import os
import time
import logging
import sqlite3
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================
# 1. КОНФИГУРАЦИЯ
# =========================================================
API_BASE = "https://platform-api2.max.ru"  # Правильный URL
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]   # Ваш user_id
DB_PATH = "news.db"

# =========================================================
# 2. ПРОВЕРКА ТОКЕНА
# =========================================================
def check_token():
    url = f"{API_BASE}/me"
    headers = {"Authorization": TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            logger.info("✅ Токен действителен")
            return True
        else:
            logger.error(f"❌ Ошибка проверки токена: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Исключение при проверке токена: {e}")
        return False

if not check_token():
    logger.critical("❌ Токен невалидный. Бот не будет работать.")
    exit(1)

# =========================================================
# 3. ОТПРАВКА СООБЩЕНИЙ (РАБОЧИЙ МЕТОД)
# =========================================================
def send_message(recipient_id: int, text: str, retries: int = 3) -> bool:
    """
    Отправляет сообщение через GET /messages?chat_id={recipient_id}&text={text}
    """
    url = f"{API_BASE}/messages"
    params = {
        "chat_id": recipient_id,
        "text": text
    }
    headers = {"Authorization": TOKEN}
    
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20, verify=False)
            logger.info(f"📤 GET /messages?chat_id={recipient_id} -> {resp.status_code}")
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                logger.warning(f"⚠️ 429, ждём {wait} сек...")
                time.sleep(wait)
                continue
            if resp.status_code == 200:
                logger.info(f"✅ Сообщение отправлено пользователю {recipient_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки на {recipient_id}: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {e}")
            time.sleep(1)
    return False

# =========================================================
# 4. БАЗА ДАННЫХ
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
# 5. ФУНКЦИИ РАБОТЫ С БД
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
# 6. ХРАНИЛИЩЕ СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЕЙ (FSM)
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
# 7. ВОПРОСЫ ДЛЯ ОПРОСА
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
# 8. ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ (LONG POLLING)
# =========================================================
def get_updates(marker=None):
    url = f"{API_BASE}/updates"
    params = {"timeout": 30, "limit": 100}
    if marker is not None:
        params["marker"] = marker
    try:
        resp = requests.get(url, headers={"Authorization": TOKEN}, params=params, timeout=40, verify=False)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.error(f"❌ Ошибка получения обновлений: {resp.status_code} - {resp.text}")
            return {}
    except Exception as e:
        logger.error(f"❌ Исключение при получении: {e}")
        return {}

# =========================================================
# 9. УВЕДОМЛЕНИЕ АДМИНОВ
# =========================================================
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

# =========================================================
# 10. ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ
# =========================================================
def handle_message(update):
    message = update.get('message', {})
    if not message:
        return

    sender = message.get('sender', {})
    user_id = sender.get('user_id')
    body = message.get('body', {})
    text = body.get('text', '').strip()

    if not user_id or not text:
        return

    logger.info(f"📩 Получено сообщение от {user_id}: {text[:50]}")

    # === ОБРАБОТКА КОМАНД ===
    if text.startswith('/'):
        command_parts = text.split(maxsplit=2)
        if not command_parts:
            return
        command = command_parts[0].lower()
        is_admin = user_id in ADMIN_IDS

        if command == '/help':
            send_message(user_id,
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
            return

        if command == '/start':
            send_message(user_id,
                "👋 Привет! Я бот для подачи новостей.\n"
                "Чтобы начать, отправьте /news\n"
                "Для справки используйте /help"
            )
            return

        elif command == '/id':
            send_message(user_id, f"Ваш ID: {user_id}")
            return

        elif command == '/cancel':
            if get_user_state(user_id) is not None:
                clear_user_state(user_id)
                send_message(user_id, "✅ Заявка отменена.")
            else:
                send_message(user_id, "Нет активной заявки.")
            return

        elif command == '/news':
            if get_user_state(user_id) is not None:
                send_message(user_id, "У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            send_message(user_id, QUESTIONS[0][1])
            return

        elif command == '/pending':
            if not is_admin:
                send_message(user_id, "⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                send_message(user_id, "Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
            send_message(user_id, msg)
            return

        elif command == '/approve':
            if not is_admin:
                send_message(user_id, "⛔ Нет прав.")
                return
            if len(command_parts) < 2:
                send_message(user_id, "Использование: /approve <id> [комментарий]")
                return
            try:
                app_id = int(command_parts[1])
            except ValueError:
                send_message(user_id, "ID должен быть числом.")
                return
            feedback = command_parts[2] if len(command_parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message(user_id, f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                send_message(user_id, f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'approved', feedback)
            send_message(user_id, f"✅ Заявка #{app_id} одобрена.")
            try:
                send_message(int(app[1]), f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
            except:
                pass
            return

        elif command == '/reject':
            if not is_admin:
                send_message(user_id, "⛔ Нет прав.")
                return
            if len(command_parts) < 2:
                send_message(user_id, "Использование: /reject <id> [комментарий]")
                return
            try:
                app_id = int(command_parts[1])
            except ValueError:
                send_message(user_id, "ID должен быть числом.")
                return
            feedback = command_parts[2] if len(command_parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message(user_id, f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                send_message(user_id, f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'rejected', feedback)
            send_message(user_id, f"❌ Заявка #{app_id} отклонена.")
            try:
                send_message(int(app[1]), f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
            except:
                pass
            return

        elif command == '/stats':
            if not is_admin:
                send_message(user_id, "⛔ Нет прав.")
                return
            total, pending, approved, rejected = get_stats()
            send_message(user_id,
                f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            )
            return

        else:
            send_message(user_id, "Неизвестная команда. Используйте /help для справки.")
            return

    # === ОБРАБОТКА СОСТОЯНИЙ ОПРОСА ===
    state = get_user_state(user_id)
    if state is None:
        return

    step = state['step']
    data = state['data']

    if step == -1:
        if text.lower() == "да":
            app_id = save_application(user_id, data)
            clear_user_state(user_id)
            send_message(user_id, "✅ Заявка успешно отправлена на модерацию!")
            notify_admins(app_id, data)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            send_message(user_id, "❌ Заявка отменена.")
        else:
            send_message(user_id, 'Пожалуйста, ответьте "Да" или "Нет".')
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            send_message(user_id, QUESTIONS[next_step][1])
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
            send_message(user_id, summary)

# =========================================================
# 11. ТЕСТОВАЯ ОТПРАВКА ПРИ ЗАПУСКЕ
# =========================================================
def send_startup_test():
    for admin_id in ADMIN_IDS:
        send_message(admin_id, "🚀 Бот запущен и готов к работе!")

# =========================================================
# 12. ОСНОВНОЙ ЦИКЛ
# =========================================================
def main():
    logger.info("🚀 Бот запущен...")
    send_startup_test()
    marker = None

    while True:
        try:
            data = get_updates(marker)
            for update in data.get('updates', []):
                if update.get('update_type') == 'message_created':
                    handle_message(update)
            if data.get('marker') is not None:
                marker = data['marker']
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
