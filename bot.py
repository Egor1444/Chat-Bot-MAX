import os
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
DB_PATH = "news.db"

# =========================================================
# 3. БАЗА ДАННЫХ
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
            status TEXT DEFAULT 'pending',
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# =========================================================
# 4. ФУНКЦИИ РАБОТЫ С БД
# =========================================================
def save_application(user_id, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO news 
        (user_id, full_name, action_desc, benefit, how_came, place_time, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        str(user_id),
        data.get('full_name', ''),
        data.get('action_desc', ''),
        data.get('benefit', ''),
        data.get('how_came', ''),
        data.get('place_time', ''),
        data.get('content', '')
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
# 5. ХРАНИЛИЩЕ СОСТОЯНИЙ (ручное, без FSM)
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
# 6. ВОПРОСЫ
# =========================================================
QUESTIONS = [
    ('full_name', 'Вопрос 1 из 5. Ваше полное имя (ФИО)?'),
    ('action_desc', 'Вопрос 2 из 5. Опишите суть события или действия.'),
    ('benefit', 'Вопрос 3 из 5. Какую пользу принесёт публикация?'),
    ('how_came', 'Вопрос 4 из 5. Как вы пришли к этому событию?'),
    ('place_time', 'Вопрос 5 из 5. Где и когда произошло событие?')
]
TOTAL_QUESTIONS = len(QUESTIONS)

# =========================================================
# 7. ПОЛУЧЕНИЕ USER_ID (универсальное)
# =========================================================
def get_user_id(event):
    """
    Пытается извлечь user_id из события, перебирая возможные атрибуты.
    """
    # Пробуем from_user (основной вариант)
    if hasattr(event, 'from_user') and event.from_user:
        user_obj = event.from_user
        # Перебираем возможные имена атрибутов
        for attr in ['user_id', 'id', 'uid', 'pk']:
            if hasattr(user_obj, attr):
                value = getattr(user_obj, attr)
                if value is not None:
                    return value

    # Пробуем sender.user_id
    if hasattr(event, 'sender') and hasattr(event.sender, 'user_id'):
        return event.sender.user_id

    # Пробуем user.id
    if hasattr(event, 'user') and hasattr(event.user, 'id'):
        return event.user.id

    # Если ничего не найдено, логируем и возвращаем None
    logger.error(f"Не удалось найти user_id. Атрибуты event: {dir(event)}")
    return None

# =========================================================
# 8. ИНИЦИАЛИЗАЦИЯ БОТА
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 9. ОБРАБОТЧИКИ КОМАНД
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    clear_user_state(str(user_id))
    await event.message.answer(
        "👋 Привет! Я бот для подачи новостей.\n"
        "Чтобы начать, отправьте /news\n"
        "Для справки используйте /help"
    )

@dp.message_created(Command(commands=['help']))
async def cmd_help(event):
    await event.message.answer(
        "📖 Доступные команды:\n"
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
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    await event.message.answer(f"Ваш ID: {user_id}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    if get_user_state(user_id_str) is None:
        await event.message.answer("Нет активной заявки для отмены.")
        return
    clear_user_state(user_id_str)
    await event.message.answer("✅ Заявка отменена.")

# =========================================================
# 10. ОПРОС (/news)
# =========================================================
@dp.message_created(Command(commands=['news']))
async def cmd_news(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    if get_user_state(user_id_str) is not None:
        await event.message.answer("У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
        return
    set_user_state(user_id_str, 0)
    await event.message.answer(QUESTIONS[0][1])

@dp.message_created()
async def handle_message(event):
    user_id = get_user_id(event)
    if user_id is None:
        return
    user_id_str = str(user_id)
    state = get_user_state(user_id_str)
    if state is None:
        return  # пользователь не в процессе опроса

    if not hasattr(event.message, 'body') or not hasattr(event.message.body, 'text'):
        await event.message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    text = event.message.body.text.strip()
    step = state['step']
    data = state['data']

    # === Режим подтверждения ===
    if step == -1:
        if text.lower() == "да":
            app_id = save_application(user_id_str, data)
            clear_user_state(user_id_str)
            await event.message.answer("✅ Заявка успешно отправлена на модерацию!")
            # Уведомление админам
            admin_text = (
                f"📢 Новая заявка #{app_id}\n"
                f"От пользователя: {data.get('full_name', 'не указано')}\n"
                f"Суть: {data.get('action_desc', 'не указано')}\n"
                f"Польза: {data.get('benefit', 'не указано')}\n"
                f"Как пришёл: {data.get('how_came', 'не указано')}\n"
                f"Место/время: {data.get('place_time', 'не указано')}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=admin_id, text=admin_text)
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        elif text.lower() == "нет":
            clear_user_state(user_id_str)
            await event.message.answer("❌ Заявка отменена.")
        else:
            await event.message.answer('Пожалуйста, ответьте "Да" или "Нет".')
        return

    # === Основной опрос ===
    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id_str, next_step, data)
            await event.message.answer(QUESTIONS[next_step][1])
        else:
            set_user_state(user_id_str, -1, data)
            summary = (
                "📋 Проверьте введённые данные:\n\n"
                f"1. ФИО: {data.get('full_name', '—')}\n"
                f"2. Суть: {data.get('action_desc', '—')}\n"
                f"3. Польза: {data.get('benefit', '—')}\n"
                f"4. Как пришли: {data.get('how_came', '—')}\n"
                f"5. Место/время: {data.get('place_time', '—')}\n"
                "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
            )
            await event.message.answer(summary)

# =========================================================
# 11. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['pending']))
async def cmd_pending(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await event.message.answer("⛔ Нет прав.")
        return
    rows = get_pending_applications()
    if not rows:
        await event.message.answer("Нет заявок.")
        return
    msg = "📋 Ожидающие заявки:\n\n"
    for row in rows:
        msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
    await event.message.answer(msg)

@dp.message_created(Command(commands=['approve']))
async def cmd_approve(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await event.message.answer("⛔ Нет прав.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await event.message.answer("Использование: /approve <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await event.message.answer("ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await event.message.answer(f"Заявка #{app_id} не найдена.")
        return
    if app[8] != 'pending':
        await event.message.answer(f"Заявка уже обработана (статус: {app[8]}).")
        return
    update_status(app_id, 'approved', feedback)
    await event.message.answer(f"✅ Заявка #{app_id} одобрена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
    except:
        pass

@dp.message_created(Command(commands=['reject']))
async def cmd_reject(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await event.message.answer("⛔ Нет прав.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await event.message.answer("Использование: /reject <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await event.message.answer("ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await event.message.answer(f"Заявка #{app_id} не найдена.")
        return
    if app[8] != 'pending':
        await event.message.answer(f"Заявка уже обработана (статус: {app[8]}).")
        return
    update_status(app_id, 'rejected', feedback)
    await event.message.answer(f"❌ Заявка #{app_id} отклонена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
    except:
        pass

@dp.message_created(Command(commands=['stats']))
async def cmd_stats(event):
    user_id = get_user_id(event)
    if user_id is None:
        await event.message.answer("Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await event.message.answer("⛔ Нет прав.")
        return
    total, pending, approved, rejected = get_stats()
    await event.message.answer(
        f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
    )

# =========================================================
# 12. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
