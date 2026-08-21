import os
import time
import logging
import sqlite3
import requests
import urllib3

# Отключаем предупреждения об отсутствии SSL-проверки
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ТОКЕН: ИСКЛЮЧИТЕЛЬНО ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    logging.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения BOT_TOKEN не задана на хостинге!")
    raise RuntimeError("Задайте BOT_TOKEN в настройках окружения хостинга.")

logging.info(f"🔑 Токен инициализирован (длина: {len(TOKEN)})")

API_BASE = "https://max.ru"
ADMIN_IDS = [364551480]  # Ваш user_id
DB_PATH = "news.db"

# ИНДЕКСЫ СТОЛБЦОВ ТАБЛИЦЫ БД
IDX_USER_ID = 1
IDX_STATUS = 8
IDX_FEEDBACK = 9

def check_auth():
    url = f"{API_BASE}/me"
    headers = {'Authorization': TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            logging.info("✅ Авторизация на platform-api2 успешна!")
            return True
        logging.error(f"❌ Ошибка авторизации: {resp.status_code} - {resp.text}")
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка подключения при авторизации: {e}")
        return False

if not check_auth():
    raise RuntimeError("❌ Не удалось авторизоваться в системе MAX API.")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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

init_db()

def save_application(user_id, data):
    with sqlite3.connect(DB_PATH) as conn:
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
        return c.lastrowid

def get_application_by_id(app_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM news WHERE id = ?', (app_id,))
        return c.fetchone()

def update_status(app_id, status, feedback=''):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('UPDATE news SET status = ?, feedback = ? WHERE id = ?', (status, feedback, app_id))
        conn.commit()

def get_pending_applications():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM news WHERE status = "pending" ORDER BY created_at ASC')
        return c.fetchall()

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        total = c.execute('SELECT COUNT(*) FROM news').fetchone()[0]
        pending = c.execute('SELECT COUNT(*) FROM news WHERE status = "pending"').fetchone()[0]
        approved = c.execute('SELECT COUNT(*) FROM news WHERE status = "approved"').fetchone()[0]
        rejected = c.execute('SELECT COUNT(*) FROM news WHERE status = "rejected"').fetchone()[0]
        return total, pending, approved, rejected

user_states = {}

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}

def clear_user_state(user_id):
    user_states.pop(str(user_id), None)

QUESTIONS = [
    ('full_name', 'Вопрос 1 из 5. Ваше полное имя (ФИО)?'),
    ('action_desc', 'Вопрос 2 из 5. Опишите суть события или действия.'),
    ('benefit', 'Вопрос 3 из 5. Какую пользу принесёт публикация?'),
    ('how_came', 'Вопрос 4 из 5. Как вы пришли к этому событию?'),
    ('place_time', 'Вопрос 5 из 5. Где и когда произошло событие?')
]
TOTAL_QUESTIONS = len(QUESTIONS)

# ===== МЕТОД ОТПРАВКИ СООБЩЕНИЙ =====
def send_message(recipient_id, text):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        'chat_id': str(recipient_id),
        'text': text
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if resp.status_code in:  # Исправлено синтаксическое условие
            logging.info(f"✅ Успешно доставлено в чат {recipient_id}")
            return True
        else:
            logging.error(f"❌ Ошибка доставки на {recipient_id}: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Исключение при вызове POST /messages: {e}")
        return False

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ =====
def get_updates(offset=None):
    url = f"{API_BASE}/updates"
    headers = {'Authorization': TOKEN}
    params = {'limit': 10, 'timeout': 30}
    if offset:
        params['offset'] = offset
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
        if resp.status_code == 200:
            return resp.json().get('updates', [])
        logging.error(f"❌ Ошибка получения обновлений: {resp.status_code} - {resp.text}")
        return []
    except Exception as e:
        logging.error(f"❌ Исключение при Long Polling: {e}")
        return []

def notify_admins(app_id, data):
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

def handle_message(update):
    message = update.get('message', {})
    if not message:
        return

    recipient = message.get('recipient', {})
    chat_id = str(recipient.get('chat_id', ''))
    sender = message.get('sender', {})
    user_id = str(sender.get('user_id', ''))

    if not chat_id or not user_id:
        return

    body = message.get('body', {})
    text = body.get('text', '').strip()

    if not text:
        return

    logging.info(f"📩 Обрабатываем сообщение от {user_id} в чате {chat_id}")

    # Обработка команд
    if text.startswith('/'):
        command_parts = text.split(maxsplit=2)
        command = command_parts[0].lower()
        is_admin = int(user_id) in ADMIN_IDS

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
            if get_user_state(user_id) is not None:
                clear_user_state(user_id)
                send_message(chat_id, "✅ Заявка отменена.")
            else:
                send_message(chat_id, "У вас нет активной заявки.")
            return
        elif command == '/news':
            if get_user_state(user_id) is not None:
                send_message(chat_id, "У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            send_message(chat_id, QUESTIONS[0][1])  # Исправлено
            return
        elif command == '/pending':
            if not is_admin:
                send_message(chat_id, "⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                send_message(chat_id, "Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, Имя: {row[2]}, Создано: {row[-1]}\n"
            send_message(chat_id, msg)
            return
        elif command in ['/approve', '/reject']:
            if not is_admin:
                send_message(chat_id, "⛔ Нет прав.")
                return
            if len(command_parts) < 2:
                send_message(chat_id, f"Использование: {command} <id> [комментарий]")
                return
            try:
                app_id = int(command_parts[1])
            except ValueError:
                send_message(chat_id, "ID должен быть числом.")
                return
            
            feedback = command_parts[2] if len(command_parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message(chat_id, f"Заявка #{app_id} не найдена.")
                return
            
            if app[IDX_STATUS] != 'pending':
                send_message(chat_id, f"Заявка уже обработана (статус: {app[IDX_STATUS]}).")
                return
            
            new_status = 'approved' if command == '/approve' else 'rejected'
            update_status(app_id, new_status, feedback)
