import os
import logging
import sqlite3
from datetime import datetime
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart, Command
from maxapi.types import Message
from maxapi.fsm import State, StatesGroup, MemoryStorage, StateContext

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
# 5. МАШИНА СОСТОЯНИЙ (FSM)
# =========================================================
class NewsStates(StatesGroup):
    waiting_full_name = State()
    waiting_action = State()
    waiting_benefit = State()
    waiting_how_came = State()
    waiting_place_time = State()
    waiting_confirmation = State()

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
# 7. ИНИЦИАЛИЗАЦИЯ БОТА
# =========================================================
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# =========================================================
# 8. ОБРАБОТЧИКИ КОМАНД
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event: Message, state: StateContext):
    await state.clear()
    await event.message.answer(
        "👋 Привет! Я бот для подачи новостей.\n"
        "Чтобы начать, отправьте /news\n"
        "Для справки используйте /help"
    )

@dp.message_created(Command(commands=['help']))
async def cmd_help(event: Message):
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
async def cmd_id(event: Message):
    user_id = event.from_.id
    await event.message.answer(f"Ваш ID: {user_id}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event: Message, state: StateContext):
    current_state = await state.get_state()
    if current_state is None:
        await event.message.answer("Нет активной заявки для отмены.")
        return
    await state.clear()
    await event.message.answer("✅ Заявка отменена.")

# =========================================================
# 9. ОПРОС (/news)
# =========================================================
@dp.message_created(Command(commands=['news']))
async def cmd_news(event: Message, state: StateContext):
    user_id = event.from_.id
    current_state = await state.get_state()
    if current_state is not None:
        await event.message.answer("У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
        return
    await state.set_state(NewsStates.waiting_full_name)
    await event.message.answer(QUESTIONS[0][1])

@dp.message_created(NewsStates.waiting_full_name, F.message.body.text)
async def process_full_name(event: Message, state: StateContext):
    await state.update_data(full_name=event.message.body.text)
    await state.set_state(NewsStates.waiting_action)
    await event.message.answer(QUESTIONS[1][1])

@dp.message_created(NewsStates.waiting_action, F.message.body.text)
async def process_action(event: Message, state: StateContext):
    await state.update_data(action_desc=event.message.body.text)
    await state.set_state(NewsStates.waiting_benefit)
    await event.message.answer(QUESTIONS[2][1])

@dp.message_created(NewsStates.waiting_benefit, F.message.body.text)
async def process_benefit(event: Message, state: StateContext):
    await state.update_data(benefit=event.message.body.text)
    await state.set_state(NewsStates.waiting_how_came)
    await event.message.answer(QUESTIONS[3][1])

@dp.message_created(NewsStates.waiting_how_came, F.message.body.text)
async def process_how_came(event: Message, state: StateContext):
    await state.update_data(how_came=event.message.body.text)
    await state.set_state(NewsStates.waiting_place_time)
    await event.message.answer(QUESTIONS[4][1])

@dp.message_created(NewsStates.waiting_place_time, F.message.body.text)
async def process_place_time(event: Message, state: StateContext):
    await state.update_data(place_time=event.message.body.text)
    data = await state.get_data()
    summary = (
        "📋 Проверьте введённые данные:\n\n"
        f"1. ФИО: {data.get('full_name', '—')}\n"
        f"2. Суть: {data.get('action_desc', '—')}\n"
        f"3. Польза: {data.get('benefit', '—')}\n"
        f"4. Как пришли: {data.get('how_came', '—')}\n"
        f"5. Место/время: {data.get('place_time', '—')}\n"
        "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
    )
    await state.set_state(NewsStates.waiting_confirmation)
    await event.message.answer(summary)

@dp.message_created(NewsStates.waiting_confirmation)
async def process_confirmation(event: Message, state: StateContext):
    text = event.message.body.text.strip().lower()
    if text == "да":
        data = await state.get_data()
        app_id = save_application(event.from_.id, data)
        await state.clear()
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
    elif text == "нет":
        await state.clear()
        await event.message.answer("❌ Заявка отменена.")
    else:
        await event.message.answer('Пожалуйста, ответьте "Да" или "Нет".')

# =========================================================
# 10. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['pending']))
async def cmd_pending(event: Message):
    if event.from_.id not in ADMIN_IDS:
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
async def cmd_approve(event: Message):
    if event.from_.id not in ADMIN_IDS:
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
    # Уведомить автора
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
    except:
        pass

@dp.message_created(Command(commands=['reject']))
async def cmd_reject(event: Message):
    if event.from_.id not in ADMIN_IDS:
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
async def cmd_stats(event: Message):
    if event.from_.id not in ADMIN_IDS:
        await event.message.answer("⛔ Нет прав.")
        return
    total, pending, approved, rejected = get_stats()
    await event.message.answer(
        f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
    )

# =========================================================
# 11. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
