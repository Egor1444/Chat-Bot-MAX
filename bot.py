import os
import sys
import subprocess
import importlib
import asyncio
import logging
import sqlite3
from datetime import datetime

# ===== АВТОУСТАНОВКА maxapi =====
def install_package(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", package])

def ensure_maxapi():
    try:
        importlib.import_module('maxapi')
        return True
    except ImportError:
        print("maxapi не найдена. Устанавливаем...")
        try:
            install_package('attrs')
            install_package('aiohttp')
            install_package('maxapi')
            importlib.import_module('maxapi')
            print("maxapi успешно установлена.")
            return True
        except Exception as e:
            print(f"Ошибка установки: {e}")
            return False

if not ensure_maxapi():
    print("❌ Не удалось установить maxapi. Установите вручную: python3 -m pip install --user maxapi")
    sys.exit(1)

# ===== ИМПОРТЫ ИЗ maxapi =====
try:
    from maxapi import Bot, Dispatcher, Message
except ImportError:
    from maxapi import Bot, Dispatcher
    Message = None

# ===== ТОКЕН =====
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Токен не найден! Установите BOT_TOKEN или MAX_BOT_TOKEN")

# ===== ID АДМИНИСТРАТОРА =====
ADMIN_IDS = [123456789]  # ⚠️ Замените на свой ID

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO)

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ===== ХРАНИЛИЩЕ СОСТОЯНИЙ =====
user_states = {}

# ===== БАЗА ДАННЫХ =====
DB_PATH = "news.db"

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

# ===== ФУНКЦИИ БАЗЫ =====
def save_application(user_id, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO news 
        (user_id, full_name, action_desc, benefit, how_came, place_time, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
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
    c.execute('SELECT COUNT(*) FROM news')
    total = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM news WHERE status = "pending"')
    pending = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM news WHERE status = "approved"')
    approved = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM news WHERE status = "rejected"')
    rejected = c.fetchone()[0]
    conn.close()
    return total, pending, approved, rejected

# ===== ОБРАБОТЧИКИ =====
@dp.message_handler(commands=['start'])
async def cmd_start(event: Message):
    await event.answer(
        "👋 Привет! Я бот для подачи новостей.\n"
        "Чтобы начать, отправьте /news\n\n"
        "Администратор:\n"
        "/pending — список заявок\n"
        "/approve <id> [комментарий]\n"
        "/reject <id> [комментарий]\n"
        "/stats — статистика"
    )

@dp.message_handler(commands=['id'])
async def cmd_id(event: Message):
    await event.answer(f"Ваш ID: {event.from_.id}")

@dp.message_handler(commands=['cancel'])
async def cmd_cancel(event: Message):
    user_id = str(event.from_.id)
    if user_id in user_states:
        del user_states[user_id]
        await event.answer("✅ Заявка отменена.")
    else:
        await event.answer("Нет активной заявки.")

# ===== ОПРОС =====
QUESTIONS = [
    ('full_name', 'Вопрос 1 из 5. Ваше полное имя (ФИО)?'),
    ('action_desc', 'Вопрос 2 из 5. Опишите суть события или действия.'),
    ('benefit', 'Вопрос 3 из 5. Какую пользу принесёт публикация?'),
    ('how_came', 'Вопрос 4 из 5. Как вы пришли к этому событию?'),
    ('place_time', 'Вопрос 5 из 5. Где и когда произошло событие?')
]
TOTAL_QUESTIONS = len(QUESTIONS)

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}

def clear_user_state(user_id):
    user_states.pop(str(user_id), None)

@dp.message_handler(commands=['news'])
async def cmd_news(event: Message):
    user_id = str(event.from_.id)
    if user_id in user_states:
        await event.answer("У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
        return
    set_user_state(user_id, 0)
    await event.answer(QUESTIONS[0][1])

@dp.message_handler(content_types=['text'])
async def handle_message(event: Message):
    user_id = str(event.from_.id)
    state = get_user_state(user_id)
    if state is None:
        return

    if not event.text:
        await event.answer("Пожалуйста, отправьте текст.")
        return

    text = event.text.strip()
    step = state['step']
    data = state['data']

    if step == -1:
        if text.lower() == "да":
            app_id = save_application(user_id, data)
            clear_user_state(user_id)
            await event.answer("✅ Заявка успешно отправлена на модерацию!")
            await notify_admins(app_id, data, user_id)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            await event.answer("❌ Заявка отменена.")
        else:
            await event.answer('Пожалуйста, ответьте "Да" или "Нет".')
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            await event.answer(QUESTIONS[next_step][1])
        else:
            set_user_state(user_id, -1, data)
            summary = (
                "📋 Проверьте введённые данные:\n\n"
                f"1. ФИО: {data.get('full_name', '—')}\n"
                f"2. Суть: {data.get('action_desc', '—')}\n"
                f"3. Польза: {data.get('benefit', '—')}\n"
                f"4. Как пришли: {data.get('how_came', '—')}\n"
                f"5. Место/время: {data.get('place_time', '—')}\n"
                "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
            )
            await event.answer(summary)

async def notify_admins(app_id, data, user_id):
    text = (
        f"📢 Новая заявка #{app_id}\n"
        f"От пользователя: {data.get('full_name', 'не указано')}\n"
        f"Суть: {data.get('action_desc', 'не указано')}\n"
        f"Польза: {data.get('benefit', 'не указано')}\n"
        f"Как пришёл: {data.get('how_came', 'не указано')}\n"
        f"Место/время: {data.get('place_time', 'не указано')}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logging.error(f"Не удалось уведомить админа {admin_id}: {e}")

# ===== АДМИН-КОМАНДЫ =====
@dp.message_handler(commands=['pending'])
async def cmd_pending(event: Message):
    if event.from_.id not in ADMIN_IDS:
        await event.answer("⛔ Нет прав.")
        return
    rows = get_pending_applications()
    if not rows:
        await event.answer("Нет заявок.")
        return
    text = "📋 Ожидающие заявки:\n\n"
    for row in rows:
        text += f"ID: {row[0]}, {row[2]}, {row[-1]}\n"
    await event.answer(text)

@dp.message_handler(commands=['approve'])
async def cmd_approve(event: Message):
    if event.from_.id not in ADMIN_IDS:
        await event.answer("⛔ Нет прав.")
        return
    args = event.text.split(maxsplit=2)
    if len(args) < 2:
        await event.answer("Использование: /approve <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await event.answer("ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await event.answer(f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await event.answer(f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'approved', feedback)
    await event.answer(f"✅ Заявка #{app_id} одобрена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
    except:
        pass

@dp.message_handler(commands=['reject'])
async def cmd_reject(event: Message):
    if event.from_.id not in ADMIN_IDS:
        await event.answer("⛔ Нет прав.")
        return
    args = event.text.split(maxsplit=2)
    if len(args) < 2:
        await event.answer("Использование: /reject <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await event.answer("ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await event.answer(f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await event.answer(f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'rejected', feedback)
    await event.answer(f"❌ Заявка #{app_id} отклонена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
    except:
        pass

@dp.message_handler(commands=['stats'])
async def cmd_stats(event: Message):
    if event.from_.id not in ADMIN_IDS:
        await event.answer("⛔ Нет прав.")
        return
    total, pending, approved, rejected = get_stats()
    await event.answer(
        f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
    )

# ===== ЗАПУСК =====
async def main():
    logging.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
