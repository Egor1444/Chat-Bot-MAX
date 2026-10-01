import os
import uuid
import logging
import sqlite3
import urllib.request
import json
import ssl
from datetime import datetime, timedelta
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart, Command

# =========================================================
# 1. ЛОГИРОВАНИЕ
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================
# 2. КОНФИГУРАЦИЯ
# =========================================================
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода.")

ADMIN_IDS = [364551480]
API_BASE = "https://platform-api2.max.ru"
DB_PATH = "news.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
PAGE_SIZE = 5

admin_chat_ids = {}
greeted_users = set()

# =========================================================
# 3. СЛОВАРЬ СТАТУСОВ
# =========================================================
STATUS_RU = {
    "pending": "⏳ На модерации",
    "approved": "✅ Одобрено",
    "rejected": "❌ Отклонено",
}

def status_ru(status):
    return STATUS_RU.get(status, status)

# =========================================================
# 4. УСТАНОВКА СПИСКА КОМАНД БОТА (для автоподсказки при "/")
# =========================================================
def set_bot_commands():
    """
    Устанавливает список команд в меню бота MAX.
    После этого при вводе "/" пользователь увидит подсказки.
    """
    url = f"{API_BASE}/me/commands"
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    }
    commands = [
        {"name": "start",    "description": "Приветствие и список команд"},
        {"name": "news",     "description": "Подать новость"},
        {"name": "cancel",   "description": "Отменить текущую заявку"},
        {"name": "help",     "description": "Справка по командам"},
        {"name": "id",       "description": "Показать ваш ID"},
        # Команды администратора (появятся у всех, но выполняются только админами)
        {"name": "list",     "description": "Список заявок (админ)"},
        {"name": "pending",  "description": "Заявки на модерации (админ)"},
        {"name": "view",     "description": "Просмотр заявки по ID (админ)"},
        {"name": "approve",  "description": "Одобрить заявку (админ)"},
        {"name": "reject",   "description": "Отклонить заявку (админ)"},
        {"name": "stats",    "description": "Статистика (админ)"},
    ]

    # Пробуем несколько возможных эндпоинтов — разные версии API MAX
    endpoints = [
        (f"{API_BASE}/me/commands", "PATCH"),
        (f"{API_BASE}/me/commands", "PUT"),
        (f"{API_BASE}/me",          "PATCH"),
    ]
    for ep_url, method in endpoints:
        try:
            data = json.dumps({"commands": commands}).encode("utf-8")
            req = urllib.request.Request(ep_url, data=data, headers=headers, method=method)
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"✅ Команды установлены через {method} {ep_url}")
                    return True
        except Exception as e:
            logger.debug(f"Не удалось установить команды через {method} {ep_url}: {e}")

    logger.warning("⚠️ API MAX не поддерживает установку команд бота — "
                   "подсказки при '/' не появятся. Всё остальное работает.")
    return False

# =========================================================
# 5. БАЗА ДАННЫХ
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            full_name TEXT,
            action_desc TEXT,
            benefit TEXT,
            how_came TEXT,
            place_time TEXT,
            content TEXT,
            file_path TEXT,
            status TEXT DEFAULT 'pending',
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_application(user_id, data, file_path=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO news 
        (user_id, full_name, action_desc, benefit, how_came, place_time, content, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        str(user_id),
        data.get('full_name', ''),
        data.get('action_desc', ''),
        data.get('benefit', ''),
        data.get('how_came', ''),
        data.get('place_time', ''),
        data.get('content', ''),
        file_path
    ))
    conn.commit()
    app_id = c.lastrowid
    conn.close()
    return app_id

def get_application_by_id(app_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM news WHERE id = ?', (app_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_status(app_id, status, feedback=''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE news SET status = ?, feedback = ? WHERE id = ?', (status, feedback, app_id))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM news').fetchone()[0]
    pending = c.execute("SELECT COUNT(*) FROM news WHERE status = 'pending'").fetchone()[0]
    approved = c.execute("SELECT COUNT(*) FROM news WHERE status = 'approved'").fetchone()[0]
    rejected = c.execute("SELECT COUNT(*) FROM news WHERE status = 'rejected'").fetchone()[0]
    conn.close()
    return total, pending, approved, rejected

def filter_applications(status=None, period=None, sort_new_first=True, limit=None, offset=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT * FROM news WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if period:
        now = datetime.now()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            start = None
        if start:
            query += " AND created_at >= ?"
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))

    order = "DESC" if sort_new_first else "ASC"
    query += f" ORDER BY created_at {order}"

    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def count_filtered(status=None, period=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT COUNT(*) FROM news WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if period:
        now = datetime.now()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            start = None
        if start:
            query += " AND created_at >= ?"
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))

    c.execute(query, params)
    count = c.fetchone()[0]
    conn.close()
    return count

# =========================================================
# 6. СОСТОЯНИЯ
# =========================================================
user_states = {}

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}

def clear_user_state(user_id):
    if user_id in user_states:
        del user_states[str(user_id)]

# =========================================================
# 7. ВОПРОСЫ
# =========================================================
QUESTIONS = [
    ('full_name', 'Расскажите о себе: ваше полное имя, должность или роль в проекте.'),
    ('action_desc', 'Опишите событие или действие, о котором хотите сообщить. Что именно произошло?'),
    ('benefit', 'Какую пользу или ценность эта новость принесёт аудитории?'),
    ('how_came', 'Как вы пришли к этому? Какие обстоятельства или предпосылки к этому привели?'),
    ('place_time', 'Где и когда произошло событие? Укажите место и дату (город, площадка, время).'),
    ('content', 'Если хотите, добавьте комментарий или дополнительную информацию (можно пропустить, отправьте «—»).')
]
FILE_STEP = len(QUESTIONS)

# =========================================================
# 8. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================
def get_user_id(event):
    if hasattr(event, 'from_user'):
        if hasattr(event.from_user, 'user_id'):
            return event.from_user.user_id
        if hasattr(event.from_user, 'id'):
            return event.from_user.id
    if hasattr(event, 'sender') and hasattr(event.sender, 'user_id'):
        return event.sender.user_id
    if hasattr(event, 'user') and hasattr(event.user, 'id'):
        return event.user.id
    return None

def get_chat_id(event):
    if hasattr(event, 'recipient') and hasattr(event.recipient, 'chat_id'):
        return event.recipient.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'chat_id'):
        return event.message.chat_id
    if hasattr(event, 'chat_id'):
        return event.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient'):
        return event.message.recipient.chat_id
    return None

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_file_from_event(event):
    msg = event.message
    for attr in ['photo', 'document', 'file', 'attachment', 'media']:
        if hasattr(msg, attr):
            val = getattr(msg, attr)
            if val:
                return val
    if hasattr(msg, 'body'):
        body = msg.body
        if hasattr(body, 'attachments') and body.attachments:
            return body.attachments[0] if isinstance(body.attachments, list) else body.attachments
        for attr in ['file', 'photo', 'document']:
            if hasattr(body, attr):
                val = getattr(body, attr)
                if val:
                    return val
    return None

def save_file(file_obj):
    name = getattr(file_obj, 'filename', None) or getattr(file_obj, 'name', None) or getattr(file_obj, 'file_name', None) or 'file'
    ext = name.split('.')[-1] if '.' in name else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    if hasattr(file_obj, 'download'):
        try:
            file_obj.download(file_path)
            return file_path
        except Exception as e:
            logger.error(f"Ошибка download: {e}")

    if hasattr(file_obj, 'payload') and hasattr(file_obj.payload, 'url'):
        url = file_obj.payload.url
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(url, context=ctx) as response:
                with open(file_path, 'wb') as f:
                    f.write(response.read())
            return file_path
        except Exception as e:
            logger.error(f"Ошибка скачивания по URL: {e}")

    if hasattr(file_obj, 'file_id'):
        return str(file_obj.file_id)
    return name

# =========================================================
# 9. БОТ
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 10. ПРИВЕТСТВИЕ
# =========================================================
async def send_greeting(chat_id, user_id=None):
    text = (
        "👋 Добро пожаловать в бот для подачи новостей!\n\n"
        "📌 Доступные команды:\n\n"
        "🔹 /news — подать новость (пошаговый опрос)\n"
        "🔹 /cancel — отменить текущую заявку\n"
        "🔹 /help — справка\n"
        "🔹 /id — показать ваш ID\n"
    )
    if user_id and user_id in ADMIN_IDS:
        text += (
            "\n🔐 Панель администратора:\n"
            "🔹 /list [статус] [период] [страница]\n"
            "   статус: pending | approved | rejected | all\n"
            "   период: today | week | month | all\n"
            "🔹 /pending — список заявок на модерации\n"
            "🔹 /view <id> — просмотреть заявку\n"
            "🔹 /stats — статистика\n"
            "🔹 /approve <id> [комментарий] — одобрить\n"
            "🔹 /reject <id> [комментарий] — отклонить"
        )
    text += "\n\n💡 Совет: введите «/», чтобы увидеть список команд."
    await bot.send_message(chat_id=chat_id, text=text)
    greeted_users.add(str(user_id))

# =========================================================
# 11. КОМАНДЫ
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    clear_user_state(str(user_id))
    await send_greeting(chat_id, user_id)

@dp.message_created(Command(commands=['help']))
async def cmd_help(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    text = (
        "📖 Команды:\n\n"
        "🔹 Для всех:\n"
        "/start — приветствие\n"
        "/news — подать новость\n"
        "/cancel — отменить заявку\n"
        "/id — ваш ID\n"
    )
    if is_admin(user_id):
        text += (
            "\n🔹 Для администраторов:\n"
            "/list [статус] [период] [страница] — список заявок\n"
            "/pending — только заявки на модерации\n"
            "/view <id> — просмотр заявки\n"
            "/stats — статистика\n"
            "/approve <id> [комментарий] — одобрить\n"
            "/reject <id> [комментарий] — отклонить\n"
        )
    text += "\n💡 Введите «/», чтобы увидеть список команд."
    await bot.send_message(chat_id=chat_id, text=text)

@dp.message_created(Command(commands=['id']))
async def cmd_id(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    role = "администратор ✅" if user_id in ADMIN_IDS else "пользователь"
    await bot.send_message(chat_id=chat_id, text=f"Ваш ID: {user_id}\nРоль: {role}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if get_user_state(str(user_id)) is not None:
        clear_user_state(str(user_id))
        await bot.send_message(chat_id=chat_id, text="✅ Заявка отменена.")
    else:
        await bot.send_message(chat_id=chat_id, text="Нет активной заявки.")

@dp.message_created(Command(commands=['news']))
async def cmd_news(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    clear_user_state(str(user_id))
    set_user_state(str(user_id), 0)
    await bot.send_message(chat_id=chat_id, text=QUESTIONS[0][1])

# =========================================================
# 12. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['list']))
async def cmd_list(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await bot.send_message(chat_id=chat_id, text="⛔ Только для администраторов.")
        return

    args = event.message.body.text.split()
    status = None
    period = None
    page = 1

    for a in args[1:]:
        a_lower = a.lower()
        if a_lower in ('pending', 'approved', 'rejected', 'all'):
            status = None if a_lower == 'all' else a_lower
        elif a_lower in ('today', 'week', 'month', 'all'):
            period = None if a_lower == 'all' else a_lower
        elif a.isdigit():
            page = int(a)

    total = count_filtered(status=status, period=period)
    if total == 0:
        await bot.send_message(chat_id=chat_id, text="Нет заявок по заданным фильтрам.")
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    rows = filter_applications(status=status, period=period, sort_new_first=True,
                               limit=PAGE_SIZE, offset=offset)

    st = status if status else "все"
    pd = period if period else "все"
    msg = f"📋 Заявки (статус: {st}, период: {pd}, стр. {page}/{total_pages}):\n\n"
    for r in rows:
        msg += (
            f"ID: {r[0]}\n"
            f"Имя: {r[2]}\n"
            f"Статус: {status_ru(r[9])}\n"
            f"Дата: {r[11]}\n\n"
        )
    msg += "Просмотр: /view <id>\nРешение: /approve <id> или /reject <id>"
    await bot.send_message(chat_id=chat_id, text=msg)

@dp.message_created(Command(commands=['pending']))
async def cmd_pending(event):
    event.message.body.text = "/list pending"
    await cmd_list(event)

@dp.message_created(Command(commands=['view']))
async def cmd_view(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await bot.send_message(chat_id=chat_id, text="⛔ Только для администраторов.")
        return

    args = event.message.body.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /view <id>")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return

    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return

    text = (
        f"📄 Заявка #{app_id}\n\n"
        f"Пользователь: {app[2]}\n"
        f"Суть: {app[3]}\n"
        f"Польза: {app[4]}\n"
        f"Как пришёл: {app[5]}\n"
        f"Место и время: {app[6]}\n"
        f"Комментарий: {app[7] or '—'}\n"
        f"Статус: {status_ru(app[9])}\n"
        f"Комментарий админа: {app[10] or '—'}\n"
        f"Создана: {app[11]}"
    )
    if app[8] and os.path.exists(app[8]):
        try:
            if hasattr(bot, 'send_file'):
                await bot.send_file(chat_id=chat_id, file=app[8], caption=text)
            else:
                await bot.send_message(chat_id=chat_id, text=text + f"\n📎 Файл: {app[8]}")
            return
        except Exception as e:
            logger.error(f"Ошибка отправки файла: {e}")
            await bot.send_message(chat_id=chat_id, text=text + f"\n📎 Файл: {app[8]}")
    else:
        await bot.send_message(chat_id=chat_id, text=text)

@dp.message_created(Command(commands=['stats']))
async def cmd_stats(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await bot.send_message(chat_id=chat_id, text="⛔ Только для администраторов.")
        return
    total, pending, approved, rejected = get_stats()
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📊 Статистика заявок:\n"
            f"Всего: {total}\n"
            f"{status_ru('pending')}: {pending}\n"
            f"{status_ru('approved')}: {approved}\n"
            f"{status_ru('rejected')}: {rejected}"
        )
    )

@dp.message_created(Command(commands=['approve']))
async def cmd_approve(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await bot.send_message(chat_id=chat_id, text="⛔ Только для администраторов.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /approve <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await bot.send_message(chat_id=chat_id,
            text=f"Заявка уже обработана ({status_ru(app[9])}).")
        return
    update_status(app_id, 'approved', feedback)
    await bot.send_message(chat_id=chat_id, text=f"✅ Заявка #{app_id} одобрена.")
    try:
        await bot.send_message(
            chat_id=int(app[1]),
            text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback or 'нет'}"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")

@dp.message_created(Command(commands=['reject']))
async def cmd_reject(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await bot.send_message(chat_id=chat_id, text="⛔ Только для администраторов.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /reject <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await bot.send_message(chat_id=chat_id,
            text=f"Заявка уже обработана ({status_ru(app[9])}).")
        return
    update_status(app_id, 'rejected', feedback)
    await bot.send_message(chat_id=chat_id, text=f"❌ Заявка #{app_id} отклонена.")
    try:
        await bot.send_message(
            chat_id=int(app[1]),
            text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback or 'не указана'}"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")

# =========================================================
# 13. ОСНОВНОЙ ОБРАБОТЧИК
# =========================================================
@dp.message_created()
async def handle_message(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    user_id_str = str(user_id)

    if user_id in ADMIN_IDS:
        admin_chat_ids[user_id] = chat_id

    # Авто-приветствие при первом контакте
    if user_id_str not in greeted_users:
        text_preview = ""
        if hasattr(event.message, 'body') and hasattr(event.message.body, 'text'):
            text_preview = (event.message.body.text or "").strip()
        if not text_preview.startswith("/start"):
            await send_greeting(chat_id, user_id)

    state = get_user_state(user_id_str)
    if state is None:
        return

    step = state['step']
    data = state['data']

    # Шаг файла
    if step == FILE_STEP:
        file_obj = get_file_from_event(event)
        file_path = None

        if file_obj is not None:
            try:
                file_path = save_file(file_obj)
                data['file_path'] = file_path
            except Exception as e:
                logger.error(f"Ошибка сохранения: {e}")
                await bot.send_message(chat_id=chat_id, text="Не удалось сохранить файл.")
                return
        else:
            if hasattr(event.message, 'body') and hasattr(event.message.body, 'text'):
                text = event.message.body.text.strip().lower()
                if text in ("пропустить", "—"):
                    data['file_path'] = None
                else:
                    await bot.send_message(chat_id=chat_id,
                        text="Прикрепите фото/документ или напишите «Пропустить».")
                    return
            else:
                await bot.send_message(chat_id=chat_id,
                    text="Прикрепите фото/документ или напишите «Пропустить».")
                return

        app_id = save_application(user_id_str, data, data.get('file_path'))
        clear_user_state(user_id_str)
        await bot.send_message(chat_id=chat_id, text="✅ Заявка отправлена на модерацию!")

        admin_note = (
            f"📢 Новая заявка #{app_id}\n"
            f"От: {data.get('full_name', '—')}\n"
            f"Статус: {status_ru('pending')}\n\n"
            f"Просмотр: /view {app_id}\n"
            f"Решение: /approve {app_id} или /reject {app_id}"
        )
        for admin_id in ADMIN_IDS:
            cid = admin_chat_ids.get(admin_id)
            if cid:
                try:
                    await bot.send_message(chat_id=cid, text=admin_note)
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        return

    # Основные вопросы
    if step < FILE_STEP:
        if not hasattr(event.message, 'body') or not hasattr(event.message.body, 'text'):
            await bot.send_message(chat_id=chat_id, text="Отправьте текстовое сообщение.")
            return
        text = event.message.body.text.strip()
        if not text:
            await bot.send_message(chat_id=chat_id, text="Отправьте текстовое сообщение.")
            return
        if step == 5 and text == "—":
            text = ""
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < FILE_STEP:
            set_user_state(user_id_str, next_step, data)
            await bot.send_message(chat_id=chat_id, text=QUESTIONS[next_step][1])
        else:
            set_user_state(user_id_str, FILE_STEP, data)
            await bot.send_message(chat_id=chat_id,
                text="Прикрепите фото/документ, подтверждающее событие. Или напишите «Пропустить».")
        return

# =========================================================
# 14. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    set_bot_commands()   # регистрируем команды для автоподсказки при "/"
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
