import os
import logging
import sqlite3
from datetime import datetime
from maxo import Bot, Dispatcher
from maxo.types import MessageCreated

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
API_BASE = "https://platform-api2.max.ru"  # Не используется напрямую, но оставляем для ясности
TOKEN = os.getenv("MAX_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    TOKEN = "f9LHodD0cOJO_JQ3Fnv3sJhDo51UNGWi8RuOQuHkTuCgmlRHNseHKzURvnyoIcCt1caQpNsYzMZJY3aQLoG9"
    logger.warning("⚠️ Токен взят из кода. На хостинге задайте MAX_BOT_TOKEN!")

ADMIN_IDS = [364551480]   # Ваш user_id
DB_PATH = "news.db"

# =========================================================
# 3. БАЗА ДАННЫХ
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
# 4. ФУНКЦИИ РАБОТЫ С БД
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
# 5. ХРАНИЛИЩЕ СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЕЙ (FSM)
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
# 6. ВОПРОСЫ ДЛЯ ОПРОСА
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
# 7. ИНИЦИАЛИЗАЦИЯ БОТА
# =========================================================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# =========================================================
# 8. ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ
# =========================================================
@dp.message_created()
async def handle_message(message: MessageCreated):
    user_id = message.sender.user_id
    chat_id = message.recipient.chat_id
    text = message.text.strip() if message.text else ""

    if not text:
        return

    logger.info(f"📩 Получено сообщение от {user_id}: {text[:50]}")

    # === ОБРАБОТКА КОМАНД ===
    if text.startswith('/'):
        parts = text.split(maxsplit=2)
        command = parts[0].lower()
        is_admin = user_id in ADMIN_IDS

        if command == '/help':
            await message.answer(
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
            await message.answer(
                "👋 Привет! Я бот для подачи новостей.\n"
                "Чтобы начать, отправьте /news\n"
                "Для справки используйте /help"
            )
            return

        elif command == '/id':
            await message.answer(f"Ваш ID: {user_id}")
            return

        elif command == '/cancel':
            if get_user_state(user_id) is not None:
                clear_user_state(user_id)
                await message.answer("✅ Заявка отменена.")
            else:
                await message.answer("Нет активной заявки.")
            return

        elif command == '/news':
            if get_user_state(user_id) is not None:
                await message.answer("У вас уже есть активная заявка. Используйте /cancel, чтобы отменить её.")
                return
            set_user_state(user_id, 0)
            await message.answer(QUESTIONS[0][1])
            return

        elif command == '/pending':
            if not is_admin:
                await message.answer("⛔ Нет прав.")
                return
            rows = get_pending_applications()
            if not rows:
                await message.answer("Нет заявок.")
                return
            msg = "📋 Ожидающие заявки:\n\n"
            for row in rows:
                msg += f"ID: {row[0]}, Имя: {row[2]}, Время: {row[-1]}\n"
            await message.answer(msg)
            return

        elif command == '/approve':
            if not is_admin:
                await message.answer("⛔ Нет прав.")
                return
            if len(parts) < 2:
                await message.answer("Использование: /approve <id> [комментарий]")
                return
            try:
                app_id = int(parts[1])
            except ValueError:
                await message.answer("ID должен быть числом.")
                return
            feedback = parts[2] if len(parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                await message.answer(f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                await message.answer(f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'approved', feedback)
            await message.answer(f"✅ Заявка #{app_id} одобрена.")
            # Уведомляем автора
            try:
                await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} одобрена. Комментарий: {feedback if feedback else 'нет'}")
            except:
                pass
            return

        elif command == '/reject':
            if not is_admin:
                await message.answer("⛔ Нет прав.")
                return
            if len(parts) < 2:
                await message.answer("Использование: /reject <id> [комментарий]")
                return
            try:
                app_id = int(parts[1])
            except ValueError:
                await message.answer("ID должен быть числом.")
                return
            feedback = parts[2] if len(parts) > 2 else ""
            app = get_application_by_id(app_id)
            if not app:
                await message.answer(f"Заявка #{app_id} не найдена.")
                return
            if app[8] != 'pending':
                await message.answer(f"Заявка уже обработана (статус: {app[8]}).")
                return
            update_status(app_id, 'rejected', feedback)
            await message.answer(f"❌ Заявка #{app_id} отклонена.")
            try:
                await bot.send_message(chat_id=int(app[1]), text=f"Ваша заявка #{app_id} отклонена. Причина: {feedback if feedback else 'не указана'}")
            except:
                pass
            return

        elif command == '/stats':
            if not is_admin:
                await message.answer("⛔ Нет прав.")
                return
            total, pending, approved, rejected = get_stats()
            await message.answer(
                f"📊 Статистика:\nВсего: {total}\nОжидают: {pending}\nОдобрено: {approved}\nОтклонено: {rejected}"
            )
            return

        else:
            await message.answer("Неизвестная команда. Используйте /help для справки.")
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
            await message.answer("✅ Заявка успешно отправлена на модерацию!")

            # Уведомление админам
            admin_text = (
                f"📢 Новая заявка #{app_id}\n"
                f"От пользователя: {data.get('full_name', 'не указано')}\n"
                f"Суть: {data.get('action_desc', 'не указано')}\n"
                f"Польза: {data.get('benefit', 'не указано')}\n"
                f"Как пришёл: {data.get('how_came', 'не указано')}\n"
                f"Место/время: {data.get('place_time', 'не указано')}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=admin_id, text=admin_text)
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
            return
        elif text.lower() == "нет":
            clear_user_state(user_id)
            await message.answer("❌ Заявка отменена.")
            return
        else:
            await message.answer('Пожалуйста, ответьте "Да" или "Нет".')
            return

    if step < TOTAL_QUESTIONS:
        field = QUESTIONS[step][0]
        data[field] = text
        next_step = step + 1
        if next_step < TOTAL_QUESTIONS:
            set_user_state(user_id, next_step, data)
            await message.answer(QUESTIONS[next_step][1])
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
            await message.answer(summary)

# =========================================================
# 9. ЗАПУСК
# =========================================================
if __name__ == "__main__":
    logger.info("🚀 Бот запущен...")
    dp.run_polling(bot)
