import logging
import asyncio
import random
import string
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import config
from database import Database
import random
from aiohttp import web
from datetime import datetime, timedelta

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = Database()

# Константа с именем канала
CHANNEL_USERNAME = "@colizeum_kp67"  # Ваш канал

# Хранилище для временных кодов подтверждения
# Структура: {friend_id: {"referrer_id": id, "code": "ABC123", "expires": timestamp}}
pending_confirmations = {}

# Функция генерации случайного кода
def generate_confirmation_code(length=6):
    """Генерирует случайный код из букв и цифр"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# Функция проверки подписки
async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Ошибка проверки подписки для {user_id}: {e}")
        return False

# Клавиатура главного меню
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎫 Мои билеты"))
    builder.add(KeyboardButton(text="📊 Топ недели"))
    builder.add(KeyboardButton(text="🔗 Пригласить друга"))
    builder.add(KeyboardButton(text="🏆 О розыгрыше"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# Клавиатура для проверки подписки
def get_subscription_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/colizeum_kp67")],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
        ]
    )
    return keyboard

# Команда /start
@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    
    # Добавляем пользователя в БД в любом случае
    db.add_user(user_id, username, first_name)
    
    # Проверяем, есть ли реферальный параметр (кто пригласил)
    args = message.text.split()
    referrer_id = None
    
    if len(args) > 1 and args[1].startswith('ref'):
        try:
            referrer_id = int(args[1].replace('ref', ''))
            if referrer_id == user_id:
                referrer_id = None
        except:
            referrer_id = None
    
    # Проверка подписки на канал
    is_subscribed = await check_subscription(user_id)
    
    if not is_subscribed:
        # Если не подписан - просим подписаться
        await message.answer(
            f"👋 Привет, {first_name}!\n\n"
            f"Для доступа к розыгрышу нужно подписаться на наш канал:\n"
            f"{CHANNEL_USERNAME}\n\n"
            f"После подписки нажмите кнопку 'Я подписался' 👇",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Если есть пригласивший И пользователь подписан
    if referrer_id:
        # Проверяем, существует ли пригласивший
        if db.get_referrer_by_start_param(referrer_id):
            # Генерируем код подтверждения
            confirm_code = generate_confirmation_code()
            expires_at = datetime.now() + timedelta(minutes=10)  # Код действует 10 минут
            
            # Сохраняем во временное хранилище
            pending_confirmations[user_id] = {
                "referrer_id": referrer_id,
                "code": confirm_code,
                "expires": expires_at
            }
            
            # Создаем клавиатуру с кнопкой подтверждения
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"🔑 Подтвердить код: {confirm_code}", callback_data=f"confirm_{confirm_code}")]
                ]
            )
            
            await message.answer(
                f"🔐 **Подтверждение приглашения**\n\n"
                f"Вы перешли по приглашению друга!\n"
                f"Чтобы приглашение засчиталось, нажмите кнопку ниже:\n\n"
                f"Код: `{confirm_code}`\n\n"
                f"⚠️ Код действителен 10 минут",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return  # Не даем доступ, пока не подтвердит
    
    # Если нет пригласившего ИЛИ пригласивший не существует
    welcome_text = (
        f"👋 Привет, {first_name}!\n\n"
        f"🎲 Каждую неделю мы разыгрываем призы!\n"
        f"💰 Текущий приз: {config.WEEKLY_PRIZE}\n\n"
        f"Как получить билеты:\n"
        f"• 1 друг = 1 билет\n"
        f"• 5 друзей = +1 бонусный билет\n"
        f"• 10 друзей = +2 бонусных билета\n\n"
        f"Чем больше друзей, тем выше шанс!"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# Обработчик подтверждения по коду
@dp.callback_query(lambda c: c.data and c.data.startswith('confirm_'))
async def confirm_referral_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    received_code = callback_query.data.replace('confirm_', '')
    
    # Проверяем, есть ли ожидающее подтверждение
    if user_id not in pending_confirmations:
        await callback_query.answer(
            "❌ Срок действия кода истек или он уже использован.",
            show_alert=True
        )
        await callback_query.message.edit_text(
            "❌ Код подтверждения недействителен. Попробуйте перейти по ссылке заново."
        )
        return
    
    confirm_data = pending_confirmations[user_id]
    
    # Проверяем срок действия
    if datetime.now() > confirm_data["expires"]:
        del pending_confirmations[user_id]
        await callback_query.answer(
            "❌ Время действия кода истекло (10 минут). Перейдите по ссылке заново.",
            show_alert=True
        )
        await callback_query.message.edit_text(
            "❌ Время действия кода истекло. Попробуйте перейти по ссылке заново."
        )
        return
    
    # Проверяем код
    if received_code != confirm_data["code"]:
        await callback_query.answer(
            "❌ Неверный код подтверждения.",
            show_alert=True
        )
        return
    
    # Всё хорошо - добавляем реферала
    referrer_id = confirm_data["referrer_id"]
    
    # Проверяем, не был ли этот друг уже приглашен ранее
    db.cursor.execute(
        "SELECT id FROM referrals WHERE friend_id = ?",
        (user_id,)
    )
    if db.cursor.fetchone():
        await callback_query.answer(
            "❌ Вы уже были приглашены ранее.",
            show_alert=True
        )
        await callback_query.message.edit_text(
            "❌ Вы уже зарегистрированы как чей-то друг ранее."
        )
        del pending_confirmations[user_id]
        return
    
    # Добавляем реферала
    success = db.add_referral(referrer_id, user_id)
    
    if success:
        # Удаляем из временного хранилища
        del pending_confirmations[user_id]
        
        # Уведомляем пригласившего
        try:
            friend_name = callback_query.from_user.first_name
            await bot.send_message(
                referrer_id,
                f"🎉 По вашей ссылке зарегистрировался и подтвердил {friend_name}!\n"
                f"Ваши билеты обновлены!"
            )
        except:
            pass
        
        await callback_query.message.edit_text(
            "✅ **Приглашение подтверждено!**\n\n"
            "Теперь вам доступен розыгрыш бонусов!\n"
            "Нажмите /start чтобы начать."
        )
        
        # Отправляем приветствие с меню
        user_info = db.get_user_stats(user_id)
        await callback_query.message.answer(
            f"Добро пожаловать!",
            reply_markup=get_main_keyboard()
        )
    else:
        await callback_query.answer(
            "❌ Ошибка при добавлении приглашения. Возможно, вы уже были приглашены.",
            show_alert=True
        )

# Обработчик кнопки "Я подписался"
@dp.callback_query(lambda c: c.data == "check_sub")
async def check_subscription_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    first_name = callback_query.from_user.first_name
    
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback_query.message.edit_text(
            f"✅ Спасибо за подписку, {first_name}!\n\n"
            f"Теперь вам доступен розыгрыш бонусов!\n"
            f"Нажмите /start, чтобы начать."
        )
        await callback_query.message.answer(
            f"Добро пожаловать!",
            reply_markup=get_main_keyboard()
        )
    else:
        await callback_query.answer(
            "❌ Вы ещё не подписались на канал. Пожалуйста, подпишитесь и нажмите кнопку снова.",
            show_alert=True
        )

# Функция очистки просроченных кодов (запускается периодически)
async def clean_expired_codes():
    while True:
        await asyncio.sleep(60)  # Проверяем каждую минуту
        now = datetime.now()
        expired = [user_id for user_id, data in pending_confirmations.items() 
                  if data["expires"] < now]
        for user_id in expired:
            del pending_confirmations[user_id]
            print(f"Очищен просроченный код для user_id {user_id}")

# --- ВСЕ ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (my_tickets, top_week, invite_friend, copy_link, about_prize, draw_winner) ---
# Они остаются ТОЧНО ТАКИМИ ЖЕ, как в предыдущей версии
# Вставьте сюда код из предыдущего сообщения для функций:
# my_tickets, top_week, invite_friend, copy_link_callback, about_prize, draw_winner

@dp.message(lambda message: message.text == "🎫 Мои билеты")
async def my_tickets(message: Message):
    user_id = message.from_user.id
    
    # Проверка подписки
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    stats = db.get_user_stats(user_id)
    
    week_start = db.get_week_start()
    db.cursor.execute(
        "SELECT SUM(tickets_count) FROM weekly_stats WHERE week_start = ?",
        (week_start,)
    )
    total_tickets = db.cursor.fetchone()[0] or 1
    
    chance = (stats['tickets'] / total_tickets) * 100 if total_tickets > 0 else 0
    
    text = (
        f"🎫 **Ваши билеты**\n\n"
        f"Приглашено друзей: {stats['invites']}\n"
        f"Билетов: {stats['tickets']}\n"
        f"Шанс на победу: {chance:.1f}%\n\n"
        f"🏆 Текущий приз: {config.WEEKLY_PRIZE}"
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(lambda message: message.text == "📊 Топ недели")
async def top_week(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    top_users = db.get_top_users(10)
    
    if not top_users:
        await message.answer("Пока нет участников. Стань первым! 🎯")
        return
    
    text = "🏆 **Топ 10 недели** 🏆\n\n"
    
    for i, user in enumerate(top_users, 1):
        user_id, username, first_name, invites, tickets = user
        name = first_name if first_name else f"User{user_id}"
        
        if i == 1:
            medal = "🥇"
        elif i == 2:
            medal = "🥈"
        elif i == 3:
            medal = "🥉"
        else:
            medal = f"{i}."
        
        text += f"{medal} {name} — {tickets} билетов ({invites} др.)\n"
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(lambda message: message.text == "🔗 Пригласить друга")
async def invite_friend(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    bot_username = (await bot.me()).username
    
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    
    text = (
        "🔗 **Твоя персональная ссылка для приглашения:**\n\n"
        f"`{ref_link}`\n\n"
        "📤 Отправь эту ссылку друзьям\n"
        "👥 Друг должен подтвердить приглашение кнопкой\n"
        "🎁 Чем больше друзей, тем выше шанс!"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📋 Копировать ссылку", callback_data="copy_link")]]
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "copy_link")
async def copy_link_callback(callback_query: CallbackQuery):
    await callback_query.answer(
        text="Ссылка скопирована! Просто выдели и скопируй сообщение выше 👆",
        show_alert=False
    )

@dp.message(lambda message: message.text == "🏆 О розыгрыше")
async def about_prize(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    week_start = db.get_week_start()
    
    db.cursor.execute(
        "SELECT COUNT(DISTINCT user_id), SUM(tickets_count) FROM weekly_stats WHERE week_start = ?",
        (week_start,)
    )
    result = db.cursor.fetchone()
    participants = result[0] or 0
    total_tickets = result[1] or 0
    
    from datetime import datetime, timedelta
    monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    sunday = monday + timedelta(days=6)
    
    text = (
        f"🏆 **О текущем розыгрыше** 🏆\n\n"
        f"💰 Приз: {config.WEEKLY_PRIZE}\n"
        f"👥 Участников: {participants}\n"
        f"🎫 Всего билетов: {total_tickets}\n"
        f"📅 Розыгрыш: {sunday.strftime('%d.%m.%Y')}\n\n"
        f"Победитель будет определен случайно!\n"
        f"Чем больше у тебя билетов, тем выше шанс."
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("draw"))
async def draw_winner(message: Message):
    if message.from_user.id != 1335144671:  # ВАШ TELEGRAM ID
        await message.answer("❌ Эта команда только для администратора")
        return
    
    week_start = db.get_week_start()
    
    db.cursor.execute('''
        SELECT user_id, tickets_count FROM weekly_stats 
        WHERE week_start = ? AND tickets_count > 0
    ''', (week_start,))
    
    participants = db.cursor.fetchall()
    
    if not participants:
        await message.answer("❌ Нет участников с билетами")
        return
    
    tickets_pool = []
    for user_id, tickets_count in participants:
        tickets_pool.extend([user_id] * tickets_count)
    
    winner_id = random.choice(tickets_pool)
    
    db.cursor.execute(
        "SELECT username, first_name FROM users WHERE user_id = ?",
        (winner_id,)
    )
    winner_info = db.cursor.fetchone()
    winner_name = winner_info[1] or f"User{winner_id}"
    
    result_text = (
        f"🎉 **РОЗЫГРЫШ СОСТОЯЛСЯ!** 🎉\n\n"
        f"🏆 Приз: {config.WEEKLY_PRIZE}\n"
        f"👑 Победитель: {winner_name}\n\n"
        f"Поздравляем! 🥳\n\n"
        f"Следующий розыгрыш уже начался!\n"
        f"Приглашай друзей и выигрывай!"
    )
    
    await message.answer(result_text, parse_mode=ParseMode.MARKDOWN)
    
    try:
        await bot.send_message(
            winner_id,
            f"🎉 **ПОЗДРАВЛЯЕМ!** 🎉\n\n"
            f"Ты выиграл(а) в нашем розыгрыше!\n"
            f"💰 Приз: {config.WEEKLY_PRIZE}\n\n"
            f"Свяжись с администратором для получения приза!"
        )
    except:
        pass

# HTTP сервер для Render
async def start_web_server():
    app = web.Application()
    app.router.add_get('/', lambda request: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 10000)
    await site.start()
    logging.info("Keep-alive server started on port 10000")

# Запуск бота
async def main():
    # Запускаем фоновую очистку просроченных кодов
    asyncio.create_task(clean_expired_codes())
    # Запускаем HTTP сервер для Render
    asyncio.create_task(start_web_server())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
