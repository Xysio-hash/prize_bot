import logging
import asyncio
import random
import string
import gc
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import config
from database import Database
from aiohttp import web
from datetime import datetime, timedelta

# Принудительно используем IPv4 (для стабильности)
os.environ["HTTPX_FORCE_IP4_ROUTING"] = "1"

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = Database()

# Константы
CHANNEL_USERNAME = "@colizeum_kp67"
ADMIN_ID = 1335144671

# Хранилище для временных кодов
pending_confirmations = {}

# Функция генерации кода
def generate_confirmation_code(length=6):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# Периодическая очистка памяти
async def memory_cleaner():
    """Запускает сборку мусора каждые 10 минут"""
    while True:
        await asyncio.sleep(600)  # 10 минут
        gc.collect()
        logging.info("🧹 Очистка памяти выполнена")

# Проверка подписки
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# Проверка истории подписок
async def was_ever_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator', 'left', 'kicked', 'restricted']:
            return True
        return False
    except Exception:
        return False

# Проверка можно ли засчитать друга
async def can_count_as_referral(friend_id: int, referrer_id: int) -> tuple:
    if friend_id == referrer_id:
        return False, "Нельзя пригласить самого себя"
    
    db.cursor.execute("SELECT id FROM referrals WHERE friend_id = ?", (friend_id,))
    if db.cursor.fetchone():
        return False, "Этот пользователь уже был приглашен ранее"
    
    if not await check_subscription(friend_id):
        return False, "Пользователь не подписан на канал"
    
    if await was_ever_subscribed(friend_id):
        return False, "Пользователь уже был подписан на канал ранее"
    
    return True, "OK"

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
    builder.add(InlineKeyboardButton(text="👥 Рефералы", callback_data="admin_referrals"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🎲 Розыгрыш", callback_data="admin_draw"))
    builder.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.adjust(2)
    return builder.as_markup()

# Клавиатура подписки
def get_subscription_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/colizeum_kp67")],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
        ]
    )

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@dp.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name
    
    db.add_user(user_id, username, first_name)
    
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith('ref'):
        try:
            referrer_id = int(args[1].replace('ref', ''))
            if referrer_id == user_id:
                referrer_id = None
        except:
            referrer_id = None
    
    # Проверка подписки
    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Привет, {first_name}!\n\n"
            f"Для участия в розыгрыше нужно подписаться на канал:\n"
            f"{CHANNEL_USERNAME}",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Если есть пригласивший
    if referrer_id and db.get_referrer_by_start_param(referrer_id):
        can_count, reason = await can_count_as_referral(user_id, referrer_id)
        if not can_count:
            await message.answer(
                f"👋 Привет, {first_name}!\n\n"
                f"{reason}\n\n"
                f"Но вы можете участвовать в розыгрыше!",
                reply_markup=get_main_keyboard(is_admin(user_id))
            )
            return
        
        # Генерация кода подтверждения
        code = generate_confirmation_code()
        pending_confirmations[user_id] = {
            "referrer_id": referrer_id,
            "code": code,
            "expires": datetime.now() + timedelta(minutes=10)
        }
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ Подтвердить приглашение", 
                    callback_data=f"confirm_{code}"
                )]
            ]
        )
        
        await message.answer(
            f"🔐 **Подтверждение приглашения**\n\n"
            f"Вы перешли по приглашению друга!\n"
            f"Чтобы приглашение засчиталось, нажмите кнопку ниже.\n\n"
            f"Код: `{code}`\n"
            f"⏳ Действителен 10 минут",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return
    
    # Обычный запуск
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"🎲 **Розыгрыш {config.WEEKLY_PRIZE}**\n\n"
        f"Как получить билеты:\n"
        f"• 1 друг = 1 билет\n"
        f"• 5 друзей = +1 бонус\n"
        f"• 10 друзей = +2 бонуса\n\n"
        f"⚠️ Друг засчитывается только если он:\n"
        f"• Никогда не был подписан на канал\n"
        f"• Подтвердил приглашение в боте",
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.callback_query(lambda c: c.data and c.data.startswith('confirm_'))
async def confirm_referral(callback: CallbackQuery):
    user_id = callback.from_user.id
    code = callback.data.replace('confirm_', '')
    
    if user_id not in pending_confirmations:
        await callback.answer("❌ Срок действия кода истек", show_alert=True)
        await callback.message.edit_text("❌ Код недействителен")
        return
    
    data = pending_confirmations[user_id]
    
    if datetime.now() > data["expires"]:
        del pending_confirmations[user_id]
        await callback.answer("❌ Время действия кода истекло", show_alert=True)
        await callback.message.edit_text("❌ Время вышло. Попробуйте снова.")
        return
    
    if code != data["code"]:
        await callback.answer("❌ Неверный код", show_alert=True)
        return
    
    can_count, reason = await can_count_as_referral(user_id, data["referrer_id"])
    if not can_count:
        del pending_confirmations[user_id]
        await callback.answer(f"❌ {reason}", show_alert=True)
        await callback.message.edit_text(f"❌ {reason}")
        return
    
    if db.add_referral(data["referrer_id"], user_id):
        del pending_confirmations[user_id]
        await callback.message.edit_text("✅ **Приглашение подтверждено!**")
        await callback.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
        try:
            await bot.send_message(
                data["referrer_id"],
                f"🎉 {callback.from_user.first_name} подтвердил приглашение!\n"
                f"Ваши билеты обновлены!"
            )
        except:
            pass
    else:
        await callback.answer("❌ Ошибка при добавлении", show_alert=True)

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if await check_subscription(user_id):
        await callback.message.edit_text("✅ Спасибо за подписку! Нажмите /start")
        await callback.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
    else:
        await callback.answer("❌ Вы ещё не подписались", show_alert=True)

# ==================== КНОПКИ МЕНЮ ====================

@dp.message(lambda message: message.text == "🎫 Мои билеты")
async def my_tickets(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Нет подписки на канал",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    stats = db.get_user_stats(user_id)
    week_start = db.get_week_start()
    db.cursor.execute(
        "SELECT SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", 
        (week_start,)
    )
    total = db.cursor.fetchone()[0] or 1
    chance = (stats['tickets'] / total) * 100
    
    await message.answer(
        f"🎫 **Ваши билеты**\n\n"
        f"👥 Приглашено друзей: {stats['invites']}\n"
        f"🎫 Билетов: {stats['tickets']}\n"
        f"📊 Шанс на победу: {chance:.1f}%\n\n"
        f"💰 Приз: {config.WEEKLY_PRIZE}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.message(lambda message: message.text == "📊 Топ недели")
async def top_week(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Нет подписки на канал",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    top = db.get_top_users(10)
    if not top:
        await message.answer("📊 Пока нет участников. Стань первым!")
        return
    
    text = "🏆 **Топ 10 участников недели** 🏆\n\n"
    for i, u in enumerate(top, 1):
        name = u[2] or f"User{u[0]}"
        username = f"(@{u[1]})" if u[1] and u[1] != "NoUsername" else ""
        text += f"{i}. {name} {username} — {u[4]} билетов\n"
    
    await message.answer(
        text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.message(lambda message: message.text == "🔗 Пригласить друга")
async def invite_friend(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Нет подписки на канал",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    bot_user = await bot.me()
    link = f"https://t.me/{bot_user.username}?start=ref{user_id}"
    
    await message.answer(
        f"🔗 **Твоя реферальная ссылка**\n\n"
        f"`{link}`\n\n"
        f"📤 Отправь эту ссылку друзьям\n\n"
        f"⚠️ **Важно:** друг засчитывается только если:\n"
        f"• Он новый подписчик канала\n"
        f"• Он подтвердит приглашение в боте",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.message(lambda message: message.text == "🏆 О розыгрыше")
async def about_prize(message: Message):
    user_id = message.from_user.id
    
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Нет подписки на канал",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    week = db.get_week_start()
    db.cursor.execute(
        "SELECT COUNT(*), SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", 
        (week,)
    )
    data = db.cursor.fetchone()
    participants = data[0] or 0
    tickets = data[1] or 0
    
    from datetime import datetime, timedelta
    monday = datetime.strptime(week, "%Y-%m-%d").date()
    sunday = monday + timedelta(days=6)
    
    text = (
        f"🏆 **О РОЗЫГРЫШЕ** 🏆\n\n"
        f"💰 **Приз:** {config.WEEKLY_PRIZE}\n"
        f"👥 **Участников:** {participants}\n"
        f"🎫 **Билетов:** {tickets}\n"
        f"📅 **Розыгрыш:** {sunday.strftime('%d.%m.%Y')}\n\n"
        f"⚡ **Как получить билеты:**\n"
        f"• 1 друг = 1 билет\n"
        f"• 5 друзей = +1 бонус\n"
        f"• 10 друзей = +2 бонуса\n\n"
        f"⚠️ **ВАЖНОЕ ПРАВИЛО:**\n"
        f"Приглашённый друг засчитывается ТОЛЬКО если:\n"
        f"✅ Он **никогда ранее не был подписан** на канал\n"
        f"✅ Он **подтвердил приглашение** в боте (нажал кнопку)\n"
        f"❌ Старые подписчики и отписавшиеся **НЕ засчитываются**\n\n"
        f"🎯 Чем больше новых друзей, тем выше шанс на победу!"
    )
    
    await message.answer(
        text, 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

# ==================== АДМИН-ПАНЕЛЬ ====================

@dp.message(lambda message: message.text == "⚙️ Админ панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "⚙️ **Административная панель**\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query(lambda c: c.data == "admin_change_prize")
async def admin_change_prize(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🏆 **Смена приза**\n\n"
        "Отправьте новое название приза одним сообщением.\n"
        "Например: `2000 рублей` или `Наушники`"
    )
    db.cursor.execute(
        "INSERT OR REPLACE INTO admin_states (user_id, state, data) VALUES (?, ?, ?)",
        (callback.from_user.id, "waiting_prize", "{}")
    )
    db.conn.commit()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_users_list")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    db.cursor.execute(
        "SELECT user_id, username, first_name, joined_date FROM users ORDER BY joined_date DESC LIMIT 20"
    )
    users = db.cursor.fetchall()
    
    text = "📋 **Последние 20 пользователей:**\n\n"
    for u in users:
        name = u[2] or f"User{u[0]}"
        user = f"(@{u[1]})" if u[1] and u[1] != "NoUsername" else ""
        text += f"• {name} {user} - {u[3]}\n"
    
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_referrals")
async def admin_referrals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    db.cursor.execute("""
        SELECT users.first_name, users.username, COUNT(*) as cnt
        FROM referrals 
        JOIN users ON referrals.referrer_id = users.user_id
        GROUP BY referrals.referrer_id 
        ORDER BY cnt DESC 
        LIMIT 10
    """)
    top = db.cursor.fetchall()
    
    text = "👥 **Топ приглашающих:**\n\n"
    for i, t in enumerate(top, 1):
        name = t[0] or "NoName"
        user = f"(@{t[1]})" if t[1] else ""
        text += f"{i}. {name} {user} — {t[2]} пригл.\n"
    
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT COUNT(*) FROM referrals")
    total_refs = db.cursor.fetchone()[0]
    
    week = db.get_week_start()
    db.cursor.execute(
        "SELECT COUNT(*), SUM(invites_count), SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", 
        (week,)
    )
    w = db.cursor.fetchone()
    
    text = (
        f"📊 **СТАТИСТИКА**\n\n"
        f"**За всё время:**\n"
        f"👤 Пользователей: {total_users}\n"
        f"🔄 Приглашений: {total_refs}\n\n"
        f"**Текущая неделя:**\n"
        f"👥 Участников: {w[0] or 0}\n"
        f"➕ Приглашений: {w[1] or 0}\n"
        f"🎫 Билетов: {w[2] or 0}\n\n"
        f"🏆 Приз: {config.WEEKLY_PRIZE}"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_draw")
async def admin_draw(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    week = db.get_week_start()
    db.cursor.execute(
        "SELECT user_id, tickets_count FROM weekly_stats WHERE week_start = ? AND tickets_count > 0", 
        (week,)
    )
    participants = db.cursor.fetchall()
    
    if not participants:
        await callback.answer("❌ Нет участников с билетами", show_alert=True)
        return
    
    # Создаем пул билетов
    pool = []
    for uid, cnt in participants:
        pool.extend([uid] * cnt)
    
    winner = random.choice(pool)
    
    db.cursor.execute(
        "SELECT first_name, username FROM users WHERE user_id = ?", 
        (winner,)
    )
    winner_info = db.cursor.fetchone()
    winner_name = winner_info[0] or f"User{winner}"
    winner_username = f"(@{winner_info[1]})" if winner_info[1] and winner_info[1] != "NoUsername" else ""
    
    await callback.message.edit_text(
        f"🎉 **РОЗЫГРЫШ ПРОВЕДЁН!** 🎉\n\n"
        f"🏆 Приз: {config.WEEKLY_PRIZE}\n"
        f"👑 Победитель: {winner_name} {winner_username}\n\n"
        f"Поздравляем! 🥳",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        await bot.send_message(
            winner,
            f"🎉 **ПОЗДРАВЛЯЕМ!** 🎉\n\n"
            f"Ты выиграл(а) в розыгрыше!\n"
            f"💰 Приз: {config.WEEKLY_PRIZE}\n\n"
            f"Свяжись с администратором для получения приза!"
        )
    except:
        pass
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📢 **РАССЫЛКА**\n\n"
        "Отправьте сообщение для рассылки всем пользователям.\n\n"
        "Можно отправлять:\n"
        "• Текст\n"
        "• Фото с подписью\n"
        "• Видео\n\n"
        "Для отмены отправьте /cancel"
    )
    db.cursor.execute(
        "INSERT OR REPLACE INTO admin_states (user_id, state, data) VALUES (?, ?, ?)",
        (callback.from_user.id, "waiting_broadcast", "{}")
    )
    db.conn.commit()
    await callback.answer()

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

@dp.message()
async def handle_messages(message: Message):
    user_id = message.from_user.id
    
    # Проверка состояний админа
    db.cursor.execute(
        "SELECT state FROM admin_states WHERE user_id = ?", 
        (user_id,)
    )
    state = db.cursor.fetchone()
    
    if state and is_admin(user_id):
        if state[0] == "waiting_prize":
            new_prize = message.text.strip()
            config.WEEKLY_PRIZE = new_prize
            
            db.cursor.execute(
                "DELETE FROM admin_states WHERE user_id = ?", 
                (user_id,)
            )
            db.conn.commit()
            
            await message.answer(
                f"✅ Приз успешно изменён на:\n🏆 **{new_prize}**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_keyboard(True)
            )
            return
        
        elif state[0] == "waiting_broadcast":
            await message.answer("📤 Начинаю рассылку...")
            
            db.cursor.execute("SELECT user_id FROM users")
            users = db.cursor.fetchall()
            
            success = 0
            failed = 0
            
            for u in users:
                try:
                    await message.copy_to(u[0])
                    success += 1
                    await asyncio.sleep(0.05)  # Защита от спама
                except Exception as e:
                    failed += 1
                    logging.error(f"Ошибка рассылки для {u[0]}: {e}")
            
            db.cursor.execute(
                "DELETE FROM admin_states WHERE user_id = ?", 
                (user_id,)
            )
            db.conn.commit()
            
            await message.answer(
                f"✅ Рассылка завершена!\n"
                f"📨 Отправлено: {success}\n"
                f"❌ Ошибок: {failed}",
                reply_markup=get_main_keyboard(True)
            )
            return
    
    # Проверка подписки для обычных пользователей
    if not await check_subscription(user_id):
        # Не спамим, если это не команда
        if message.text and not message.text.startswith('/'):
            return
        await message.answer(
            "❌ Нет подписки на канал",
            reply_markup=get_subscription_keyboard()
        )

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

async def clean_expired_codes():
    """Очищает просроченные коды подтверждения"""
    while True:
        await asyncio.sleep(60)  # Каждую минуту
        now = datetime.now()
        expired = [uid for uid, data in pending_confirmations.items() if data["expires"] < now]
        for uid in expired:
            del pending_confirmations[uid]
            logging.info(f"Очищен просроченный код для user_id {uid}")

async def start_web_server():
    """Запускает HTTP сервер для проверки Render"""
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 10000).start()
    logging.info("✅ Keep-alive server started on port 10000")

# ==================== ЗАПУСК ====================

async def main():
    # Создаем таблицу для состояний админа
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT
        )
    """)
    db.conn.commit()
    
    # Запускаем фоновые задачи
    asyncio.create_task(clean_expired_codes())
    asyncio.create_task(start_web_server())
    asyncio.create_task(memory_cleaner())
    
    # Запускаем бота
    logging.info("🚀 Бот запускается...")
    await dp.start_polling(
        bot, 
        allowed_updates=['message', 'callback_query'],
        skip_updates=True  # Пропускаем старые апдейты
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🛑 Бот остановлен")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
