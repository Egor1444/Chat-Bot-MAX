import os
import time
import logging
import sqlite3
import requests
import urllib3
from collections import deque

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ===== КОНФИГУРАЦИЯ =====
API_BASE = "https://platform-api.max.ru"  # или platform-api2.max.ru
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logging.warning("⚠️ Токен взят из кода (только для теста)")

ADMIN_IDS = [364551480]  # Ваш user_id
DB_PATH = "news.db"
HEADERS = {"Authorization": TOKEN}

# ===== ХРАНИЛИЩЕ CHAT_ID АДМИНИСТРАТОРОВ =====
admin_chat_ids = {}

# ===== ЗАЩИТА ОТ ДУБЛЕЙ =====
_SEEN = deque(maxlen=200)

def dedup_key(update: dict) -> tuple:
    msg = update.get('message', {})
    body = msg.get('body', {})
    mid = body.get('mid')
    return (update.get('update_type'), update.get('timestamp'), mid)

# ===== БАЗА ДАННЫХ =====
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

# ===== ФУНКЦИИ БД =====
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

# ===== ОТПРАВКА СООБЩЕНИЙ (GET — рабочий) =====
def send_message_safe(chat_id: int, text: str, retries: int = 3) -> bool:
    url = f"{API_BASE}/messages"
    params = {'chat_id': chat_id, 'text': text}
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20, verify=False)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                logging.warning("⚠️ Ограничение частоты (429). Ожидание %s сек...", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 200:
                logging.info(f"✅ Сообщение отправлено в чат {chat_id}")
                return True
            else:
                logging.error(f"❌ Ошибка отправки на {chat_id}: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logging.error(f"❌ Исключение при отправке на {chat_id}: {e}")
            time.sleep(1)
    return False

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ =====
def get_updates(marker=None):
    url = f"{API_BASE}/updates"
    params = {"timeout": 30, "limit": 100}
    if marker is not None:
        params["marker"] = marker
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=40, verify=False)
        if resp.status_code == 200:
            return resp.json()
        logging.error(f"❌ Ошибка получения обновлений: {resp.status_code}")
        return {}
    except Exception as e:
        logging.error(f"❌ Исключение при получении: {e}")
        return {}

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
        chat_id = admin_chat_ids.get(admin_id)
        if chat_id:
            send_message_safe(chat_id, text)
        else:
            logging.warning(f"⚠️ Chat_id для администратора {admin_id} не найден. Уведомление пропущено.")

# ===== ОБРАБОТКА СООБЩЕНИЙ =====
def handle_message(update):
    key = dedup_key(update)
    if key in _SEEN:
        return
    _SEEN.append(key)

    message = update.get('message', {})
    if not message:
        return

    recipient = message.get('recipient', {})
    chat_id = recipient.get('chat_id')
    sender = message.get('sender', {})
    user_id = sender.get('user_id')

    if not chat_id or not user_id:
        return

    # === СОХРАНЯЕМ CHAT_ID АДМИНИСТРАТОРА ===
    if int(user_id) in ADMIN_IDS:
        admin_chat_ids[int(user_id)] = chat_id
        logging.info(f"👤 Сохранён chat_id администратора {user_id}: {chat_id}")

    body = message.get('body', {})
    text = body.get('text', '').strip()

    if not text:
        return

    logging.info(f"📩 Получено сообщение от {user_id} в чат {chat_id}: {text[:50]}")

    # === ОБРАБОТКА КОМАНД ===
    if text.startswith('/'):
        command_parts = text.split(maxsplit=2)
        if not command_parts:
            return
        command = command_parts[0].lower()
        is_admin = int(user_id) in ADMIN_IDS

        # --- /help ---
        if command == '/help':
            help_text = (
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
            send_message_safe(chat_id, help_text)
            return

        # --- /start с параметром (deep link) ---
        if command == '/start':
            if len(command_parts) > 1:
                param = command_parts[1]
                send_message_safe(chat_id, f"👋 Привет! Вы перешли по ссылке с параметром: {param}")
            else:
                send_message_safe(chat_id,
                    "👋 Привет! Я бот для подачи новостей.\n"
                    "Чтобы начать, отправьте /news\n"
                    "Для справки используйте /help"
                )
            return

        # --- /id ---
        elif command == '/id':
            send_message_safe(chat_id, f"Ваш ID: {user_id} | Chat ID: {chat_id}")
            return

        # --- /cancel ---
        elif command == '/cancel':
            if get_user_state(user_id) is not None:
                clear_user_state(user_id)
                send_message_safe(chat_id, "✅ Заявка отменена.")
            else:
                send_message_safe(chat_id, "Нет активной заявки.")
            return

        # --- /news ---
        elif command == '/news':
            if get_user_state(user_id) is not None:
                send_message_safe(chat_id, "У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            send_message_safe(chat_id, QUESTIONS[0][1])
            return

        # --- /pending ---
        elif command == '/pending':
            if not is_admin:
                send_message_safe(chat_id, "⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                send_message_safe(chat_id, "Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
            send_message_safe(chat_id, msg)
            return

        # --- /approve ---
        elif command == '/approve':
            if not is_admin:
                send_message_safe(chat_id, "⛔ Нет прав.")
                return
            if len(command_parts) < 2:
                send_message_safe(chat_id, "Использование: /approve <id> [комментарий]")
                return
            try:
                app_id = int(command_parts[1])
            except ValueError:
                send_message_safe(chat_id, "ID должен быть числом.")
                return
            feedback = command_parts[2] if len(command_parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message_safe(chat_id, f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                send_message_safe(chat_id, f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'approved', feedback)
            send_message_safe(chat_id, f"✅ Заявка #{app_id} одобрена.")
            # Уведомление пользователя
            try:
                send_message_safe(int(app[1]), f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
            except:
                pass
            return

        # --- /reject ---
        elif command == '/reject':
            if not is_admin:
                send_message_safe(chat_id, "⛔ Нет прав.")
                return
            if len(command_parts) < 2:
                send_message_safe(chat_id, "Использование: /reject <id> [комментарий]")
                return
            try:
                app_id = int(command_parts[1])
            except ValueError:
                send_message_safe(chat_id, "ID должен быть числом.")
                return
            feedback = command_parts[2] if len(command_parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                send_message_safe(chat_id, f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                send_message_safe(chat_id, f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'rejected', feedback)
            send_message_safe(chat_id, f"❌ Заявка #{app_id} отклонена.")
            try:
                send_message_safe(int(app[1]), f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
            except:
                pass
            return

        # --- /stats ---
        elif command == '/stats':
            if not is_admin:
                send_message_safe(chat_id, "⛔ Нет прав.")
                return
            total, pending, approved, rejected = get_stats()
            send_message_safe(
                chat_id,
                f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            )
            return

        else:
            send_message_safe(chat_id, "Неизвестная команда. Используйте /help для справки.")
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
            send_message_safe(chat_id, "✅ Заявка успешно отправлена на модерацию!")
            notify_admins(app_id, data)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            send_message_safe(chat_id, "❌ Заявка отменена.")
        else:
            send_message_safe(chat_id, 'Пожалуйста, ответьте "Да" или "Нет".')
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            send_message_safe(chat_id, QUESTIONS[next_step][1])
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
            send_message_safe(chat_id, summary)

# ===== ОСНОВНОЙ ЦИКЛ =====
def main():
    logging.info("🚀 Бот запущен...")
    marker = None

    while True:
        try:
            data = get_updates(marker)
            for update in data.get('updates', []):
                if update.get('update_type') != 'message_created':
                    continue
                handle_message(update)
            if data.get('marker') is not None:
                marker = data['marker']
        except Exception as e:
            logging.error(f"❌ Ошибка в цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
