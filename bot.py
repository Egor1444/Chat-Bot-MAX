import os
import time
import logging
import sqlite3
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройка логирования с подробным выводом
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================
# 1. КОНФИГУРАЦИЯ
# =========================================================
API_BASE = "https://platform-api2.max.ru"
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]   # Ваш user_id
DB_PATH = "news.db"

logger.info("🔧 Конфигурация загружена")
logger.info(f"🔑 Токен (маска): {TOKEN[:4]}...{TOKEN[-4:]}, длина: {len(TOKEN)}")

# =========================================================
# 2. ПРОВЕРКА ТОКЕНА (GET /me)
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
# 3. ОТПРАВКА СООБЩЕНИЙ (ПРАВИЛЬНЫЙ МЕТОД)
# =========================================================
def send_message(recipient_id: int, text: str, retries: int = 3) -> bool:
    url = f"{API_BASE}/messages"
    params = {
        "user_id": recipient_id,
        "text": text
    }
    headers = {"Authorization": TOKEN}
    
    logger.info(f"📤 Попытка отправки пользователю {recipient_id}")
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20, verify=False)
            logger.info(f"📤 GET /messages?user_id={recipient_id} -> статус {resp.status_code}")
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                logger.warning(f"⚠️ 429 Too Many Requests, ждём {wait} сек...")
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
# 4. ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ (LONG POLLING)
# =========================================================
def get_updates(marker=None):
    url = f"{API_BASE}/updates"
    params = {"timeout": 30, "limit": 100}
    if marker is not None:
        params["marker"] = marker
    try:
        logger.info(f"📥 Запрос обновлений с marker={marker}")
        resp = requests.get(url, headers={"Authorization": TOKEN}, params=params, timeout=40, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"📥 Получено {len(data.get('updates', []))} обновлений")
            return data
        else:
            logger.error(f"❌ Ошибка получения обновлений: {resp.status_code} - {resp.text}")
            return {}
    except Exception as e:
        logger.error(f"❌ Исключение при получении: {e}")
        return {}

# =========================================================
# 5. БАЗА ДАННЫХ И ОСТАЛЬНАЯ ЛОГИКА
# =========================================================
# (вставляем сюда весь код БД, состояний, команд – он идентичен предыдущей версии)
# Я сокращу для компактности, но вы должны скопировать его из предыдущего ответа.
# =========================================================

# =========================================================
# 6. ТЕСТОВАЯ ОТПРАВКА ПРИ ЗАПУСКЕ
# =========================================================
def send_startup_test():
    logger.info("📤 Отправка тестового сообщения администратору...")
    for admin_id in ADMIN_IDS:
        send_message(admin_id, "🚀 Бот запущен и готов к работе!")

# =========================================================
# 7. ОСНОВНОЙ ЦИКЛ
# =========================================================
def main():
    logger.info("🚀 Бот запущен, вход в основной цикл...")
    send_startup_test()
    
    marker = None
    while True:
        try:
            data = get_updates(marker)
            for update in data.get('updates', []):
                if update.get('update_type') == 'message_created':
                    handle_message(update)  # функция handle_message должна быть определена
            if data.get('marker') is not None:
                marker = data['marker']
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logger.info("📌 Запуск скрипта")
    main()
