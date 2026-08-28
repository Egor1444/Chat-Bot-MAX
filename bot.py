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
API_BASE = "https://platform-api2.max.ru"  # Только базовый URL!
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]   # Ваш user_id
DB_PATH = "news.db"

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
    """
    Отправляет сообщение через GET /messages?user_id={user_id}&text={text}
    Это правильный метод из документации MAX.
    """
    url = f"{API_BASE}/messages"
    params = {
        "user_id": recipient_id,   # Правильный параметр для личных сообщений
        "text": text
    }
    headers = {"Authorization": TOKEN}
    
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
# 4. БАЗА ДАННЫХ И ВСЯ ОСТАЛЬНАЯ ЛОГИКА (БЕЗ ИЗМЕНЕНИЙ)
# =========================================================
# (здесь идёт весь код БД, состояний, команд и цикла – см. предыдущие ответы)
# Я не повторяю его здесь, чтобы не загромождать ответ,
# но он полностью идентичен тому, что я дал в прошлом сообщении.
# Главное – функция send_message теперь правильная.
