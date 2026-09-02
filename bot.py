import os
import uuid
import logging
import sqlite3
from datetime import datetime
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart, Command

# =========================================================
# 1. НАСТРОЙКА ЛОГИРОВАНИЯ
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
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]   # Ваш user_id
logger.info(f"🔑 Администраторы: {ADMIN_IDS}")

DB_PATH = "news.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================================================
# 3. ФУНКЦИИ ПОЛУЧЕНИЯ ID
# =========================================================
def get_user_id(event):
    """Извлекает user_id из события."""
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
    """Извлекает chat_id для отправки сообщения."""
    if hasattr(event, 'recipient') and hasattr(event.recipient, 'chat_id'):
        return event.recipient.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'chat_id'):
        return event.message.chat_id
    if hasattr(event, 'chat_id'):
        return event.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient'):
        return event.message.recipient.chat_id
    logger.error(f"Не удалось найти chat_id в событии. Атрибуты: {dir(event)}")
    return None

# =========================================================
# 4. БАЗА ДАННЫХ (с полем file_path)
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

# =========================================================
# 5. ФУНКЦИИ РАБОТЫ С БД
# =========================================================
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

def get_pending_applications():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM news WHERE status = "pending" ORDER BY created_at ASC')
    rows = c.fetchall()
    conn.close()
    return rows

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute('SELECT COUNT(*) FROM news').fetchone()[0]
    pending = c.execute('SELECT COUNT(*) FROM news WHERE status = "pending"').fetchone()[0]
    approved = c.execute('SELECT COUNT(*) FROM news WHERE status = "approved"').fetchone()[0]
    rejected = c.execute('SELECT COUNT(*) FROM news WHERE status = "rejected"').fetchone()[0]
    conn.close()
    return total, pending, approved, rejected

# =========================================================
# 6. ХРАНИЛИЩЕ СОСТОЯНИЙ
# =========================================================
user_states = {}

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}

def clear_user_state(user_id):
    user_states.pop(str(user_id), None)

# =========================================================
# 7. НОВЫЕ ВОПРОСЫ (наводящие)
# =========================================================
QUESTIONS = [
    ('full_name', 'Расскажите о себе: ваше полное имя, должность или роль в проекте.'),
    ('action_desc', 'Опишите событие или действие, о котором хотите сообщить. Что именно произошло?'),
    ('benefit', 'Какую пользу или ценность эта новость принесёт аудитории?'),
    ('how_came', 'Как вы пришли к этому? Какие обстоятельства или предпосылки к этому привели?'),
    ('place_time', 'Где и когда произошло событие? Укажите место и дату (город, площадка, время).')
]
FILE_STEP = len(QUESTIONS)  # == 5

# =========================================================
# 8. ФУНКЦИЯ СОХРАНЕНИЯ ФАЙЛА (ТОЛЬКО ФОТО)
# =========================================================
def save_file(file_obj):
    """Сохраняет файл и возвращает путь к нему (только фото и документы)."""
    ext = file_obj.name.split('.')[-1] if '.' in file_obj.name else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    file_obj.download(file_path)
    return file_path

def is_photo_file(event):
    """Проверяет, является ли сообщение файлом с фото."""
    return hasattr(event.message, 'photo') and event.message.photo

def is_document_file(event):
    """Проверяет, является ли сообщение документом (может быть картинка)."""
    return hasattr(event.message, 'document') and event.message.document

# =========================================================
# 9. ИНИЦИАЛИЗАЦИЯ БОТА
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 10. ОБРАБОТЧИКИ КОМАНД
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить chat_id.")
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    clear_user_state(str(user_id))
    await bot.send_message(chat_id=chat_id,
        text="👋 Привет! Я бот для подачи новостей.\n"
             "Чтобы начать, отправьте /news\n"
             "Для справки используйте /help"
    )

@dp.message_created(Command(commands=['help']))
async def cmd_help(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    await bot.send_message(chat_id=chat_id,
        text="📖 Доступные команды:\n"
             "/start — начать работу\n"
             "/news — подать новость\n"
             "/cancel — отменить текущую заявку\n"
             "/id — показать ваш ID\n\n"
             "Для администраторов:\n"
             "/pending — список заявок\n"
             "/approve <id> [комментарий] — одобрить\n"
             "/reject <id> [комментарий] — отклонить\n"
             "/stats — статистика"
    )

@dp.message_created(Command(commands=['id']))
async def cmd_id(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    await bot.send_message(chat_id=chat_id, text=f"Ваш ID: {user_id}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    if get_user_state(user_id_str) is None:
        await bot.send_message(chat_id=chat_id, text="Нет активной заявки для отмены.")
        return
    clear_user_state(user_id_str)
    await bot.send_message(chat_id=chat_id, text="✅ Заявка отменена.")

@dp.message_created(Command(commands=['news']))
async def cmd_news(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    if get_user_state(user_id_str) is not None:
        await bot.send_message(chat_id=chat_id, text="У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
        return
    set_user_state(user_id_str, 0)
    await bot.send_message(chat_id=chat_id, text=QUESTIONS[0][1])

# =========================================================
# 11. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['pending']))
async def cmd_pending(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    rows = get_pending_applications()
    if not rows:
        await bot.send_message(chat_id=chat_id, text="Нет заявок.")
        return
    msg = "📋 Ожидающие заявки:\n\n"
    for row in rows:
        msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
    await bot.send_message(chat_id=chat_id, text=msg)

@dp.message_created(Command(commands=['approve']))
async def cmd_approve(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
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
        await bot.send_message(chat_id=chat_id, text=f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'approved', feedback)
    await bot.send_message(chat_id=chat_id, text=f"✅ Заявка #{app_id} одобрена.")
    try:
        user_to_notify = int(app[1])
        await bot.send_message(chat_id=user_to_notify, text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
    except Exception as e:
        logger.error(f"Не удалось уведомить автора заявки {app[1]}: {e}")

@dp.message_created(Command(commands=['reject']))
async def cmd_reject(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
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
        await bot.send_message(chat_id=chat_id, text=f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'rejected', feedback)
    await bot.send_message(chat_id=chat_id, text=f"❌ Заявка #{app_id} отклонена.")
    try:
        user_to_notify = int(app[1])
        await bot.send_message(chat_id=user_to_notify, text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
    except Exception as e:
        logger.error(f"Не удалось уведомить автора заявки {app[1]}: {e}")

@dp.message_created(Command(commands=['stats']))
async def cmd_stats(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    total, pending, approved, rejected = get_stats()
    await bot.send_message(chat_id=chat_id,
        text=f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
    )

# =========================================================
# 12. ОБРАБОТЧИК ФАЙЛОВ И ОПРОСА
# =========================================================
@dp.message_created()
async def handle_message(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        return
    user_id_str = str(user_id)
    state = get_user_state(user_id_str)
    if state is None:
        return  # не в процессе опроса

    step = state['step']
    data = state['data']

    # === ШАГ 5: Ожидание файла ===
    if step == FILE_STEP:
        # Проверяем, есть ли фото или документ
        if is_photo_file(event) or is_document_file(event):
            file_obj = event.message.photo or event.message.document
            file_path = save_file(file_obj)
            data['file_path'] = file_path
            set_user_state(user_id_str, -1, data)
            summary = (
                "📋 Проверьте введённые данные:\n\n"
                f"1. ФИО: {data.get('full_name', '—')}\n"
                f"2. Суть: {data.get('action_desc', '—')}\n"
                f"3. Польза: {data.get('benefit', '—')}\n"
                f"4. Как пришли: {data.get('how_came', '—')}\n"
                f"5. Место/время: {data.get('place_time', '—')}\n"
                f"6. Файл: {os.path.basename(file_path)}\n"
                "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
            )
            await bot.send_message(chat_id=chat_id, text=summary)
        elif event.message.text and event.message.text.strip().lower() == "пропустить":
            data['file_path'] = None
            set_user_state(user_id_str, -1, data)
            summary = (
                "📋 Проверьте введённые данные:\n\n"
                f"1. ФИО: {data.get('full_name', '—')}\n"
                f"2. Суть: {data.get('action_desc', '—')}\n"
                f"3. Польза: {data.get('benefit', '—')}\n"
                f"4. Как пришли: {data.get('how_came', '—')}\n"
                f"5. Место/время: {data.get('place_time', '—')}\n"
                f"6. Файл: не прикреплён\n"
                "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
            )
            await bot.send_message(chat_id=chat_id, text=summary)
        else:
            await bot.send_message(chat_id=chat_id,
                text="Пожалуйста, прикрепите фото (или документ) или напишите «Пропустить».")
        return

    # === ОСНОВНЫЕ ШАГИ (0-4) ===
    if step < FILE_STEP:
        if not event.message.text:
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, отправьте текстовое сообщение.")
            return
        text = event.message.text.strip()
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < FILE_STEP:
            set_user_state(user_id_str, next_step, data)
            await bot.send_message(chat_id=chat_id, text=QUESTIONS[next_step][1])
        else:
            set_user_state(user_id_str, FILE_STEP, data)
            await bot.send_message(chat_id=chat_id,
                text="Прикрепите фото, подтверждающее событие (если есть). Напишите «Пропустить», чтобы пропустить.")
        return

    # === ШАГ -1: ПОДТВЕРЖДЕНИЕ ===
    if step == -1:
        if not event.message.text:
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, отправьте текстовое сообщение.")
            return
        text = event.message.text.strip().lower()
        if text == "да":
            app_id = save_application(user_id_str, data, data.get('file_path'))
            clear_user_state(user_id_str)
            await bot.send_message(chat_id=chat_id, text="✅ Заявка успешно отправлена на модерацию!")
            admin_text = (
                f"📢 Новая заявка #{app_id}\n"
                f"От пользователя: {data.get('full_name', 'не указано')}\n"
                f"Суть: {data.get('action_desc', 'не указано')}\n"
                f"Польза: {data.get('benefit', 'не указано')}\n"
                f"Как пришёл: {data.get('how_came', 'не указано')}\n"
                f"Место/время: {data.get('place_time', 'не указано')}"
            )
            if data.get('file_path'):
                admin_text += f"\nФайл: {data['file_path']}"
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=admin_id, text=admin_text)
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        elif text == "нет":
            clear_user_state(user_id_str)
            await bot.send_message(chat_id=chat_id, text="❌ Заявка отменена.")
        else:
            await bot.send_message(chat_id=chat_id, text='Пожалуйста, ответьте "Да" или "Нет".')
        return

# =========================================================
# 13. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
