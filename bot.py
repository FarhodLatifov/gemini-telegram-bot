import os
from dotenv import load_dotenv
import asyncio
import logging
import aiohttp
import random
import aiosqlite  # Импортируем библиотеку для асинхронной работы с SQLite
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatAction

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

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Функции для работы с БД ---
async def create_database():
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                message TEXT
            )
        ''')
        await conn.commit()

async def save_user_request(user_id, message):
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        
        # Проверяем на дубликаты
        await cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = ? AND message = ?", (user_id, message))
        if (await cursor.fetchone())[0] > 0:
            return  # Сообщение уже сохранено
        
        await cursor.execute("INSERT INTO users (user_id, message) VALUES (?, ?)", (user_id, message))
        await conn.commit()

async def get_users_count():
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users")
        return (await cursor.fetchone())[0]

# --- Функция запроса к Gemini ---
async def get_gemini_response(message_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": message_text}]}]}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                response.raise_for_status()  # Проверка на ошибки HTTP
                result = await response.json()

                if 'candidates' in result and result['candidates']:
                    return result['candidates'][0]['content']['parts'][0]['text']
                return "Gemini не дал ответа."
                
    except aiohttp.ClientError as e:
        logging.error(f"Ошибка при запросе к Gemini API: {e}")
        return "Ошибка запроса к Gemini API. Пожалуйста, попробуйте позже."
        
    except asyncio.TimeoutError:
        logging.error("Время ожидания запроса к Gemini API истекло.")
        return "Запрос к Gemini API занял слишком много времени. Попробуйте еще раз."
        
    except Exception as e:
        logging.exception("Необработанная ошибка при получении ответа Gemini:")
        return "Произошла ошибка при обработке вашего запроса."

# --- Логирование действий пользователей (функция) ---
def log_user_action(user_id, action):
    logging.info(f"Пользователь {user_id} выполнил действие: {action}")

# --- Обработчики команд ---
@dp.message(Command(commands=["start", "help"]))
async def handle_commands(message: Message):
    command = message.text.lower()
    log_user_action(message.from_user.id, command)  # Логируем действие пользователя

    if command == "/start":
        user_first_name = message.from_user.first_name or "пользователь"
        await message.answer(f"Добро пожаловать, {user_first_name}! Чем могу вам помоч?")
        
    elif command == "/help":
        await message.answer(
            "Я бот, который отвечает на ваши вопросы с помощью Gemini Pro.\n\n"
            "Доступные команды:\n"
            "/start - Начать диалог\n"
            "/help - Помощь\n"
        )
        
# --- Обработчик для кнопки "Задать вопрос" ---
@dp.message(F.text == "Задать вопрос")
async def ask_question(message: Message):
    await message.answer("Пожалуйста, задайте ваш вопрос.")

# --- Обработчик текстовых сообщений ---
@dp.message(F.text)
async def handle_message(message: Message):
    if message.text.lower() == "задать вопрос":
        await ask_question(message)
        return
    
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)  # Отправляем индикатор "печатает"
        
        await save_user_request(message.from_user.id, message.text)
        
        reply = await get_gemini_response(message.text)
        
        await message.reply(reply)
        
    except Exception as e:
        logging.exception("Необработанная ошибка при обработке сообщения:")
        await message.answer(f"Произошла ошибка при обработке запроса: {e}")


# --- Запуск бота ---
async def main():
   await create_database()  # Создаем БД при запуске
   print("Бот запущен!")
   try:
       await dp.start_polling(bot)
   finally:
       await bot.session.close()  # Закрываем сессию бота

if __name__ == "__main__":
   asyncio.run(main())
