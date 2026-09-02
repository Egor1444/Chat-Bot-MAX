import os
import uuid
import logging
import sqlite3
import urllib.request
import ssl
from datetime import datetime
from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart, Command

# =========================================================
# 1. НАСТРОЙКА ЛОГИРОВАНИЯ
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================================================
# 2. КОНФИГУРАЦИЯ
# =========================================================
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]
logger.info(f"🔑 Администраторы: {ADMIN_IDS}")

DB_PATH = "news.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================================================
# 3. ХРАНИЛИЩЕ CHAT_ID АДМИНОВ
# =========================================================
admin_chat_ids = {}

# =========================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================
def get_user_id(event):
    if hasattr(event, 'from_user'):
        if hasattr(event.from_user, 'user_id'):
            return event.from_user.user_id
        if hasattr(event.from_user, 'id'):
            return event.from_user.id
    if hasattr(event, 'sender') and hasattr(event.sender, 'user_id'):
        return event.sender.user_id
    if hasattr(event, 'user') and hasattr(event.user, 'id'):
        return event.user.id
    return None

def get_chat_id(event):
    if hasattr(event, 'recipient') and hasattr(event.recipient, 'chat_id'):
        return event.recipient.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'chat_id'):
        return event.message.chat_id
    if hasattr(event, 'chat_id'):
        return event.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient'):
        return event.message.recipient.chat_id
    logger.error("Не удалось найти chat_id")
    return None

# =========================================================
# 5. БАЗА ДАННЫХ
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
            file_path TEXT,
            status TEXT DEFAULT 'pending',
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_application(user_id, data, file_path=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO news 
        (user_id, full_name, action_desc, benefit, how_came, place_time, content, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        str(user_id),
        data.get('full_name', ''),
        data.get('action_desc', ''),
        data.get('benefit', ''),
        data.get('how_came', ''),
        data.get('place_time', ''),
        data.get('content', ''),
        file_path
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
    pending = c.execute("SELECT COUNT(*) FROM news WHERE status = 'pending'").fetchone()[0]
    approved = c.execute("SELECT COUNT(*) FROM news WHERE status = 'approved'").fetchone()[0]
    rejected = c.execute("SELECT COUNT(*) FROM news WHERE status = 'rejected'").fetchone()[0]
    conn.close()
    return total, pending, approved, rejected

# =========================================================
# 6. СОСТОЯНИЯ
# =========================================================
user_states = {}

def get_user_state(user_id):
    return user_states.get(str(user_id))

def set_user_state(user_id, step, data=None):
    if data is None:
        data = {}
    user_states[str(user_id)] = {'step': step, 'data': data}
    logger.info(f"🧠 Состояние для {user_id} установлено на шаг {step}")

def clear_user_state(user_id):
    if user_id in user_states:
        del user_states[str(user_id)]
        logger.info(f"🧹 Состояние для {user_id} очищено")
    else:
        logger.warning(f"⚠️ Попытка очистить несуществующее состояние для {user_id}")

# =========================================================
# 7. ВОПРОСЫ (с комментарием)
# =========================================================
QUESTIONS = [
    ('full_name', 'Расскажите о себе: ваше полное имя, должность или роль в проекте.'),
    ('action_desc', 'Опишите событие или действие, о котором хотите сообщить. Что именно произошло?'),
    ('benefit', 'Какую пользу или ценность эта новость принесёт аудитории?'),
    ('how_came', 'Как вы пришли к этому? Какие обстоятельства или предпосылки к этому привели?'),
    ('place_time', 'Где и когда произошло событие? Укажите место и дату (город, площадка, время).'),
    ('content', 'Если хотите, добавьте комментарий или дополнительную информацию (можно пропустить, отправьте «—»).')
]
FILE_STEP = len(QUESTIONS)  # теперь 6

# =========================================================
# 8. ФУНКЦИЯ ПОЛУЧЕНИЯ И СОХРАНЕНИЯ ФАЙЛА
# =========================================================
def get_file_from_event(event):
    msg = event.message
    for attr in ['photo', 'document', 'file', 'attachment', 'media']:
        if hasattr(msg, attr):
            val = getattr(msg, attr)
            if val:
                logger.info(f"✅ Найден файл в поле {attr}: {val}")
                return val
    if hasattr(msg, 'body'):
        body = msg.body
        if hasattr(body, 'attachments') and body.attachments:
            logger.info(f"✅ Найден файл в body.attachments: {body.attachments}")
            return body.attachments[0] if isinstance(body.attachments, list) else body.attachments
        if hasattr(body, 'file'):
            logger.info(f"✅ Найден файл в body.file: {body.file}")
            return body.file
        if hasattr(body, 'photo'):
            logger.info(f"✅ Найден файл в body.photo: {body.photo}")
            return body.photo
        if hasattr(body, 'document'):
            logger.info(f"✅ Найден файл в body.document: {body.document}")
            return body.document
    logger.warning("❌ Файл не найден в сообщении")
    return None

def save_file(file_obj):
    name = getattr(file_obj, 'filename', None) or getattr(file_obj, 'name', None) or getattr(file_obj, 'file_name', None) or 'file'
    ext = name.split('.')[-1] if '.' in name else ''
    filename = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    if hasattr(file_obj, 'download'):
        try:
            file_obj.download(file_path)
            return file_path
        except Exception as e:
            logger.error(f"Ошибка download: {e}")

    if hasattr(file_obj, 'payload') and hasattr(file_obj.payload, 'url'):
        url = file_obj.payload.url
        try:
            ssl_context = ssl._create_unverified_context()
            with urllib.request.urlopen(url, context=ssl_context) as response:
                with open(file_path, 'wb') as f:
                    f.write(response.read())
            logger.info(f"📎 Файл скачан по URL: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Ошибка скачивания по URL: {e}")

    if hasattr(file_obj, 'file_id'):
        return str(file_obj.file_id)
    return name

# =========================================================
# 9. ОТПРАВКА ФАЙЛА АДМИНУ (через send_file)
# =========================================================
async def send_file_to_admin(file_path, caption):
    for admin_id in ADMIN_IDS:
        chat_id = admin_chat_ids.get(admin_id)
        if not chat_id:
            logger.warning(f"⚠️ Chat_id для администратора {admin_id} не найден, пропускаем отправку файла.")
            continue
        try:
            # Пытаемся отправить файл с помощью send_file (если метод существует)
            if hasattr(bot, 'send_file'):
                await bot.send_file(chat_id=chat_id, file=file_path, caption=caption)
            else:
                # Fallback: отправляем только текст с путём
                await bot.send_message(chat_id=chat_id, text=caption + f"\nФайл: {file_path}")
            logger.info(f"📎 Файл отправлен админу {admin_id} (chat_id={chat_id})")
        except Exception as e:
            logger.error(f"Ошибка отправки файла админу {admin_id}: {e}")
            try:
                await bot.send_message(chat_id=chat_id, text=caption + f"\nФайл: {file_path}")
            except:
                pass

# =========================================================
# 10. БОТ
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 11. КОМАНДЫ
# =========================================================
@dp.message_created(CommandStart())
async def cmd_start(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    clear_user_state(str(user_id))
    await bot.send_message(chat_id=chat_id,
        text="👋 Привет! Я бот для подачи новостей.\n"
             "Чтобы начать, отправьте /news\n"
             "Для справки используйте /help"
    )

@dp.message_created(Command(commands=['help']))
async def cmd_help(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    await bot.send_message(chat_id=chat_id,
        text="📖 Доступные команды:\n"
             "/start — начать работу\n"
             "/news — подать новость\n"
             "/cancel — отменить текущую заявку\n"
             "/id — показать ваш ID\n\n"
             "Для администраторов:\n"
             "/pending — список заявок\n"
             "/approve <id> [комментарий] — одобрить\n"
             "/reject <id> [комментарий] — отклонить\n"
             "/stats — статистика\n"
             "/view <id> — просмотреть заявку"
    )

@dp.message_created(Command(commands=['id']))
async def cmd_id(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    await bot.send_message(chat_id=chat_id, text=f"Ваш ID: {user_id}")

@dp.message_created(Command(commands=['cancel']))
async def cmd_cancel(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    if get_user_state(user_id_str) is not None:
        clear_user_state(user_id_str)
        await bot.send_message(chat_id=chat_id, text="✅ Заявка отменена.")
    else:
        await bot.send_message(chat_id=chat_id, text="Нет активной заявки для отмены.")

@dp.message_created(Command(commands=['news']))
async def cmd_news(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    user_id_str = str(user_id)
    clear_user_state(user_id_str)
    set_user_state(user_id_str, 0)
    await bot.send_message(chat_id=chat_id, text=QUESTIONS[0][1])

# =========================================================
# 12. АДМИН-КОМАНДЫ
# =========================================================
@dp.message_created(Command(commands=['pending']))
async def cmd_pending(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    rows = get_pending_applications()
    if not rows:
        await bot.send_message(chat_id=chat_id, text="Нет заявок.")
        return
    msg = "📋 Ожидающие заявки:\n\n"
    for row in rows:
        msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
    await bot.send_message(chat_id=chat_id, text=msg)

@dp.message_created(Command(commands=['view']))
async def cmd_view(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    args = event.message.body.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /view <id>")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return
    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return
    text = (
        f"📄 Заявка #{app_id}\n"
        f"Пользователь: {app[2]}\n"
        f"Суть: {app[3]}\n"
        f"Польза: {app[4]}\n"
        f"Как пришёл: {app[5]}\n"
        f"Место/время: {app[6]}\n"
    )
    if app[7]:
        text += f"Комментарий: {app[7]}\n"
    text += f"Статус: {app[9]}\nСоздана: {app[-1]}"
    if app[8] and os.path.exists(app[8]):
        try:
            if hasattr(bot, 'send_file'):
                await bot.send_file(chat_id=chat_id, file=app[8], caption=text)
            else:
                await bot.send_message(chat_id=chat_id, text=text + f"\nФайл: {app[8]}")
            return
        except Exception as e:
            logger.error(f"Ошибка отправки файла при просмотре: {e}")
            await bot.send_message(chat_id=chat_id, text=text + f"\nФайл: {app[8]}")
    else:
        await bot.send_message(chat_id=chat_id, text=text)

@dp.message_created(Command(commands=['approve']))
async def cmd_approve(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /approve <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await bot.send_message(chat_id=chat_id, text=f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'approved', feedback)
    await bot.send_message(chat_id=chat_id, text=f"✅ Заявка #{app_id} одобрена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
    except:
        pass

@dp.message_created(Command(commands=['reject']))
async def cmd_reject(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    args = event.message.body.text.split(maxsplit=2)
    if len(args) < 2:
        await bot.send_message(chat_id=chat_id, text="Использование: /reject <id> [комментарий]")
        return
    try:
        app_id = int(args[1])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="ID должен быть числом.")
        return
    feedback = args[2] if len(args) > 2 else ""
    app = get_application_by_id(app_id)
    if not app:
        await bot.send_message(chat_id=chat_id, text=f"Заявка #{app_id} не найдена.")
        return
    if app[9] != 'pending':
        await bot.send_message(chat_id=chat_id, text=f"Заявка уже обработана (статус: {app[9]}).")
        return
    update_status(app_id, 'rejected', feedback)
    await bot.send_message(chat_id=chat_id, text=f"❌ Заявка #{app_id} отклонена.")
    try:
        await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
    except:
        pass

@dp.message_created(Command(commands=['stats']))
async def cmd_stats(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        await bot.send_message(chat_id=chat_id, text="Ошибка: не удалось определить ваш ID.")
        return
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id=chat_id, text="⛔ Нет прав.")
        return
    total, pending, approved, rejected = get_stats()
    await bot.send_message(chat_id=chat_id,
        text=f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
    )

# =========================================================
# 13. ОСНОВНОЙ ОБРАБОТЧИК
# =========================================================
@dp.message_created()
async def handle_message(event):
    chat_id = get_chat_id(event)
    if chat_id is None:
        return
    user_id = get_user_id(event)
    if user_id is None:
        return
    user_id_str = str(user_id)

    if user_id in ADMIN_IDS:
        admin_chat_ids[user_id] = chat_id
        logger.info(f"👤 Сохранён chat_id для администратора {user_id}: {chat_id}")

    state = get_user_state(user_id_str)
    if state is None:
        logger.info(f"🔄 Сообщение от {user_id_str} вне опроса")
        return

    step = state['step']
    data = state['data']

    # --- ШАГ 6: ФАЙЛ ---
    if step == FILE_STEP:
        logger.info(f"📂 Обработка шага файла для {user_id_str}")
        file_obj = get_file_from_event(event)
        file_path = None

        if file_obj is not None:
            try:
                file_path = save_file(file_obj)
                data['file_path'] = file_path
                logger.info(f"📎 Файл сохранён: {file_path}")
            except Exception as e:
                logger.error(f"Ошибка сохранения файла: {e}")
                await bot.send_message(chat_id=chat_id, text="Не удалось сохранить файл. Попробуйте ещё раз.")
                return
        else:
            if hasattr(event.message, 'body') and hasattr(event.message.body, 'text'):
                text = event.message.body.text.strip().lower()
                if text == "пропустить" or text == "—":
                    data['file_path'] = None
                    logger.info("📎 Файл пропущен")
                else:
                    await bot.send_message(chat_id=chat_id,
                        text="Пожалуйста, прикрепите фото (или документ) или напишите «Пропустить».")
                    return
            else:
                await bot.send_message(chat_id=chat_id,
                    text="Пожалуйста, прикрепите фото (или документ) или напишите «Пропустить».")
                return

        app_id = save_application(user_id_str, data, data.get('file_path'))
        clear_user_state(user_id_str)
        await bot.send_message(chat_id=chat_id, text="✅ Заявка успешно отправлена на модерацию!")

        admin_text = (
            f"📢 Новая заявка #{app_id}\n"
            f"От пользователя: {data.get('full_name', 'не указано')}\n"
            f"Суть: {data.get('action_desc', 'не указано')}\n"
            f"Польза: {data.get('benefit', 'не указано')}\n"
            f"Как пришёл: {data.get('how_came', 'не указано')}\n"
            f"Место/время: {data.get('place_time', 'не указано')}"
        )
        if data.get('content'):
            admin_text += f"\nКомментарий: {data['content']}"

        if data.get('file_path') and os.path.exists(data['file_path']):
            await send_file_to_admin(data['file_path'], admin_text)
        else:
            for admin_id in ADMIN_IDS:
                chat_id_admin = admin_chat_ids.get(admin_id)
                if chat_id_admin:
                    try:
                        await bot.send_message(chat_id=chat_id_admin, text=admin_text)
                    except Exception as e:
                        logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
                else:
                    logger.warning(f"⚠️ Chat_id для админа {admin_id} не найден, пропускаем уведомление.")
        return

    # --- ШАГИ 0-5: ВОПРОСЫ ---
    if step < FILE_STEP:
        if not hasattr(event.message, 'body') or not hasattr(event.message.body, 'text'):
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, отправьте текстовое сообщение.")
            return
        text = event.message.body.text.strip()
        if not text:
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, отправьте текстовое сообщение.")
            return
        # Для комментария разрешаем пустой ответ через "—"
        if step == 5:
            if text == "—":
                text = ""
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < FILE_STEP:
            set_user_state(user_id_str, next_step, data)
            await bot.send_message(chat_id=chat_id, text=QUESTIONS[next_step][1])
        else:
            set_user_state(user_id_str, FILE_STEP, data)
            await bot.send_message(chat_id=chat_id,
                text="Прикрепите фото, подтверждающее событие (если есть). Напишите «Пропустить», чтобы пропустить.")
        return

    logger.warning(f"⚠️ Неизвестное состояние {step} для {user_id_str}")

# =========================================================
# 14. ЗАПУСК
# =========================================================
async def main():
    logger.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
