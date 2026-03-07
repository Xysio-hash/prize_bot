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

# Константы
CHANNEL_USERNAME = "@colizeum_kp67"  # Ваш канал
ADMIN_ID = 1335144671  # Ваш Telegram ID

# Хранилище для временных кодов подтверждения
pending_confirmations = {}

# Функция генерации случайного кода
def generate_confirmation_code(length=6):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# Функция проверки подписки
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Ошибка проверки подписки для {user_id}: {e}")
        return False

# Клавиатура главного меню
def get_main_keyboard(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎫 Мои билеты"))
    builder.add(KeyboardButton(text="📊 Топ недели"))
    builder.add(KeyboardButton(text="🔗 Пригласить друга"))
    builder.add(KeyboardButton(text="🏆 О розыгрыше"))
    
    if is_admin:
        builder.add(KeyboardButton(text="⚙️ Админ панель"))
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# Клавиатура админ-панели
def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🏆 Сменить приз", callback_data="admin_change_prize"))
    builder.add(InlineKeyboardButton(text="📋 Список участников", callback_data="admin_users_list"))
    builder.add(InlineKeyboardButton(text="👥 Реферальная сеть", callback_data="admin_referrals"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🎲 Розыгрыш", callback_data="admin_draw"))
    builder.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.adjust(2)  # по 2 кнопки в ряд
    return builder.as_markup()

# Клавиатура для проверки подписки
def get_subscription_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/colizeum_kp67")],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
        ]
    )
    return keyboard

# Функция проверки админа
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# Команда /start
@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    
    # Добавляем пользователя в БД в любом случае
    db.add_user(user_id, username, first_name)
    
    # Проверяем реферальный параметр
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
        await message.answer(
            f"👋 Привет, {first_name}!\n\n"
            f"Для доступа к розыгрышу нужно подписаться на наш канал:\n"
            f"{CHANNEL_USERNAME}\n\n"
            f"После подписки нажмите кнопку 'Я подписался' 👇",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Если есть пригласивший
    if referrer_id:
        if db.get_referrer_by_start_param(referrer_id):
            confirm_code = generate_confirmation_code()
            expires_at = datetime.now() + timedelta(minutes=10)
            
            pending_confirmations[user_id] = {
                "referrer_id": referrer_id,
                "code": confirm_code,
                "expires": expires_at
            }
            
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
            return
    
    # Приветственное сообщение
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
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard(is_admin(user_id)))

# АДМИН-ПАНЕЛЬ
@dp.message(lambda message: message.text == "⚙️ Админ панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав администратора")
        return
    
    text = (
        "⚙️ **Административная панель**\n\n"
        "Выберите действие:"
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_keyboard())

# Смена приза
@dp.callback_query(lambda c: c.data == "admin_change_prize")
async def admin_change_prize(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback_query.message.edit_text(
        "🏆 **Смена приза**\n\n"
        "Отправьте новое название приза одним сообщением.\n"
        "Например: `1000 рублей` или `Наушники`\n\n"
        "Для отмены отправьте /cancel"
    )
    
    # Сохраняем состояние ожидания
    db.cursor.execute(
        "INSERT OR REPLACE INTO admin_states (user_id, state, data) VALUES (?, ?, ?)",
        (callback_query.from_user.id, "waiting_prize", "{}")
    )
    db.conn.commit()
    
    await callback_query.answer()

# Список участников
@dp.callback_query(lambda c: c.data == "admin_users_list")
async def admin_users_list(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    # Получаем всех пользователей
    db.cursor.execute("""
        SELECT user_id, username, first_name, joined_date 
        FROM users 
        ORDER BY joined_date DESC 
        LIMIT 50
    """)
    users = db.cursor.fetchall()
    
    text = f"📋 **Последние 50 участников:**\n\n"
    for i, user in enumerate(users, 1):
        user_id, username, first_name, joined_date = user
        name = first_name if first_name else f"User{user_id}"
        username_str = f"(@{username})" if username and username != "NoUsername" else ""
        text += f"{i}. {name} {username_str} - {joined_date}\n"
    
    # Кнопка для экспорта
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Экспорт в CSV", callback_data="admin_export_users")]
        ]
    )
    
    await callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    await callback_query.answer()

# Реферальная сеть
@dp.callback_query(lambda c: c.data == "admin_referrals")
async def admin_referrals(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    # Статистика по рефералам
    db.cursor.execute("""
        SELECT 
            COUNT(DISTINCT referrer_id) as total_referrers,
            COUNT(*) as total_referrals
        FROM referrals
    """)
    stats = db.cursor.fetchone()
    
    # Топ приглашающих
    db.cursor.execute("""
        SELECT users.user_id, users.first_name, users.username, COUNT(*) as invites
        FROM referrals
        JOIN users ON referrals.referrer_id = users.user_id
        GROUP BY referrals.referrer_id
        ORDER BY invites DESC
        LIMIT 10
    """)
    top_referrers = db.cursor.fetchall()
    
    text = (
        f"👥 **Реферальная статистика**\n\n"
        f"Всего приглашающих: {stats[0]}\n"
        f"Всего приглашений: {stats[1]}\n\n"
        f"🏆 **Топ приглашающих:**\n"
    )
    
    for i, user in enumerate(top_referrers, 1):
        user_id, first_name, username, invites = user
        name = first_name if first_name else f"User{user_id}"
        username_str = f"(@{username})" if username and username != "NoUsername" else ""
        text += f"{i}. {name} {username_str} — {invites} пригл.\n"
    
    # Кнопки для детального просмотра
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_search_referrals")]
        ]
    )
    
    await callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    await callback_query.answer()

# Статистика
@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    week_start = db.get_week_start()
    
    # Общая статистика
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT COUNT(*) FROM referrals")
    total_referrals = db.cursor.fetchone()[0]
    
    # Статистика за неделю
    db.cursor.execute("""
        SELECT 
            COUNT(DISTINCT user_id),
            SUM(invites_count),
            SUM(tickets_count)
        FROM weekly_stats 
        WHERE week_start = ?
    """, (week_start,))
    week_stats = db.cursor.fetchone()
    
    week_participants = week_stats[0] or 0
    week_invites = week_stats[1] or 0
    week_tickets = week_stats[2] or 0
    
    text = (
        f"📊 **Статистика бота**\n\n"
        f"**За всё время:**\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🔄 Всего приглашений: {total_referrals}\n\n"
        f"**Текущая неделя ({week_start}):**\n"
        f"👤 Участников: {week_participants}\n"
        f"➕ Новых приглашений: {week_invites}\n"
        f"🎫 Всего билетов: {week_tickets}\n"
        f"🏆 Приз: {config.WEEKLY_PRIZE}"
    )
    
    await callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback_query.answer()

# Розыгрыш
@dp.callback_query(lambda c: c.data == "admin_draw")
async def admin_draw(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    week_start = db.get_week_start()
    
    db.cursor.execute('''
        SELECT user_id, tickets_count FROM weekly_stats 
        WHERE week_start = ? AND tickets_count > 0
    ''', (week_start,))
    
    participants = db.cursor.fetchall()
    
    if not participants:
        await callback_query.message.edit_text("❌ Нет участников с билетами")
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
        f"🎉 **РОЗЫГРЫШ ПРОВЕДЁН!** 🎉\n\n"
        f"🏆 Приз: {config.WEEKLY_PRIZE}\n"
        f"👑 Победитель: {winner_name}\n\n"
        f"Поздравляем! 🥳"
    )
    
    await callback_query.message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
    
    # Отправляем личное сообщение победителю
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
    
    await callback_query.answer()

# Рассылка
@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback_query.message.edit_text(
        "📢 **Рассылка**\n\n"
        "Отправьте сообщение для рассылки всем пользователям.\n\n"
        "Можно использовать:\n"
        "• Текст\n"
        "• Фото с подписью\n"
        "• Видео\n\n"
        "Для отмены отправьте /cancel"
    )
    
    # Сохраняем состояние ожидания
    db.cursor.execute(
        "INSERT OR REPLACE INTO admin_states (user_id, state, data) VALUES (?, ?, ?)",
        (callback_query.from_user.id, "waiting_broadcast", "{}")
    )
    db.conn.commit()
    
    await callback_query.answer()

# Экспорт пользователей
@dp.callback_query(lambda c: c.data == "admin_export_users")
async def admin_export_users(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    db.cursor.execute("""
        SELECT 
            u.user_id,
            u.username,
            u.first_name,
            u.joined_date,
            COUNT(r.friend_id) as total_invites
        FROM users u
        LEFT JOIN referrals r ON u.user_id = r.referrer_id
        GROUP BY u.user_id
        ORDER BY u.joined_date DESC
    """)
    users_data = db.cursor.fetchall()
    
    # Создаем CSV
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User ID", "Username", "Имя", "Дата регистрации", "Приглашено друзей"])
    
    for row in users_data:
        writer.writerow(row)
    
    csv_data = output.getvalue().encode('utf-8')
    
    await callback_query.message.answer_document(
        types.BufferedInputFile(csv_data, filename="users_export.csv"),
        caption="📥 Экспорт пользователей"
    )
    
    await callback_query.answer()

# Обработка текстовых сообщений (для ожидания приза)
@dp.message()
async def handle_messages(message: Message):
    user_id = message.from_user.id
    
    # Проверяем состояние админа
    db.cursor.execute(
        "SELECT state, data FROM admin_states WHERE user_id = ?",
        (user_id,)
    )
    admin_state = db.cursor.fetchone()
    
    if admin_state and is_admin(user_id):
        state = admin_state[0]
        
        if state == "waiting_prize":
            # Меняем приз
            new_prize = message.text.strip()
            config.WEEKLY_PRIZE = new_prize
            
            # Обновляем в config (для текущей сессии)
            db.cursor.execute(
                "DELETE FROM admin_states WHERE user_id = ?",
                (user_id,)
            )
            db.conn.commit()
            
            await message.answer(
                f"✅ Приз успешно изменён на:\n"
                f"🏆 **{new_prize}**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_keyboard(True)
            )
            return
        
        elif state == "waiting_broadcast":
            # Отправляем рассылку
            await message.answer("📤 Начинаю рассылку...")
            
            # Получаем всех пользователей
            db.cursor.execute("SELECT user_id FROM users")
            users = db.cursor.fetchall()
            
            success = 0
            failed = 0
            
            for user in users:
                try:
                    await message.copy_to(user[0])
                    success += 1
                    await asyncio.sleep(0.05)  # Защита от спама
                except:
                    failed += 1
            
            db.cursor.execute(
                "DELETE FROM admin_states WHERE user_id = ?",
                (user_id,)
            )
            db.conn.commit()
            
            await message.answer(
                f"✅ Рассылка завершена!\n"
                f"📨 Отправлено: {success}\n"
                f"❌ Не доставлено: {failed}",
                reply_markup=get_main_keyboard(True)
            )
            return
    
    # Если не админское состояние - проверяем подписку и т.д.
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Остальные обработчики кнопок (my_tickets, top_week, invite_friend, about_prize)
    # Вставьте их сюда из предыдущей версии

# Добавим обработчики из предыдущей версии (my_tickets, top_week, invite_friend, about_prize)
# Они остаются без изменений

@dp.message(lambda message: message.text == "🎫 Мои билеты")
async def my_tickets(message: Message):
    user_id = message.from_user.id
    
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
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin(user_id)))

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
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin(user_id)))

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
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin(user_id)))

# Обработчик подтверждения по коду
@dp.callback_query(lambda c: c.data and c.data.startswith('confirm_'))
async def confirm_referral_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    received_code = callback_query.data.replace('confirm_', '')
    
    if user_id not in pending_confirmations:
        await callback_query.answer("❌ Срок действия кода истек", show_alert=True)
        await callback_query.message.edit_text("❌ Код недействителен")
        return
    
    confirm_data = pending_confirmations[user_id]
    
    if datetime.now() > confirm_data["expires"]:
        del pending_confirmations[user_id]
        await callback_query.answer("❌ Время вышло", show_alert=True)
        return
    
    if received_code != confirm_data["code"]:
        await callback_query.answer("❌ Неверный код", show_alert=True)
        return
    
    referrer_id = confirm_data["referrer_id"]
    
    # Проверяем, не был ли друг приглашен ранее
    db.cursor.execute(
        "SELECT id FROM referrals WHERE friend_id = ?",
        (user_id,)
    )
    if db.cursor.fetchone():
        await callback_query.answer("❌ Вы уже были приглашены", show_alert=True)
        del pending_confirmations[user_id]
        return
    
    success = db.add_referral(referrer_id, user_id)
    
    if success:
        del pending_confirmations[user_id]
        
        try:
            friend_name = callback_query.from_user.first_name
            await bot.send_message(
                referrer_id,
                f"🎉 По вашей ссылке зарегистрировался {friend_name}!\n"
                f"Ваши билеты обновлены!"
            )
        except:
            pass
        
        await callback_query.message.edit_text(
            "✅ **Приглашение подтверждено!**\n\n"
            "Теперь вам доступен розыгрыш!\n"
            "Нажмите /start чтобы начать."
        )
        
        await callback_query.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
    else:
        await callback_query.answer("❌ Ошибка добавления", show_alert=True)

# Обработчик кнопки "Копировать ссылку"
@dp.callback_query(lambda c: c.data == "copy_link")
async def copy_link_callback(callback_query: CallbackQuery):
    await callback_query.answer(
        text="Ссылка скопирована! Просто выдели и скопируй сообщение выше 👆",
        show_alert=False
    )

# Обработчик кнопки "Я подписался"
@dp.callback_query(lambda c: c.data == "check_sub")
async def check_subscription_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await callback_query.message.edit_text(
            f"✅ Спасибо за подписку!\n\n"
            f"Теперь вам доступен розыгрыш!\n"
            f"Нажмите /start, чтобы начать."
        )
        await callback_query.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
    else:
        await callback_query.answer(
            "❌ Вы ещё не подписались на канал.",
            show_alert=True
        )

# Функция очистки просроченных кодов
async def clean_expired_codes():
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        expired = [user_id for user_id, data in pending_confirmations.items() 
                  if data["expires"] < now]
        for user_id in expired:
            del pending_confirmations[user_id]
            print(f"Очищен просроченный код для user_id {user_id}")

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
    # Создаем таблицу для состояний админа, если её нет
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT
        )
    """)
    db.conn.commit()
    
    asyncio.create_task(clean_expired_codes())
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
