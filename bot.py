import os
import sys
import asyncio
import logging
import sqlite3
import json
from datetime import datetime
import time

# ===== ПРОВЕРКА УСТАНОВКИ maxapi =====
try:
    from maxapi import Bot
except ImportError:
    print("maxapi не найдена. Устанавливаем...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "maxapi"])
    from maxapi import Bot

# ===== ТОКЕН =====
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Токен не найден! Установите BOT_TOKEN или MAX_BOT_TOKEN")

# ===== ID АДМИНИСТРАТОРА =====
ADMIN_IDS = [123456789]  # ⚠️ Замените на свой ID

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO)

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

# ===== ХРАНИЛИЩЕ СОСТОЯНИЙ =====
user_states = {}

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}

def clear_user_state(user_id):
    user_states.pop(str(user_id), None)

# ===== ВОПРОСЫ =====
QUESTIONS = [
    ('full_name', 'Вопрос 1 из 5. Ваше полное имя (ФИО)?'),
    ('action_desc', 'Вопрос 2 из 5. Опишите суть события или действия.'),
    ('benefit', 'Вопрос 3 из 5. Какую пользу принесёт публикация?'),
    ('how_came', 'Вопрос 4 из 5. Как вы пришли к этому событию?'),
    ('place_time', 'Вопрос 5 из 5. Где и когда произошло событие?')
]
TOTAL_QUESTIONS = len(QUESTIONS)

# ===== УВЕДОМЛЕНИЕ АДМИНОВ =====
async def notify_admins(bot, app_id, data, user_id):
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

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
async def handle_message(bot, message):
    user_id = str(message.get('from', {}).get('id', ''))
    chat_id = message.get('chat', {}).get('id', '')
    text = message.get('text', '')

    if not text:
        return

    # === ОБРАБОТКА КОМАНД ===
    if text.startswith('/'):
        command = text.split()[0].lower()
        if command == '/start':
            await bot.send_message(
                chat_id=chat_id,
                text="👋 Привет! Я бот для подачи новостей.\n"
                     "Чтобы начать, отправьте /news\n\n"
                     "Администратор:\n"
                     "/pending — список заявок\n"
                     "/approve <id> [комментарий]\n"
                     "/reject <id> [комментарий]\n"
                     "/stats — статистика"
            )
            return
        elif command == '/id':
            await bot.send_message(chat_id=chat_id, text=f"Ваш ID: {user_id}")
            return
        elif command == '/cancel':
            if user_id in user_states:
                clear_user_state(user_id)
                await bot.send_message(chat_id=chat_id, text="✅ Заявка отменена.")
            else:
                await bot.send_message(chat_id=chat_id, text="Нет активной заявки.")
            return
        elif command == '/news':
            if user_id in user_states:
                await bot.send_message(chat_id=chat_id, text="У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            await bot.send_message(chat_id=chat_id, text=QUESTIONS[0][1])
            return
        elif command == '/pending':
            if int(user_id) not in ADMIN_IDS:
                await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                await bot.send_message(chat_id=chat_id, text="Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, {row[2]}, {row[-1]}\n"
            await bot.send_message(chat_id=chat_id, text=msg)
            return
        elif command == '/approve':
            if int(user_id) not in ADMIN_IDS:
                await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
                return
            args = text.split(maxsplit=2)
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
                await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
            except:
                pass
            return
        elif command == '/reject':
            if int(user_id) not in ADMIN_IDS:
                await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
                return
            args = text.split(maxsplit=2)
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
                await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
            except:
                pass
            return
        elif command == '/stats':
            if int(user_id) not in ADMIN_IDS:
                await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
                return
            total, pending, approved, rejected = get_stats()
            await bot.send_message(
                chat_id=chat_id,
                text=f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            )
            return
        else:
            await bot.send_message(chat_id=chat_id, text="Неизвестная команда. Используйте /start для справки.")
            return

    # === ЕСЛИ НЕ КОМАНДА — ОБРАБОТКА СОСТОЯНИЙ ===
    state = get_user_state(user_id)
    if state is None:
        return

    step = state['step']
    data = state['data']

    if step == -1:
        if text.lower() == "да":
            app_id = save_application(user_id, data)
            clear_user_state(user_id)
            await bot.send_message(chat_id=chat_id, text="✅ Заявка успешно отправлена на модерацию!")
            await notify_admins(bot, app_id, data, user_id)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            await bot.send_message(chat_id=chat_id, text="❌ Заявка отменена.")
        else:
            await bot.send_message(chat_id=chat_id, text='Пожалуйста, ответьте "Да" или "Нет".')
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            await bot.send_message(chat_id=chat_id, text=QUESTIONS[next_step][1])
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
            await bot.send_message(chat_id=chat_id, text=summary)

# ===== ОСНОВНОЙ ЦИКЛ (LONG POLLING) =====
async def main():
    bot = Bot(token=TOKEN)
    last_update_id = 0

    logging.info("🚀 Бот запущен...")

    while True:
        try:
            # Получаем обновления
            updates = await bot.get_updates(offset=last_update_id + 1, timeout=30)
            for update in updates:
                last_update_id = update.get('update_id', 0)
                if 'message' in update:
                    await handle_message(bot, update['message'])
        except Exception as e:
            logging.error(f"Ошибка в цикле: {e}")
            await asyncio.sleep(5)  # пауза при ошибке

if __name__ == "__main__":
    asyncio.run(main())
