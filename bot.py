import os
import uvicorn
from dotenv import load_dotenv
import asyncio
import logging
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ChatAction
from fastapi import FastAPI
from contextlib import asynccontextmanager

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = os.getenv("OWNER_ID")
DB_FILE = "users_data.db"

# --- Проверка наличия токенов ---
if not BOT_TOKEN:
    raise ValueError("Необходимо установить переменную окружения BOT_TOKEN")
if not GEMINI_API_KEY:
    raise ValueError("Необходимо установить переменную окружения GEMINI_API_KEY")

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Инициализация объектов ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Lifespan менеджер для FastAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация базы данных
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.commit()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.critical(f"Ошибка инициализации БД: {e}")
        raise

    # Запуск бота в фоновом режиме
    asyncio.create_task(start_bot())
    yield

    # Завершение работы
    await bot.session.close()
    logger.info("Приложение корректно завершает работу")

app = FastAPI(lifespan=lifespan)

# --- Функции для работы с БД ---
async def save_user_request(user_id, message):
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute(
                "INSERT INTO users (user_id, message) VALUES (?, ?)",
                (user_id, message)
            )
            await conn.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")

async def get_users_count():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM users")
            return (await cursor.fetchone())[0]
    except Exception as e:
        logger.error(f"Ошибка получения данных: {e}")
        return 0

# --- Функция запроса к Gemini ---
async def get_gemini_response(message_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": message_text}]}]}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                return result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', "Не удалось получить ответ")
    except Exception as e:
        logger.error(f"Ошибка Gemini API: {str(e)}")
        return "Извините, произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."

# --- Обработчики команд ---
@dp.message(Command(commands=["start", "help"]))
async def handle_commands(message: Message):
    try:
        command = message.text.split()[0].lower()
        logger.info(f"User {message.from_user.id} executed {command}")
        
        if command == "/start":
            await message.answer(f"Добро пожаловать, {message.from_user.first_name}! Чем могу помочь?")
        elif command == "/help":
            await message.answer(
                "🤖 Я бот с интеграцией Gemini Pro\n\n"
                "Доступные команды:\n"
                "/start - Начало работы\n"
                "/help - Это сообщение\n"
                "/stats - Статистика пользователей"
            )
    except Exception as e:
        logger.error(f"Ошибка обработки команды: {e}")

# --- Обработчик текстовых сообщений ---
@dp.message(F.text)
async def handle_message(message: Message):
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await save_user_request(message.from_user.id, message.text)
        response = await get_gemini_response(message.text)
        await message.reply(response)
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await message.answer("⚠️ Произошла ошибка при обработке вашего запроса")

# --- FastAPI Endpoints ---
@app.get("/")
async def health_check():
    return {
        "status": "running",
        "users": await get_users_count()
    }

# --- Запуск бота ---
async def start_bot():
    try:
        logger.info("Запуск бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Фатальная ошибка бота: {e}")
        await bot.session.close()
        os._exit(1)

if __name__ == "__main__":
    uvicorn.run(
        app="bot:app",  # Убедитесь что имя файла совпадает (если файл называется run.py, укажите "run:app")
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )
