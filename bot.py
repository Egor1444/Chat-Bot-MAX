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
    raise ValueError("❌ Токен не найден! Установите BOT_TOKEN или MAX_BOT_TOKEN")
logging.info(f"🔑 Токен (первые 4): {TOKEN[:4]}..., длина {len(TOKEN)}")

API_BASE = "https://platform-api2.max.ru"
ADMIN_IDS = [123456789]  # ⚠️ замените на свой ID
logging.basicConfig(level=logging.INFO)

# ===== АВТОРИЗАЦИЯ =====
def check_auth():
    url = f"{API_BASE}/me"
    headers = {'Authorization': TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            logging.info("✅ Авторизация успешна!")
            return headers
        else:
            logging.error(f"❌ Ошибка авторизации: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        logging.error(f"❌ Ошибка подключения: {e}")
        return None

AUTH_HEADERS = check_auth()
if not AUTH_HEADERS:
    raise RuntimeError("Не удалось авторизоваться. Проверьте токен.")

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

# ===== ОТПРАВКА СООБЩЕНИЙ (С ПЕРЕБОРОМ ВСЕХ ВАРИАНТОВ) =====
def send_message(recipient_id, text, sender_id=None):
    """
    Пытается отправить сообщение, перебирая все возможные комбинации:
    - эндпоинты: /messages, /sendMessage
    - поля: chatId, chat_id, recipient.chat_id, peer_id, user_id
    - типы: строка, число
    - методы: POST (JSON), POST (form), GET
    """
    # Преобразуем ID в число и строку
    try:
        id_int = int(recipient_id)
    except:
        id_int = recipient_id
    id_str = str(recipient_id)

    # Если передан sender_id, тоже добавим его в перебор
    sender_id_str = str(sender_id) if sender_id else None
    sender_id_int = int(sender_id) if sender_id and str(sender_id).isdigit() else None

    # Список вариантов (эндпоинт, метод, данные)
    variants = []

    # 1. POST /messages с JSON
    base_url = f"{API_BASE}/messages"
    headers_json = AUTH_HEADERS.copy()
    headers_json['Content-Type'] = 'application/json'

    # Варианты payload для /messages
    payloads = [
        # chatId (строка)
        {"chatId": id_str, "text": text},
        # chatId (число)
        {"chatId": id_int, "text": text},
        # recipient.chat_id (строка)
        {"recipient": {"chat_id": id_str}, "text": text},
        # recipient.chat_id (число)
        {"recipient": {"chat_id": id_int}, "text": text},
        # peer_id (число)
        {"peer_id": id_int, "text": text},
        # user_id (если есть)
    ]
    if sender_id_str:
        payloads.append({"user_id": sender_id_str, "text": text})
    if sender_id_int:
        payloads.append({"user_id": sender_id_int, "text": text})

    for payload in payloads:
        variants.append({
            "url": base_url,
            "method": "POST",
            "headers": headers_json,
            "data": payload,
            "desc": f"POST /messages {list(payload.keys())}"
        })

    # 2. POST /sendMessage с form-data
    url_form = f"{API_BASE}/sendMessage"
    headers_form = AUTH_HEADERS.copy()
    headers_form['Content-Type'] = 'application/x-www-form-urlencoded'
    # Поля для form-data
    form_fields = [
        {'chat_id': id_str, 'text': text},
        {'chat_id': id_int, 'text': text},
        {'recipient': id_str, 'text': text},
        {'peer_id': id_int, 'text': text},
        {'user_id': id_str, 'text': text},
    ]
    if sender_id_str:
        form_fields.append({'user_id': sender_id_str, 'text': text})
    for fields in form_fields:
        variants.append({
            "url": url_form,
            "method": "POST",
            "headers": headers_form,
            "data": fields,
            "desc": f"POST /sendMessage {list(fields.keys())}"
        })

    # 3. GET /sendMessage с параметрами в строке
    url_get = f"{API_BASE}/sendMessage"
    get_params_list = [
        {'chat_id': id_str, 'text': text},
        {'chat_id': id_int, 'text': text},
        {'recipient': id_str, 'text': text},
        {'peer_id': id_int, 'text': text},
        {'user_id': id_str, 'text': text},
    ]
    if sender_id_str:
        get_params_list.append({'user_id': sender_id_str, 'text': text})
    for params in get_params_list:
        variants.append({
            "url": url_get,
            "method": "GET",
            "headers": AUTH_HEADERS,
            "params": params,
            "desc": f"GET /sendMessage {list(params.keys())}"
        })

    # Логируем количество попыток
    logging.info(f"📤 Начинаем перебор {len(variants)} вариантов отправки для recipient_id={recipient_id}")

    # Перебираем все варианты
    for variant in variants:
        try:
            if variant["method"] == "POST":
                resp = requests.post(
                    variant["url"],
                    json=variant.get("data"),
                    data=variant.get("data") if variant.get("headers", {}).get("Content-Type") == "application/x-www-form-urlencoded" else None,
                    headers=variant["headers"],
                    timeout=10,
                    verify=False
                )
            else:  # GET
                resp = requests.get(
                    variant["url"],
                    params=variant.get("params"),
                    headers=variant["headers"],
                    timeout=10,
                    verify=False
                )
            if resp.status_code == 200:
                logging.info(f"✅ Успешно отправлено через {variant['desc']}")
                return resp.json()
            else:
                logging.debug(f"❌ {variant['desc']} вернул {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logging.debug(f"Ошибка при {variant['desc']}: {e}")

    logging.error(f"❌ Все способы отправки для recipient_id={recipient_id} не удались.")
    return None

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ =====
def get_updates(offset=None):
    url = f"{API_BASE}/updates"
    params = {'limit': 10, 'timeout': 30}
    if offset:
        params['offset'] = offset
    try:
        response = requests.get(url, headers=AUTH_HEADERS, params=params, timeout=35, verify=False)
        if response.status_code == 200:
            data = response.json()
            return data.get('updates', [])
        else:
            logging.error(f"❌ Ошибка получения обновлений: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        logging.error(f"❌ Исключение при получении: {e}")
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
        # Для администратора используем его ID как recipient_id, но sender_id не передаём
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
            # Пытаемся отправить ответ, используя и chat_id, и user_id как получателя
            # Сначала пробуем chat_id (из recipient), затем user_id (из sender)
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, 
                    "👋 Привет! Я бот для подачи новостей.\n"
                    "Чтобы начать, отправьте /news\n\n"
                    "Администратор:\n"
                    "/pending — список заявок\n"
                    "/approve <id> [комментарий]\n"
                    "/reject <id> [комментарий]\n"
                    "/stats — статистика",
                    sender_id=user_id
                ):
                    break  # Если отправка удалась, выходим
            return
        elif command == '/id':
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, f"Ваш ID: {user_id}", sender_id=user_id):
                    break
            return
        elif command == '/cancel':
            if user_id in user_states:
                clear_user_state(user_id)
                msg = "✅ Заявка отменена."
            else:
                msg = "Нет активной заявки."
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        elif command == '/news':
            if user_id in user_states:
                msg = "У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её."
            else:
                set_user_state(user_id, 0)
                msg = QUESTIONS[0][1]
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        elif command == '/pending':
            if int(user_id) not in ADMIN_IDS:
                msg = "⛔ Нет прав."
            else:
                rows = get_pending_applications()
                if not rows:
                    msg = "Нет заявок."
                else:
                    msg = "📋 Ожидающие заявки:\n\n"
                    for row in rows:
                        msg += f"ID: {row[0]}, {row[2]}, {row[-1]}\n"
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        elif command == '/approve':
            if int(user_id) not in ADMIN_IDS:
                msg = "⛔ Нет прав."
            else:
                args = text.split(maxsplit=2)
                if len(args) < 2:
                    msg = "Использование: /approve <id> [комментарий]"
                else:
                    try:
                        app_id = int(args[1])
                    except ValueError:
                        msg = "ID должен быть числом."
                    else:
                        feedback = args[2] if len(args) > 2 else ""
                        app = get_application_by_id(app_id)
                        if not app:
                            msg = f"Заявка #{app_id} не найдена."
                        elif app[9] != 'pending':
                            msg = f"Заявка уже обработана (статус: {app[9]})."
                        else:
                            update_status(app_id, 'approved', feedback)
                            msg = f"✅ Заявка #{app_id} одобрена."
                            # Уведомляем пользователя
                            try:
                                send_message(str(app[1]), f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
                            except:
                                pass
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        elif command == '/reject':
            if int(user_id) not in ADMIN_IDS:
                msg = "⛔ Нет прав."
            else:
                args = text.split(maxsplit=2)
                if len(args) < 2:
                    msg = "Использование: /reject <id> [комментарий]"
                else:
                    try:
                        app_id = int(args[1])
                    except ValueError:
                        msg = "ID должен быть числом."
                    else:
                        feedback = args[2] if len(args) > 2 else ""
                        app = get_application_by_id(app_id)
                        if not app:
                            msg = f"Заявка #{app_id} не найдена."
                        elif app[9] != 'pending':
                            msg = f"Заявка уже обработана (статус: {app[9]})."
                        else:
                            update_status(app_id, 'rejected', feedback)
                            msg = f"❌ Заявка #{app_id} отклонена."
                            try:
                                send_message(str(app[1]), f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
                            except:
                                pass
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        elif command == '/stats':
            if int(user_id) not in ADMIN_IDS:
                msg = "⛔ Нет прав."
            else:
                total, pending, approved, rejected = get_stats()
                msg = f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            return
        else:
            msg = "Неизвестная команда. Используйте /start для справки."
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
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
            msg = "✅ Заявка успешно отправлена на модерацию!"
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
            notify_admins(app_id, data, user_id)
        elif text.lower() == "нет":
            clear_user_state(user_id)
            msg = "❌ Заявка отменена."
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
        else:
            msg = 'Пожалуйста, ответьте "Да" или "Нет".'
            for recipient_candidate in [chat_id, user_id]:
                if send_message(recipient_candidate, msg, sender_id=user_id):
                    break
        return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            msg = QUESTIONS[next_step][1]
        else:
            set_user_state(user_id, -1, data)
            msg = (
                "📋 Проверьте введённые данные:\n\n"
                f"1. ФИО: {data.get('full_name', '—')}\n"
                f"2. Суть: {data.get('action_desc', '—')}\n"
                f"3. Польза: {data.get('benefit', '—')}\n"
                f"4. Как пришли: {data.get('how_came', '—')}\n"
                f"5. Место/время: {data.get('place_time', '—')}\n"
                "\nОтправьте «Да» для подтверждения или «Нет» для отмены."
            )
        for recipient_candidate in [chat_id, user_id]:
            if send_message(recipient_candidate, msg, sender_id=user_id):
                break

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
