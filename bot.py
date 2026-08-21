import os
import time
import json
import logging
import requests
import urllib3
from collections import deque

# Отключаем SSL-предупреждения
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================
# 1. КОНФИГУРАЦИЯ
# =========================================================
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. Убедитесь, что он правильный.")

ADMIN_IDS = [364551480]   # Ваш user_id

# =========================================================
# 2. ПРОВЕРКА ТОКЕНА
# =========================================================
def check_token():
    url = "https://platform-api.max.ru/me"
    headers = {"Authorization": TOKEN}
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            logger.info("✅ Токен действителен.")
            return True
        else:
            logger.error(f"❌ Токен не прошёл проверку: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке токена: {e}")
        return False

if not check_token():
    logger.critical("❌ Токен невалидный. Бот не будет работать.")
    exit(1)

# =========================================================
# 3. ФУНКЦИЯ ОТПРАВКИ С ПЕРЕБОРОМ ВАРИАНТОВ
# =========================================================
def send_message_with_fallback(chat_id, text, user_id=None):
    """
    Пытается отправить сообщение, перебирая все возможные комбинации.
    Возвращает True, если хотя бы одна попытка успешна.
    """
    base_urls = [
        "https://platform-api.max.ru",
        "https://platform-api2.max.ru"
    ]
    endpoints = [
        "/messages",
        "/sendMessage",
        "/send",
        "/message"
    ]
    methods = ["POST", "GET"]
    # Поля, которые могут содержать ID получателя
    field_names = [
        ("chat_id", chat_id),
        ("chatId", chat_id),
        ("recipient", {"chat_id": chat_id}),
        ("recipient_id", chat_id),
        ("user_id", user_id if user_id else chat_id),
        ("to", chat_id),
    ]
    # Для GET используем параметры запроса
    for base in base_urls:
        for endpoint in endpoints:
            url = base + endpoint
            for method in methods:
                for field_name, field_value in field_names:
                    # Для GET формируем params
                    if method == "GET":
                        params = {"chat_id": chat_id, "text": text}
                        if field_name in ["chatId", "recipient_id", "user_id", "to"]:
                            params = {field_name: chat_id, "text": text}
                        try:
                            resp = requests.get(url, params=params, headers={"Authorization": TOKEN}, timeout=10, verify=False)
                            if resp.status_code == 200:
                                logger.info(f"✅ Успешно! GET {url} с params={params}")
                                return True
                            else:
                                logger.debug(f"❌ GET {url} {params} -> {resp.status_code}")
                        except Exception as e:
                            logger.debug(f"⚠️ Ошибка GET {url}: {e}")
                    else:  # POST
                        # Пробуем JSON
                        if isinstance(field_value, dict):
                            payload = {"recipient": field_value, "text": text}
                        else:
                            payload = {field_name: field_value, "text": text}
                        try:
                            resp = requests.post(url, json=payload, headers={"Authorization": TOKEN, "Content-Type": "application/json"}, timeout=10, verify=False)
                            if resp.status_code == 200:
                                logger.info(f"✅ Успешно! POST {url} с payload={payload}")
                                return True
                            else:
                                logger.debug(f"❌ POST {url} {payload} -> {resp.status_code}")
                        except Exception as e:
                            logger.debug(f"⚠️ Ошибка POST {url}: {e}")
                        # Пробуем form-data
                        try:
                            resp = requests.post(url, data=payload, headers={"Authorization": TOKEN, "Content-Type": "application/x-www-form-urlencoded"}, timeout=10, verify=False)
                            if resp.status_code == 200:
                                logger.info(f"✅ Успешно! POST form-data {url} с data={payload}")
                                return True
                            else:
                                logger.debug(f"❌ POST form-data {url} {payload} -> {resp.status_code}")
                        except Exception as e:
                            logger.debug(f"⚠️ Ошибка POST form-data {url}: {e}")
    logger.error("❌ Все попытки отправки не удались.")
    return False

# =========================================================
# 4. ТЕСТОВАЯ ОТПРАВКА
# =========================================================
def test_send():
    # Пробуем отправить тестовое сообщение администратору
    for admin_id in ADMIN_IDS:
        logger.info(f"📤 Тестовая отправка администратору {admin_id}...")
        result = send_message_with_fallback(admin_id, "🚀 Тестовое сообщение от бота.")
        if result:
            logger.info("✅ Тестовое сообщение отправлено.")
        else:
            logger.error("❌ Тестовое сообщение не отправлено.")

test_send()

# =========================================================
# 5. ОСНОВНАЯ ЛОГИКА БОТА (получение обновлений)
# =========================================================
def get_updates(marker=None):
    url = "https://platform-api.max.ru/updates"
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

def handle_message(update):
    # Простая обработка: просто логируем входящее сообщение
    message = update.get('message', {})
    if not message:
        return
    sender = message.get('sender', {})
    user_id = sender.get('user_id')
    body = message.get('body', {})
    text = body.get('text', '')
    if user_id and text:
        logger.info(f"📩 Входящее сообщение от {user_id}: {text[:50]}")
        # Отвечаем эхо (если отправка работает)
        if send_message_with_fallback(user_id, f"Вы сказали: {text}", user_id):
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
                if 'marker' in data:
                    marker = data['marker']
            if data.get('marker') is not None:
                marker = data['marker']
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
