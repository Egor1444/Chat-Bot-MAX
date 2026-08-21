import os
import time
import json
import logging
import requests
import urllib3
from collections import deque

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода.")

ADMIN_IDS = [364551480]  # Ваш user_id

# ===== ПРОВЕРКА ТОКЕНА =====
def check_token():
    for base in ["https://platform-api.max.ru", "https://platform-api2.max.ru"]:
        url = f"{base}/me"
        try:
            resp = requests.get(url, headers={"Authorization": TOKEN}, timeout=10, verify=False)
            if resp.status_code == 200:
                logger.info(f"✅ Токен действителен на {base}")
                return base
            else:
                logger.warning(f"❌ {base}/me вернул {resp.status_code}")
        except Exception as e:
            logger.error(f"Ошибка {base}: {e}")
    return None

API_BASE = check_token()
if not API_BASE:
    logger.critical("❌ Токен невалидный.")
    exit(1)

# ===== ПЕРЕБОР ВСЕХ ВАРИАНТОВ ОТПРАВКИ =====
def send_message_variants(chat_id, text, user_id=None):
    """
    Перебирает все возможные комбинации для отправки сообщения.
    Возвращает True, если хотя бы одна удалась.
    """
    endpoints = ["/messages", "/sendMessage", "/send", "/message"]
    methods = ["POST", "GET"]
    # Поля, которые могут содержать ID получателя
    field_variants = [
        ("chat_id", chat_id),
        ("chatId", chat_id),
        ("recipient", {"chat_id": chat_id}),
        ("recipient_id", chat_id),
        ("user_id", user_id if user_id else chat_id),
        ("to", chat_id),
    ]
    # Варианты передачи токена
    auth_headers = [
        {"Authorization": TOKEN},
        {"Authorization": f"Bearer {TOKEN}"},
        {"X-API-Key": TOKEN},
    ]
    base_urls = [API_BASE, "https://platform-api.max.ru", "https://platform-api2.max.ru"]

    for base in base_urls:
        for endpoint in endpoints:
            # Вариант с токеном в URL (как в Telegram)
            for token_in_url in [False, True]:
                if token_in_url:
                    url = f"{base}/bot{TOKEN}{endpoint}"
                    headers = {}
                else:
                    url = f"{base}{endpoint}"
                    headers = {"Authorization": TOKEN}
                for method in methods:
                    for field_name, field_value in field_variants:
                        # Формируем payload в зависимости от поля
                        if isinstance(field_value, dict):
                            payload = {"recipient": field_value, "text": text}
                        else:
                            payload = {field_name: field_value, "text": text}
                        # Пробуем разные форматы
                        for content_type in ["json", "form", "params"]:
                            try:
                                if method == "GET":
                                    if content_type != "params":
                                        continue
                                    resp = requests.get(url, params=payload, headers=headers, timeout=10, verify=False)
                                else:  # POST
                                    if content_type == "json":
                                        headers["Content-Type"] = "application/json"
                                        resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
                                    elif content_type == "form":
                                        headers["Content-Type"] = "application/x-www-form-urlencoded"
                                        resp = requests.post(url, data=payload, headers=headers, timeout=10, verify=False)
                                    else:
                                        continue
                                if resp.status_code == 200:
                                    logger.info(f"✅ УСПЕХ: {method} {url} {content_type} {field_name} -> 200")
                                    return True
                                else:
                                    logger.debug(f"❌ {method} {url} {content_type} {field_name} -> {resp.status_code}")
                            except Exception as e:
                                logger.debug(f"⚠️ Ошибка: {e}")
    return False

# ===== ТЕСТОВАЯ ОТПРАВКА =====
def test_send():
    for admin_id in ADMIN_IDS:
        logger.info(f"📤 Тестовая отправка администратору {admin_id}...")
        if send_message_variants(admin_id, "🚀 Тест от бота", admin_id):
            logger.info("✅ Тестовая отправка успешна!")
        else:
            logger.error("❌ Тестовая отправка не удалась.")

test_send()

# ===== ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ =====
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
            logger.error(f"❌ Ошибка получения обновлений: {resp.status_code}")
            return {}
    except Exception as e:
        logger.error(f"❌ Исключение при получении: {e}")
        return {}

def handle_message(update):
    message = update.get('message', {})
    if not message:
        return
    sender = message.get('sender', {})
    user_id = sender.get('user_id')
    body = message.get('body', {})
    text = body.get('text', '')
    if user_id and text:
        logger.info(f"📩 Входящее сообщение от {user_id}: {text[:50]}")
        # Отвечаем эхо
        if send_message_variants(user_id, f"Вы сказали: {text}", user_id):
            logger.info(f"✅ Ответ отправлен пользователю {user_id}")
        else:
            logger.error(f"❌ Не удалось отправить ответ пользователю {user_id}")

def main():
    logger.info("🚀 Бот запущен...")
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
