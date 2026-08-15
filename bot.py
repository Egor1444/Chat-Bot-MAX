import os
import time
import logging
import sqlite3
import requests
from datetime import datetime

# ===== ТОКЕН =====
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Токен не найден! Установите BOT_TOKEN или MAX_BOT_TOKEN")

# ===== ID АДМИНИСТРАТОРА =====
ADMIN_IDS = [123456789]  # ⚠️ Замените на свой ID

# ===== БАЗОВЫЙ URL API MAX =====
API_BASE = "https://platform-api2.max.ru"

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

# ===== ОТПРАВКА СООБЩЕНИЙ (НОВОЕ API) =====
def send_message(chat_id, text):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'chatId': str(chat_id),
        'text': text
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Ошибка отправки: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"Исключение при отправке: {e}")
        return None

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ (LONG POLLING) =====
def get_updates(offset=None):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': f'Bearer {TOKEN}'
    }
    params = {}
    if offset:
        params['offset'] = offset
    # Добавляем timeout для long polling (максимум 30 секунд)
    params['timeout'] = 30
    params['limit'] = 10
    try:
        response = requests.get(url, headers=headers, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            # Ожидаем, что API вернёт список сообщений
            return data.get('messages', [])
        else:
            logging.error(f"Ошибка получения обновлений: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        logging.error(f"Исключение при получении: {e}")
        return []

# ===== УВЕДОМЛЕНИЕ АДМИНОВ =====
def notify_admins(app_id, data, user_id):
    text = (
        f"📢 Новая заявка #{app_id}\n"
        f"От пользователя: {data.get('full_name', 'не указано')}\n"
        f"Суть: {data.get('action_desc', 'не указано')}\n"
        f"Польза: {data.get('benefit', 'не указано')}\n"
        f"Как пришёл: {data.get('how_came', 'не указано')}\n"
        f"Место/время: {data.get('place_time', 'не указано')}"
    )
    for admin_id in ADMIN_IDS:
        send_message(admin_id, text)

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
def handle_message(message):
    # В новом API сообщения могут иметь другую структуру
    # Предполагаем, что message содержит поля: id, from, chat, text, date
    user_id = str(message.get('from', {}).get('id', ''))
    chat_id = message.get('chat', {}).get('id', '')
    text = message.get('text', '')

    if not text:
        return

    if text.startswith('/'):
        command = text.split()[0].lower()
        if command == '/start':
            send_message(chat_id,
                "👋 Привет! Я бот для подачи новостей.\n"
                "Чтобы начать, отправьте /news\n\n"
                "Администратор:\n"
                "/pending — список заявок\n"
                "/approve <id> [комментарий]\n"
                "/reject <id> [комментарий]\n"
                "/stats — статистика"
            )
            return
        elif command == '/id':
            send_message(chat_id, f"Ваш ID: {user_id}")
            return
        elif command == '/cancel':
            if user_id in user_states:
                clear_user_state(user_id)
                send_message(chat_id, "✅ Заявка отменена.")
            else:
                send_message(chat_id, "Нет активной заявки.")
            return
        elif command == '/news':
            if user_id in user_states:
                send_message(chat_id, "У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            send_message(chat_id, QUESTIONS[0][1])
            return
        elif command == '/pending':
            if int(user_id) not in ADMIN_IDS:
                send_message(chat_id, "⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                send_message(chat_id, "Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, {row[2]}, {row[-1]}\n"
            send_message(chat_id, msg)
            return
        elif command == '/approve':
            if int(user_id) not in ADMIN_IDS:
                send_message(chat_id, "⛔ Нет прав.")
                return
            args = text.split(maxsplit=2)
            if len(args) < 2:
                send_message(chat_id, "Использование: /approve <id> [комментарий]")
                return
            try:
                app_id = int(args[1])
            except ValueError:
                send_message(chat_id, "ID должен быть числом.")
                return
            feedback = args[2] if len(args) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message(chat_id, f"Заявка #{app_id} не найдена.")
                return
            if app[9] != 'pending':
                send_message(chat_id, f"Заявка уже обработана (статус: {app[9]}).")
                return
            update_status(app_id, 'approved', feedback)
            send_message(chat_id, f"✅ Заявка #{app_id} одобрена.")
            try:
                send_message(int(app[1]), f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
            except:
                pass
            return
        elif command == '/reject':
            if int(user_id) not in ADMIN_IDS:
                send_message(chat_id, "⛔ Нет прав.")
                return
            args = text.split(maxsplit=2)
            if len(args) < 2:
                send_message(chat_id, "Использование: /reject <id> [комментарий]")
                return
            try:
                app_id = int(args[1])
            except ValueError:
                send_message(chat_id, "ID должен быть числом.")
                return
            feedback = args[2] if len(args) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message(chat_id, f"Заявка #{app_id} не найдена.")
                return
            if app[9] != 'pending':
                send_message(chat_id, f"Заявка уже обработана (статус: {app[9]}).")
                return
            update_status(app_id, 'rejected', feedback)
            send_message(chat_id, f"❌ Заявка #{app_id} отклонена.")
            try:
                send_message(int(app[1]), f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
            except:
                pass
            return
        elif command == '/stats':
            if int(user_id) not in ADMIN_IDS:
                send_message(chat_id, "⛔ Нет прав.")
                return
            total, pending, approved, rejected = get_stats()
            send_message(
                chat_id,
                f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            )
            return
        else:
            send_message(chat_id, "Неизвестная команда. Используйте /start для справки.")
            return

    state = get_user_state(user_id)
    if state is None:
        return

    step = state['step']
    data = state['data']

    if step == -1:
        if text.lower() == "да":
            app_id = save_application(user_id, data)
            clear_user_state(user_id)
            send_message(chat_id, "✅ Заявка успешно отправлена на модерацию!")
            notify_admins(app_id, data, user_id)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            send_message(chat_id, "❌ Заявка отменена.")
        else:
            send_message(chat_id, 'Пожалуйста, ответьте "Да" или "Нет".')
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            send_message(chat_id, QUESTIONS[next_step][1])
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
            send_message(chat_id, summary)

# ===== ОСНОВНОЙ ЦИКЛ =====
def main():
    logging.info("🚀 Бот запущен...")
    last_update_id = 0

    while True:
        try:
            updates = get_updates(offset=last_update_id + 1)
            for update in updates:
                # В новом API каждое обновление может иметь поле 'message'
                msg = update.get('message')
                if msg:
                    # Обновляем last_update_id – в новом API у каждого сообщения есть свой id
                    last_update_id = update.get('update_id', 0)
                    handle_message(msg)
        except Exception as e:
            logging.error(f"Ошибка в цикле: {e}")
        time.sleep(1)

if __name__ == "__main__":
    main()
