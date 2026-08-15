import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"

# Ваши ID из логов
CHAT_ID_FROM_LOG = 2712418      # recipient.chat_id
USER_ID_FROM_LOG = 364551480    # sender.user_id

API_BASE = "https://platform-api2.max.ru"

def test_send(chat_id, method="POST", field="chatId"):
    url = f"{API_BASE}/messages"
    headers = {
        'Authorization': TOKEN,
        'Content-Type': 'application/json'
    }
    if field == "chatId":
        payload = {"chatId": str(chat_id), "text": f"Тест: chatId={chat_id}"}
    elif field == "chat_id":
        payload = {"chat_id": str(chat_id), "text": f"Тест: chat_id={chat_id}"}
    elif field == "recipient":
        payload = {"recipient": {"chat_id": str(chat_id)}, "text": f"Тест: recipient.chat_id={chat_id}"}
    elif field == "user_id":
        payload = {"user_id": str(chat_id), "text": f"Тест: user_id={chat_id}"}
    else:
        return False
    
    print(f"📤 Тест: {method} {url} field={field} value={chat_id}")
    try:
        if method == "POST":
            resp = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        else:
            resp = requests.get(url, params=payload, headers=headers, timeout=10, verify=False)
        
        if resp.status_code == 200:
            print(f"✅ УСПЕШНО! chat_id={chat_id}, field={field}")
            return True
        else:
            print(f"❌ Ошибка: {resp.status_code} - {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"⚠️ Исключение: {e}")
        return False

print("="*60)
print("ПРОВЕРКА ОТПРАВКИ СООБЩЕНИЙ")
print("="*60)

# Перебираем все комбинации
ids = [CHAT_ID_FROM_LOG, USER_ID_FROM_LOG]
fields = ["chatId", "chat_id", "recipient", "user_id"]

for id_val in ids:
    for field in fields:
        if test_send(id_val, "POST", field):
            print(f"\n🎉 РАБОЧАЯ КОМБИНАЦИЯ: recipient_id={id_val}, field={field}")
            print(f"Используйте в коде: send_message({id_val}, text)")
            exit(0)

print("\n❌ Ни одна комбинация не сработала.")
print("Попробуйте проверить, что бот активен и пользователь писал ему первым.")
