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
    # Если переменные окружения не заданы, используем токен напрямую (только для теста!)
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logging.warning("⚠️ Токен взят из кода (небезопасно). Для продакшена используйте переменные окружения.")

logging.basicConfig(level=logging.INFO)
logging.info(f"🔑 Токен (первые 4): {TOKEN[:4]}..., длина {len(TOKEN)}")

# ===== БАЗОВЫЙ URL =====
API_BASE = "https://platform-api2.max.ru"

# ===== ID АДМИНИСТРАТОРА (замените на свой) =====
ADMIN_IDS = [364551480]  # Ваш user_id из логов

# ===== АВТОРИЗАЦИЯ =====
def check_auth():
    url = f"{API_BASE}/me"
    headers = {'Authorization': TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            logging.info("✅ Авторизация успешна!")
            return True
        else:
            logging.error(f"❌ Ошибка авторизации: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Ошибка подключения: {e}")
        return False

if not check_auth():
    raise RuntimeError("Не удалось авторизоваться. Проверьте токен и URL.")

# ===== ОПРЕДЕЛЕНИЕ РАБОЧЕГО chat_id =====
# Из логов мы знаем два возможных ID: recipient.chat_id = 2712418 и sender.user_id = 364551480
POSSIBLE_IDS = [2712418, 364551480]
WORKING_CHAT_ID = None
WORKING_FIELD = None

def test_send(chat_id, field):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': TOKEN,
        'Content-Type': 'application/json'
    }
    if field == "chatId":
        payload = {"chatId": str(chat_id), "text": "Тестовое сообщение для проверки"}
    elif field == "chat_id":
        payload = {"chat_id": str(chat_id), "text": "Тестовое сообщение для проверки"}
    elif field == "recipient":
        payload = {"recipient": {"chat_id": str(chat_id)}, "text": "Тестовое сообщение для проверки"}
    elif field == "user_id":
        payload = {"user_id": str(chat_id), "text": "Тестовое сообщение для проверки"}
    else:
        return False
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            logging.info(f"✅ РАБОЧАЯ КОМБИНАЦИЯ: chat_id={chat_id}, field={field}")
            return True
        else:
            logging.debug(f"❌ {field} с chat_id={chat_id} вернул {resp.status_code}: {resp.text[:80]}")
            return False
    except Exception as e:
        logging.debug(f"⚠️ Ошибка при {field} с chat_id={chat_id}: {e}")
        return False

# Перебираем все варианты
logging.info("🔎 Поиск рабочего способа отправки сообщений...")
for chat_id in POSSIBLE_IDS:
    for field in ["chatId", "chat_id", "recipient", "user_id"]:
        if test_send(chat_id, field):
            WORKING_CHAT_ID = chat_id
            WORKING_FIELD = field
            break
    if WORKING_CHAT_ID is not None:
        break

if WORKING_CHAT_ID is None:
    raise RuntimeError("❌ Не удалось найти рабочий способ отправки. Проверьте токен и права бота.")

logging.info(f"🎯 Будет использоваться: chat_id={WORKING_CHAT_ID}, field={WORKING_FIELD}")

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

# ===== ОТПРАВКА СООБЩЕНИЙ (с использованием найденных параметров) =====
def send_message(recipient_id, text):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': TOKEN,
        'Content-Type': 'application/json'
    }
    # Используем найденный рабочий вариант
    if WORKING_FIELD == "chatId":
        payload = {"chatId": str(recipient_id), "text": text}
    elif WORKING_FIELD == "chat_id":
        payload = {"chat_id": str(recipient_id), "text": text}
    elif WORKING_FIELD == "recipient":
        payload = {"recipient": {"chat_id": str(recipient_id)}, "text": text}
    elif WORKING_FIELD == "user_id":
        payload = {"user_id": str(recipient_id), "text": text}
    else:
        logging.error("❌ Неизвестное поле для отправки")
        return False

    logging.info(f"📤 Отправка в чат {recipient_id} (поле {WORKING_FIELD}): {text[:30]}...")
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            logging.info("✅ Сообщение успешно отправлено")
            return True
        else:
            logging.error(f"❌ Ошибка отправки: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Исключение: {e}")
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

    # Обработка команд
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
            # Уведомляем пользователя
            try:
                send_message(str(app[1]), f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
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
                send_message(str(app[1]), f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
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

    # Обработка состояний опроса
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
            notify_admins(app_id, data)
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
