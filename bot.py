import os
import uuid
import logging
import sqlite3
import smtplib
import urllib.request
import json
import ssl
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart, Command
from maxapi.types import ButtonsPayload, CallbackButton

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
MODERATOR_IDS = [
    # 111222333,
]
ADMIN_PASSWORD = "admin123"

SMTP_SERVER = "smtp.mail.ru"
SMTP_PORT = 465
SMTP_USER = "rockefelle@mail.ru"
SMTP_PASSWORD = "H0cCiGs91yPk2EuOMIls"
ADMIN_EMAIL = "rockefelle@mail.ru"

API_BASE = "https://platform-api2.max.ru"
DB_PATH = "news.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
PAGE_SIZE = 5

admin_chat_ids = {}
greeted_users = set()
admin_authenticated = set()

# =========================================================
# 3. СТАТУСЫ
# =========================================================
STATUS_RU = {
    "pending":  "⏳ На модерации",
    "approved": "✅ Одобрено",
    "rejected": "❌ Отклонено",
}

def status_ru(status):
    return STATUS_RU.get(status, status)

# =========================================================
# 3.1. КНОПКИ (inline keyboard MAX Bot API)
# =========================================================
def kb(rows):
    """
    rows: [[{"text": "...", "payload": "..."}], ...]
    Возвращает Pydantic-модель вложения inline_keyboard.
    """
    buttons = []
    for row in rows:
        btn_row = []
        for b in row:
            btn_row.append(
                CallbackButton(text=b["text"], payload=b["payload"])
            )
        buttons.append(btn_row)
    return ButtonsPayload(buttons=buttons).pack()

def main_menu_kb(user_id):
    rows = [
        [{"text": "📝 Подать новость", "payload": "cmd:news"}],
        [
            {"text": "📄 Мои заявки", "payload": "cmd:mystatus"},
            {"text": "❓ Помощь", "payload": "cmd:help"},
        ],
    ]
    if is_admin(user_id):
        rows.append([{"text": "🔐 Админ-панель", "payload": "cmd:admin"}])
    return kb(rows)

def application_actions_kb(app_id, with_view=True):
    rows = []
    if with_view:
        rows.append([{"text": f"📄 Просмотр #{app_id}", "payload": f"view:{app_id}"}])
    rows.append([
        {"text": "✅ Одобрить", "payload": f"approve:{app_id}"},
        {"text": "❌ Отклонить", "payload": f"reject:{app_id}"},
    ])
    return kb(rows)

def applications_list_kb(apps):
    if not apps:
        return None
    rows = []
    for app in apps:
        app_id = app[0]
        rows.append([
            {"text": f"📄 #{app_id}", "payload": f"view:{app_id}"},
            {"text": "✅", "payload": f"approve:{app_id}"},
            {"text": "❌", "payload": f"reject:{app_id}"},
        ])
    return kb(rows)

def admin_panel_kb():
    return kb([
        [
            {"text": "⏳ На модерации", "payload": "cmd:pending"},
            {"text": "📊 Статистика", "payload": "cmd:stats"},
        ],
        [
            {"text": "📋 Все заявки", "payload": "cmd:list"},
        ],
        [
            {"text": "🔒 Выйти", "payload": "cmd:logout"},
        ],
    ])

# =========================================================
# 4. ПОЧТА
# =========================================================
def send_email_with_attachment(subject: str, body: str, file_path: str = None) -> bool:
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if file_path and os.path.exists(file_path):
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context, timeout=30) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"📧 Письмо отправлено на {ADMIN_EMAIL}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки письма: {e}")
        return False

# =========================================================
# 5. КОМАНДЫ БОТА
# =========================================================
def set_bot_commands():
    headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
    commands = [
        {"name": "start",     "description": "Приветствие и меню"},
        {"name": "news",      "description": "Подать новость"},
        {"name": "mystatus",  "description": "Статус моих заявок"},
        {"name": "cancel",    "description": "Отменить черновик или отозвать заявку"},
        {"name": "help",      "description": "Справка"},
        {"name": "id",        "description": "Мой ID"},
        {"name": "admin",     "description": "Вход в админ-панель"},
        {"name": "logout",    "description": "Выйти из админ-панели"},
        {"name": "list",      "description": "Список заявок"},
        {"name": "pending",   "description": "Заявки на модерации"},
        {"name": "view",      "description": "Просмотр заявки"},
        {"name": "approve",   "description": "Одобрить заявку"},
        {"name": "reject",    "description": "Отклонить заявку"},
        {"name": "stats",     "description": "Статистика"},
    ]
    for ep_url, method in [
        (f"{API_BASE}/me/commands", "PATCH"),
        (f"{API_BASE}/me/commands", "PUT"),
        (f"{API_BASE}/me",          "PATCH"),
    ]:
        try:
            data = json.dumps({"commands": commands}).encode("utf-8")
            req = urllib.request.Request(ep_url, data=data, headers=headers, method=method)
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx) as resp:
                if 200 <= resp.status < 300:
                    logger.info(f"✅ Команды установлены через {method} {ep_url}")
                    return True
        except Exception as e:
            logger.debug(f"Не удалось через {method} {ep_url}: {e}")
    logger.warning("⚠️ API MAX не поддерживает установку команд бота.")
    return False

# =========================================================
# 6. БАЗА ДАННЫХ
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
    logger.info(f"💾 save_application: user_id={user_id!r} type={type(user_id).__name__}")
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

def get_applications_by_user(user_id):
    logger.info(f"🔍 get_applications_by_user: user_id={user_id!r} type={type(user_id).__name__}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM news WHERE user_id = ? ORDER BY created_at DESC', (str(user_id),))
    rows = c.fetchall()
    conn.close()
    return rows

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

def _period_start(period):
    now = datetime.now()
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None

def filter_applications(status=None, period=None, sort_new_first=True, limit=None, offset=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT * FROM news WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if period:
        start = _period_start(period)
        if start:
            query += " AND created_at >= ?"
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
    query += f" ORDER BY created_at {'DESC' if sort_new_first else 'ASC'}"
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
        start = _period_start(period)
        if start:
            query += " AND created_at >= ?"
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
    c.execute(query, params)
    count = c.fetchone()[0]
    conn.close()
    return count

# =========================================================
# 7. СОСТОЯНИЯ
# =========================================================
user_states = {}
WAITING_ADMIN_PASSWORD = -100

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    user_states[str(user_id)] = {'step': step, 'data': data or {}}

def clear_user_state(user_id):
    user_states.pop(str(user_id), None)

# =========================================================
# 8. ВОПРОСЫ
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
# 9. ХЕЛПЕРЫ
# =========================================================
def _normalize_uid(uid):
    if uid is None:
        return None
    return str(uid).strip()

def get_user_id(event):
    uid = None
    if hasattr(event, 'from_user'):
        if hasattr(event.from_user, 'user_id'):
            uid = event.from_user.user_id
        elif hasattr(event.from_user, 'id'):
            uid = event.from_user.id
    if uid is None and hasattr(event, 'sender') and hasattr(event.sender, 'user_id'):
        uid = event.sender.user_id
    if uid is None and hasattr(event, 'user') and hasattr(event.user, 'id'):
        uid = event.user.id
    if uid is None and hasattr(event, 'message') and hasattr(event.message, 'sender'):
        s = event.message.sender
        if hasattr(s, 'user_id'):
            uid = s.user_id
        elif hasattr(s, 'id'):
            uid = s.id
    if uid is None and hasattr(event, 'callback') and hasattr(event.callback, 'user'):
        u = event.callback.user
        if hasattr(u, 'user_id'):
            uid = u.user_id
        elif hasattr(u, 'id'):
            uid = u.id
    return _normalize_uid(uid)

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

def get_callback_payload(event):
    if hasattr(event, 'callback') and hasattr(event.callback, 'payload'):
        return event.callback.payload
    if hasattr(event, 'payload'):
        return event.payload
    return None

def is_admin(user_id):
    return str(user_id) in {str(x) for x in ADMIN_IDS}

def is_moderator(user_id):
    return str(user_id) in {str(x) for x in MODERATOR_IDS}

def can_moderate(user_id):
    return is_admin(user_id) or is_moderator(user_id)

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
            if os.path.exists(file_path):
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

    logger.warning(f"Файл не сохранён (name={name})")
    return None

# =========================================================
# 10. БОТ
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 11. ОТПРАВКА ЭКРАНОВ
# =========================================================
async def _send(chat_id, text, attachments=None):
    kwargs = {}
    if attachments:
        kwargs['attachments'] = attachments
    await bot.send_message(chat_id=chat_id, text=text, **kwargs)

async def send_greeting(chat_id, user_id=None):
    text = (
        "👋 Добро пожаловать в бот для подачи новостей!\n\n"
        "Нажмите кнопку ниже или используйте команды:\n"
        "🔹 /news — подать новость\n"
        "🔹 /mystatus — проверить статус заявок\n"
        "🔹 /cancel — отменить черновик или отозвать заявку\n"
    )
    await _send(chat_id, text, attachments=[main_menu_kb(user_id)] if user_id else None)
    if user_id:
        greeted_users.add(str(user_id))

async def send_admin_menu(chat_id):
    text = (
        "🔐 Админ-панель.\n\n"
        "Выберите действие кнопкой или используйте команды:\n"
        "🔹 /list [статус] [период] [страница]\n"
        "🔹 /pending — заявки на модерации\n"
        "🔹 /view <id> — просмотр заявки\n"
        "🔹 /approve <id> [комм.] — одобрить\n"
        "🔹 /reject <id> [комм.] — отклонить\n"
        "🔹 /stats — статистика\n"
        "🔹 /logout — выход"
    )
    await _send(chat_id, text, attachments=[admin_panel_kb()])

async def send_view(chat_id, app_id):
    app = get_application_by_id(app_id)
    if not app:
        await _send(chat_id, f"Заявка #{app_id} не найдена.")
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
    attachments = None
    if app[9] == 'pending':
        attachments = [application_actions_kb(app_id, with_view=False)]
    await _send(chat_id, text, attachments=attachments)
    if app[8] and os.path.exists(app[8]):
        try:
            if hasattr(bot, 'send_file'):
                await bot.send_file(chat_id=chat_id, file=app[8])
        except Exception as e:
            logger.error(f"Ошибка отправки файла: {e}")

async def send_pending(chat_id):
    status = 'pending'
    total = count_filtered(status=status)
    if total == 0:
        await _send(chat_id, "Заявок на модерации нет.")
        return
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    rows = filter_applications(status=status, limit=PAGE_SIZE, offset=0)
    msg = f"⏳ Заявки на модерации (стр. 1/{total_pages}):\n\n"
    for r in rows:
        msg += f"ID: {r[0]} — {r[2]} — {r[11]}\n"
    await _send(chat_id, msg, attachments=[applications_list_kb(rows)])

async def send_list(chat_id, status=None, period=None, page=1):
    total = count_filtered(status=status, period=period)
    if total == 0:
        await _send(chat_id, "Нет заявок по заданным фильтрам.")
        return
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE
    rows = filter_applications(status=status, period=period, limit=PAGE_SIZE, offset=offset)
    st = status or "все"
    pd = period or "все"
    msg = f"📋 Заявки (статус: {st}, период: {pd}, стр. {page}/{total_pages}):\n\n"
    for r in rows:
        msg += f"ID: {r[0]} — {r[2]} — {status_ru(r[9])} — {r[11]}\n"
    await _send(chat_id, msg, attachments=[applications_list_kb(rows)])

async def send_stats(chat_id):
    total, pending, approved, rejected = get_stats()
    await _send(
        chat_id,
        f"📊 Статистика:\n"
        f"Всего: {total}\n"
        f"{status_ru('pending')}: {pending}\n"
        f"{status_ru('approved')}: {approved}\n"
        f"{status_ru('rejected')}: {rejected}"
    )

async def apply_approve(chat_id, app_id, feedback=""):
    app = get_application_by_id(app_id)
    if not app:
        await _send(chat_id, f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await _send(chat_id, f"Заявка уже обработана ({status_ru(app[9])}).")
        return
    update_status(app_id, 'approved', feedback)
    await _send(chat_id, f"✅ Заявка #{app_id} одобрена.")
    try:
        await bot.send_message(
            chat_id=int(app[1]),
            text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback or 'нет'}"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")

async def apply_reject(chat_id, app_id, feedback=""):
    app = get_application_by_id(app_id)
    if not app:
        await _send(chat_id, f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await _send(chat_id, f"Заявка уже обработана ({status_ru(app[9])}).")
        return
    update_status(app_id, 'rejected', feedback)
    await _send(chat_id, f"❌ Заявка #{app_id} отклонена.")
    try:
        await bot.send_message(
            chat_id=int(app[1]),
            text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback or 'не указана'}"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя: {e}")

# =========================================================
# 12. КОМАНДЫ ПОЛЬЗОВАТЕЛЯ
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    clear_user_state(user_id)
    await send_greeting(chat_id, user_id)

@dp.message_created(Command(commands=['help']))
async def cmd_help(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    text = (
        "📖 Команды:\n\n"
        "/start — приветствие\n"
        "/news — подать новость\n"
        "/mystatus — статус моих заявок\n"
        "/cancel — отменить черновик или отозвать заявку\n"
        "/id — мой ID\n"
    )
    if is_admin(user_id):
        text += "\n🔹 Для администратора:\n/admin — вход, /logout — выход\n"
    await _send(chat_id, text, attachments=[main_menu_kb(user_id)])

@dp.message_created(Command(commands=['id']))
async def cmd_id(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if is_admin(user_id):
        role = "администратор ✅"
    elif is_moderator(user_id):
        role = "модератор ✅"
    else:
        role = "пользователь"
    auth = "авторизован" if user_id in admin_authenticated else "не авторизован"
    await _send(chat_id, f"Ваш ID: {user_id}\nРоль: {role}\nСтатус админа: {auth}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if get_user_state(user_id) is not None:
        clear_user_state(user_id)
        await _send(chat_id, "✅ Черновик заявки отменён.")
        return
    rows = get_applications_by_user(user_id)
    pending = [r for r in rows if r[9] == 'pending']
    if not pending:
        await _send(chat_id, "Нет активной заявки для отмены.")
        return
    last_id = pending[0][0]
    update_status(last_id, 'rejected', 'Отозвана автором')
    await _send(chat_id, f"✅ Заявка #{last_id} отозвана.\nСтатус: {status_ru('rejected')}")

@dp.message_created(Command(commands=['news']))
async def cmd_news(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    clear_user_state(user_id)
    set_user_state(user_id, 0)
    await _send(chat_id, QUESTIONS[0][1])

@dp.message_created(Command(commands=['mystatus']))
async def cmd_mystatus(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    state = get_user_state(user_id)
    rows = get_applications_by_user(user_id)
    parts = []
    if state is not None:
        step = state['step']
        total = len(QUESTIONS) + 1
        parts.append(
            f"📝 Незавершённый черновик (шаг {min(step + 1, total)} из {total}).\n"
            f"Продолжите или отмените командой /cancel."
        )
    if rows:
        msg = f"📄 Ваши заявки ({len(rows)}):\n\n"
        for r in rows:
            text_field = r[3] or ''
            short = text_field[:60] + ('...' if len(text_field) > 60 else '')
            msg += f"ID: {r[0]}\nТекст: {short}\nСтатус: {status_ru(r[9])}\n"
            if r[10]:
                msg += f"Комментарий: {r[10]}\n"
            msg += f"Отправлено: {r[11]}\n\n"
        msg += "📌 Отозвать последнюю: /cancel"
        parts.append(msg)
    if not parts:
        await _send(chat_id, "📭 У вас пока нет заявок.")
        return
    await _send(chat_id, "\n\n".join(parts))

# =========================================================
# 13. ВХОД / ВЫХОД
# =========================================================
@dp.message_created(Command(commands=['admin']))
async def cmd_admin(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if not is_admin(user_id):
        await _send(chat_id, "⛔ Доступ запрещён.")
        return
    if user_id in admin_authenticated:
        await _send(chat_id, "🔓 Вы уже авторизованы.")
        await send_admin_menu(chat_id)
        return
    set_user_state(user_id, WAITING_ADMIN_PASSWORD)
    await _send(chat_id, "🔐 Введите пароль администратора:")

@dp.message_created(Command(commands=['logout']))
async def cmd_logout(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    if user_id in admin_authenticated:
        admin_authenticated.discard(user_id)
        await _send(chat_id, "🔒 Вы вышли из админ-панели.")
    else:
        await _send(chat_id, "Вы не авторизованы.")

def admin_required(func):
    @wraps(func)
    async def wrapper(event):
        chat_id = get_chat_id(event)
        user_id = get_user_id(event)
        if chat_id is None or user_id is None:
            return
        if not can_moderate(user_id):
            await _send(chat_id, "⛔ Доступ запрещён.")
            return
        if is_admin(user_id) and user_id not in admin_authenticated:
            await _send(chat_id, "🔒 Требуется авторизация. Введите /admin и укажите пароль.")
            return
        return await func(event)
    return wrapper

# =========================================================
# 14. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['list']))
@admin_required
async def cmd_list(event):
    chat_id = get_chat_id(event)
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
    await send_list(chat_id, status=status, period=period, page=page)

@dp.message_created(Command(commands=['pending']))
@admin_required
async def cmd_pending(event):
    chat_id = get_chat_id(event)
    await send_pending(chat_id)

@dp.message_created(Command(commands=['view']))
@admin_required
async def cmd_view(event):
    chat_id = get_chat_id(event)
    args = event.message.body.text.split(maxsplit=1)
    if len(args) < 2:
        await _send(chat_id, "Использование: /view <id>")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await _send(chat_id, "ID должен быть числом.")
        return
    await send_view(chat_id, app_id)

@dp.message_created(Command(commands=['stats']))
@admin_required
async def cmd_stats(event):
    chat_id = get_chat_id(event)
    await send_stats(chat_id)

@dp.message_created(Command(commands=['approve']))
@admin_required
async def cmd_approve(event):
    chat_id = get_chat_id(event)
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await _send(chat_id, "Использование: /approve <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await _send(chat_id, "ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    await apply_approve(chat_id, app_id, feedback)

@dp.message_created(Command(commands=['reject']))
@admin_required
async def cmd_reject(event):
    chat_id = get_chat_id(event)
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await _send(chat_id, "Использование: /reject <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await _send(chat_id, "ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    await apply_reject(chat_id, app_id, feedback)

# =========================================================
# 15. ОБРАБОТКА CALLBACK-КНОПОК
# =========================================================
@dp.message_callback()
async def handle_callback(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return

    payload = get_callback_payload(event)
    if not payload:
        return

    # ---- Команды, доступные всем ----
    if payload == "cmd:news":
        clear_user_state(user_id)
        set_user_state(user_id, 0)
        await _send(chat_id, QUESTIONS[0][1])
        return
    if payload == "cmd:mystatus":
        state = get_user_state(user_id)
        rows = get_applications_by_user(user_id)
        parts = []
        if state is not None:
            step = state['step']
            total = len(QUESTIONS) + 1
            parts.append(
                f"📝 Незавершённый черновик (шаг {min(step + 1, total)} из {total}).\n"
                f"Продолжите или отмените командой /cancel."
            )
        if rows:
            msg = f"📄 Ваши заявки ({len(rows)}):\n\n"
            for r in rows:
                short = (r[3] or '')[:60] + ('...' if len(r[3] or '') > 60 else '')
                msg += f"ID: {r[0]}\nТекст: {short}\nСтатус: {status_ru(r[9])}\n\n"
            parts.append(msg)
        await _send(chat_id, "\n\n".join(parts) if parts else "📭 У вас пока нет заявок.")
        return
    if payload == "cmd:help":
        await _send(
            chat_id,
            "📖 Команды:\n/news — подать\n/mystatus — статус\n/cancel — отмена\n/help — справка",
            attachments=[main_menu_kb(user_id)]
        )
        return
    if payload == "cmd:admin":
        if not is_admin(user_id):
            await _send(chat_id, "⛔ Доступ запрещён.")
            return
        if user_id in admin_authenticated:
            await send_admin_menu(chat_id)
        else:
            set_user_state(user_id, WAITING_ADMIN_PASSWORD)
            await _send(chat_id, "🔐 Введите пароль администратора:")
        return

    # ---- Дальше только модерация ----
    if not can_moderate(user_id):
        await _send(chat_id, "⛔ Доступ запрещён.")
        return
    if is_admin(user_id) and user_id not in admin_authenticated:
        await _send(chat_id, "🔒 Требуется авторизация. /admin")
        return

    if payload == "cmd:pending":
        await send_pending(chat_id)
    elif payload == "cmd:stats":
        await send_stats(chat_id)
    elif payload == "cmd:list":
        await send_list(chat_id)
    elif payload == "cmd:logout":
        admin_authenticated.discard(user_id)
        await _send(chat_id, "🔒 Вы вышли из админ-панели.")
    elif payload.startswith("view:"):
        await send_view(chat_id, int(payload.split(":", 1)[1]))
    elif payload.startswith("approve:"):
        await apply_approve(chat_id, int(payload.split(":", 1)[1]))
    elif payload.startswith("reject:"):
        await apply_reject(chat_id, int(payload.split(":", 1)[1]))

# =========================================================
# 16. ОСНОВНОЙ ОБРАБОТЧИК
# =========================================================
@dp.message_created()
async def handle_message(event):
    chat_id = get_chat_id(event)
    user_id = get_user_id(event)
    if chat_id is None or user_id is None:
        return
    user_id_str = str(user_id)

    raw_text = ""
    if hasattr(event.message, 'body') and hasattr(event.message.body, 'text'):
        raw_text = (event.message.body.text or "").strip()
    if raw_text.startswith('/'):
        return

    if is_admin(user_id):
        admin_chat_ids[user_id] = chat_id

    if user_id_str not in greeted_users:
        if not raw_text.startswith("/start"):
            await send_greeting(chat_id, user_id)

    state = get_user_state(user_id_str)
    if state is None:
        return

    step = state['step']
    data = state['data']

    # Ввод пароля
    if step == WAITING_ADMIN_PASSWORD:
        if not raw_text:
            await _send(chat_id, "Введите пароль текстом.")
            return
        if raw_text == ADMIN_PASSWORD:
            admin_authenticated.add(user_id)
            clear_user_state(user_id_str)
            await _send(chat_id, "✅ Пароль верный.")
            await send_admin_menu(chat_id)
        else:
            clear_user_state(user_id_str)
            await _send(chat_id, "❌ Неверный пароль. Вход отменён.")
        return

    # Шаг файла
    if step == FILE_STEP:
        file_obj = get_file_from_event(event)
        if file_obj is not None:
            try:
                file_path = save_file(file_obj)
                data['file_path'] = file_path
            except Exception as e:
                logger.error(f"Ошибка сохранения: {e}")
                await _send(chat_id, "Не удалось сохранить файл.")
                return
        else:
            if raw_text and raw_text.lower() in ("пропустить", "—"):
                data['file_path'] = None
            else:
                await _send(chat_id, "Прикрепите фото/документ или напишите «Пропустить».")
                return

        app_id = save_application(user_id_str, data, data.get('file_path'))
        clear_user_state(user_id_str)
        await _send(chat_id, "✅ Заявка отправлена на модерацию!")

        email_body = (
            f"Новая заявка #{app_id}\n\n"
            f"ФИО / роль: {data.get('full_name', '—')}\n"
            f"Что сделано: {data.get('action_desc', '—')}\n"
            f"Польза: {data.get('benefit', '—')}\n"
            f"Как пришёл: {data.get('how_came', '—')}\n"
            f"Место и время: {data.get('place_time', '—')}\n"
            f"Комментарий: {data.get('content', '—')}\n\n"
            f"ID пользователя: {user_id_str}\n"
            f"Статус: {status_ru('pending')}\n"
            f"Создано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        send_email_with_attachment(f"Заявка #{app_id} из бота MAX", email_body, data.get('file_path'))

        admin_note = (
            f"📢 Новая заявка #{app_id}\n"
            f"От: {data.get('full_name', '—')}\n"
            f"Статус: {status_ru('pending')}"
        )
        admin_kb = kb([
            [{"text": f"📄 Просмотр #{app_id}", "payload": f"view:{app_id}"}],
            [
                {"text": "✅ Одобрить", "payload": f"approve:{app_id}"},
                {"text": "❌ Отклонить", "payload": f"reject:{app_id}"},
            ],
        ])
        for admin_id in ADMIN_IDS:
            cid = admin_chat_ids.get(admin_id)
            if cid:
                try:
                    await _send(cid, admin_note, attachments=[admin_kb])
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        return

    # Основные вопросы
    if step < FILE_STEP:
        if not raw_text:
            await _send(chat_id, "Отправьте текстовое сообщение.")
            return
        if step == 5 and raw_text == "—":
            raw_text = ""
        field = QUESTIONS[step][0]
        data[field] = raw_text
        next_step = step + 1
        if next_step < FILE_STEP:
            set_user_state(user_id_str, next_step, data)
            await _send(chat_id, QUESTIONS[next_step][1])
        else:
            set_user_state(user_id_str, FILE_STEP, data)
            await _send(chat_id, "Прикрепите фото/документ или напишите «Пропустить».")
        return

# =========================================================
# 17. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    set_bot_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
