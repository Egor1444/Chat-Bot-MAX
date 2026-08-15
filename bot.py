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
    logging.warning("⚠️ Токен взят из кода (только для теста)")

logging.basicConfig(level=logging.INFO)
logging.info(f"🔑 Токен (первые 4): {TOKEN[:4]}..., длина {len(TOKEN)}")

API_BASE = "https://platform-api2.max.ru"
ADMIN_IDS = [364551480]  # Ваш user_id

# ===== ПРОВЕРКА АВТОРИЗАЦИИ =====
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
    raise RuntimeError("❌ Не удалось авторизоваться. Проверьте токен.")

# ===== БАЗА ДАННЫХ =====
DB_PATH = "news.db"
# ... (весь код БД, функций, состояний, вопросов — без изменений, как в предыдущей версии)
# Я не буду повторять его здесь, чтобы не загромождать, но он должен быть полностью.

# ===== ОТПРАВКА СООБЩЕНИЙ С ПЕРЕБОРОМ ID =====
def send_message(recipient_id, text):
    """
    Пытается отправить сообщение на переданный ID, а также на альтернативные ID.
    Логирует все попытки и результаты.
    """
    # Список ID для проверки: сначала переданный, затем альтернативные
    ids_to_try = [recipient_id, 2712418, 364551480]
    # Убираем дубликаты
    ids_to_try = list(dict.fromkeys(ids_to_try))
    
    for idx, target_id in enumerate(ids_to_try):
        url = f"{API_BASE}/messages"
        headers = {'Authorization': TOKEN}
        params = {'chat_id': str(target_id), 'text': text}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10, verify=False)
            logging.info(f"📤 Попытка {idx+1}: отправка на ID={target_id} -> статус {resp.status_code}")
            if resp.status_code == 200:
                logging.info(f"✅ УСПЕШНО! Сообщение отправлено на ID={target_id}")
                return True
            else:
                logging.warning(f"❌ Ошибка на ID={target_id}: {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            logging.error(f"❌ Исключение на ID={target_id}: {e}")
    
    logging.error("❌ Все попытки отправки не удались.")
    return False

# ===== ТЕСТОВАЯ ОТПРАВКА ПРИ ЗАПУСКЕ =====
def send_startup_test():
    test_text = "🚀 Бот запущен и работает! Это тестовое сообщение."
    logging.info("📤 Отправка тестового сообщения администратору...")
    for admin_id in ADMIN_IDS:
        send_message(admin_id, test_text)

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

# ===== ОБРАБОТКА СООБЩЕНИЙ (без изменений) =====
def handle_message(update):
    # ... (весь код handle_message, который был ранее)
    pass

# ===== ОСНОВНОЙ ЦИКЛ =====
def main():
    logging.info("🚀 Бот запущен...")
    
    # Отправляем тестовое сообщение администратору
    send_startup_test()
    
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
