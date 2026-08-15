import os
import time
import logging
import sqlite3
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== ТОКЕН =====
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logging.warning("⚠️ Токен взят из кода (для теста)")

logging.info(f"🔑 Токен (первые 4): {TOKEN[:4]}..., длина {len(TOKEN)}")

# ===== БАЗОВЫЕ URL =====
API_BASE_NEW = "https://platform-api2.max.ru"
API_BASE_OLD = "https://api.max.ru"

# ===== ID АДМИНИСТРАТОРА =====
ADMIN_IDS = [364551480]  # Ваш user_id

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO)

# ===== ПРОВЕРКА АВТОРИЗАЦИИ =====
def check_auth():
    for base in [API_BASE_NEW, API_BASE_OLD]:
        url = f"{base}/me"
        headers = {'Authorization': TOKEN}
        try:
            resp = requests.get(url, headers=headers, timeout=5, verify=False)
            if resp.status_code == 200:
                logging.info(f"✅ Авторизация успешна на {base}")
                return base
            else:
                logging.warning(f"❌ {base}/me вернул {resp.status_code}")
        except Exception as e:
            logging.warning(f"Ошибка на {base}: {e}")
    return None

ACTIVE_BASE = check_auth()
if not ACTIVE_BASE:
    raise RuntimeError("Не удалось авторизоваться. Проверьте токен.")
logging.info(f"Используется базовый URL: {ACTIVE_BASE}")

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

# ===== УНИВЕРСАЛЬНАЯ ОТПРАВКА С ПЕРЕБОРОМ ВАРИАНТОВ =====
def send_message(recipient_id, text):
    """
    Пытается отправить сообщение, перебирая все мыслимые комбинации.
    Возвращает True, если хотя бы одна попытка успешна.
    """
    recipient_str = str(recipient_id)
    recipient_int = int(recipient_id) if str(recipient_id).isdigit() else None

    # Список базовых URL (проверяем оба домена)
    bases = [ACTIVE_BASE, API_BASE_NEW, API_BASE_OLD]

    # Список эндпоинтов
    endpoints = [
        '/messages',
        '/sendMessage',
        '/message',
        '/send',
        '/bot' + TOKEN + '/sendMessage',  # как в Telegram
    ]

    # Список методов
    methods = ['POST', 'GET']

    # Список полей для chat_id
    chat_id_fields = [
        ('chatId', recipient_str),
        ('chatId', recipient_int),
        ('chat_id', recipient_str),
        ('chat_id', recipient_int),
        ('recipient.chat_id', recipient_str),
        ('recipient.chat_id', recipient_int),
        ('recipient', recipient_str),
        ('recipient', recipient_int),
        ('peer_id', recipient_str),
        ('peer_id', recipient_int),
        ('user_id', recipient_str),
        ('user_id', recipient_int),
    ]

    # Список форматов отправки
    content_types = [
        'application/json',
        'application/x-www-form-urlencoded',
        'multipart/form-data',
    ]

    # Список типов данных
    data_types = ['json', 'data', 'params']

    attempt = 0
    for base in bases:
        for endpoint in endpoints:
            url = base + endpoint
            for method in methods:
                for field_name, field_value in chat_id_fields:
                    for ct in content_types:
                        for dt in data_types:
                            attempt += 1
                            headers = {'Authorization': TOKEN}
                            if ct != 'multipart/form-data':
                                headers['Content-Type'] = ct
                            # Формируем payload
                            if field_name == 'recipient':
                                payload = {'recipient': {'chat_id': field_value}, 'text': text}
                            elif field_name == 'recipient.chat_id':
                                payload = {'recipient': {'chat_id': field_value}, 'text': text}
                            else:
                                payload = {field_name: field_value, 'text': text}
                            
                            try:
                                if method == 'GET':
                                    # Для GET параметры передаются в строке запроса
                                    if dt == 'params':
                                        resp = requests.get(url, params=payload, headers=headers, timeout=10, verify=False)
                                    else:
                                        continue
                                else:  # POST
                                    if dt == 'json':
                                        resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
                                    elif dt == 'data':
                                        if ct == 'application/json':
                                            resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
                                        else:
                                            resp = requests.post(url, data=payload, headers=headers, timeout=10, verify=False)
                                    else:
                                        continue
                                if resp.status_code == 200:
                                    logging.info(f"✅ Успешно! Попытка #{attempt}: {method} {url} {field_name}={field_value} ({dt})")
                                    return True
                                else:
                                    if attempt <= 5 or attempt % 5 == 0:
                                        logging.debug(f"❌ Попытка #{attempt}: {method} {url} {field_name}={field_value} -> {resp.status_code} {resp.text[:80]}")
                            except Exception as e:
                                if attempt <= 5:
                                    logging.debug(f"⚠️ Попытка #{attempt}: ошибка {e}")
                                continue
    logging.error("❌ Все способы отправки не удались. Проверьте токен и права бота.")
    return False

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ =====
def get_updates(offset=None):
    url = f"{API_BASE_NEW}/updates"
    headers = {'Authorization': TOKEN}
    params = {'limit': 10, 'timeout': 30}
    if offset:
        params['offset'] = offset
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=35, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('updates', [])
        else:
            logging.error(f"❌ Ошибка получения обновлений: {resp.status_code} - {resp.text}")
            return []
    except Exception as e:
        logging.error(f"❌ Исключение при получении: {e}")
        return []

# ===== УВЕДОМЛЕНИЕ АДМИНОВ =====
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

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
def handle_message(update):
    message = update.get('message', {})
    if not message:
        return

    recipient = message.get('recipient', {})
    chat_id = str(recipient.get('chat_id', ''))
    sender = message.get('sender', {})
    user_id = str(sender.get('user_id', ''))

    if not chat_id or not user_id:
        logging.warning("❌ Нет chat_id или user_id в сообщении")
        return

    body = message.get('body', {})
    text = body.get('text', '')

    if not text:
        return

    logging.info(f"📩 Получено сообщение от {user_id} в чат {chat_id}: {text[:50]}")

    # Пробуем отправить ответ (бот должен ответить на любое сообщение, чтобы убедиться в работоспособности)
    # Для теста отправляем приветствие на все команды
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
        # остальные команды пока пропускаем, чтобы сосредоточиться на отправке
        else:
            send_message(chat_id, "Получена команда: " + command)
            return

    # Для всех остальных сообщений тоже отвечаем
    send_message(chat_id, "Я получил ваше сообщение: " + text[:30])

# ===== ОСНОВНОЙ ЦИКЛ =====
def main():
    logging.info("🚀 Бот запущен...")
    last_marker = 0

    while True:
        try:
            updates = get_updates(offset=last_marker + 1)
            for update in updates:
                if update.get('update_type') != 'message_created':
                    continue
                handle_message(update)
                if 'marker' in update:
                    last_marker = update['marker']
                else:
                    last_marker += 1
        except Exception as e:
            logging.error(f"❌ Ошибка в цикле: {e}")
        time.sleep(1)

if __name__ == "__main__":
    main()
