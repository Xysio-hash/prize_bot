import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import config
from database import Database
from aiohttp import web

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = Database()

# Простая клавиатура
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎫 Мои билеты"))
    builder.add(KeyboardButton(text="📊 Топ недели"))
    builder.add(KeyboardButton(text="🔗 Пригласить друга"))
    builder.add(KeyboardButton(text="🏆 О розыгрыше"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    
    db.add_user(user_id, username, first_name)
    
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"✅ Бот работает!\n"
        f"Нажимай кнопки 👇",
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "🎫 Мои билеты")
async def my_tickets(message: Message):
    stats = db.get_user_stats(message.from_user.id)
    await message.answer(
        f"🎫 Билеты: {stats['tickets']}\n"
        f"👥 Друзей: {stats['invites']}"
    )

@dp.message(lambda message: message.text == "📊 Топ недели")
async def top_week(message: Message):
    top_users = db.get_top_users(5)
    if not top_users:
        await message.answer("Пока нет участников")
        return
    
    text = "🏆 Топ 5:\n"
    for i, user in enumerate(top_users, 1):
        name = user[2] or f"User{user[0]}"
        text += f"{i}. {name} — {user[4]} билетов\n"
    await message.answer(text)

@dp.message(lambda message: message.text == "🔗 Пригласить друга")
async def invite_friend(message: Message):
    bot_username = (await bot.me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{message.from_user.id}"
    await message.answer(
        f"🔗 Твоя ссылка:\n`{ref_link}`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(lambda message: message.text == "🏆 О розыгрыше")
async def about_prize(message: Message):
    await message.answer(f"🏆 Приз: {config.WEEKLY_PRIZE}")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', lambda request: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    logging.info("Server started")

async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
