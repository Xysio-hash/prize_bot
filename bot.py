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
from aiohttp import web
from datetime import datetime, timedelta

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

# Проверка подписки
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
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
        return False, "Уже был приглашен"
    
    if not await check_subscription(friend_id):
        return False, "Не подписан на канал"
    
    if await was_ever_subscribed(friend_id):
        return False, "Уже был подписан ранее"
    
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
            [InlineKeyboardButton(text="📢 Подписаться", url="https://t.me/colizeum_kp67")],
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
    
    if not await check_subscription(user_id):
        await message.answer(
            f"👋 Привет, {first_name}!\n\nПодпишись на канал {CHANNEL_USERNAME}",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    if referrer_id and db.get_referrer_by_start_param(referrer_id):
        can_count, reason = await can_count_as_referral(user_id, referrer_id)
        if not can_count:
            await message.answer(
                f"👋 Привет, {first_name}!\n\n{reason}",
                reply_markup=get_main_keyboard(is_admin(user_id))
            )
            return
        
        code = generate_confirmation_code()
        pending_confirmations[user_id] = {
            "referrer_id": referrer_id,
            "code": code,
            "expires": datetime.now() + timedelta(minutes=10)
        }
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=f"✅ Подтвердить {code}", callback_data=f"confirm_{code}")]]
        )
        
        await message.answer(
            f"🔐 Нажми кнопку для подтверждения\nКод: {code}",
            reply_markup=keyboard
        )
        return
    
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"🎲 Разыгрываем {config.WEEKLY_PRIZE}\n"
        f"1 друг = 1 билет\n"
        f"5 друзей = +1 бонус\n"
        f"10 друзей = +2 бонуса",
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.callback_query(lambda c: c.data and c.data.startswith('confirm_'))
async def confirm_referral(callback: CallbackQuery):
    user_id = callback.from_user.id
    code = callback.data.replace('confirm_', '')
    
    if user_id not in pending_confirmations:
        await callback.answer("Код истек", show_alert=True)
        return
    
    data = pending_confirmations[user_id]
    if datetime.now() > data["expires"]:
        del pending_confirmations[user_id]
        await callback.answer("Время вышло", show_alert=True)
        return
    
    if code != data["code"]:
        await callback.answer("Неверный код", show_alert=True)
        return
    
    can_count, reason = await can_count_as_referral(user_id, data["referrer_id"])
    if not can_count:
        del pending_confirmations[user_id]
        await callback.answer(reason, show_alert=True)
        await callback.message.edit_text(f"❌ {reason}")
        return
    
    if db.add_referral(data["referrer_id"], user_id):
        del pending_confirmations[user_id]
        await callback.message.edit_text("✅ Приглашение подтверждено!")
        await callback.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
        try:
            await bot.send_message(
                data["referrer_id"],
                f"🎉 {callback.from_user.first_name} подтвердил приглашение!"
            )
        except:
            pass
    else:
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.edit_text("✅ Спасибо! Нажми /start")
        await callback.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(callback.from_user.id))
        )
    else:
        await callback.answer("❌ Нет подписки", show_alert=True)

# ==================== КНОПКИ МЕНЮ ====================

@dp.message(lambda message: message.text == "🎫 Мои билеты")
async def my_tickets(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❌ Нет подписки", reply_markup=get_subscription_keyboard())
        return
    
    stats = db.get_user_stats(user_id)
    week_start = db.get_week_start()
    db.cursor.execute("SELECT SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", (week_start,))
    total = db.cursor.fetchone()[0] or 1
    chance = (stats['tickets'] / total) * 100
    
    await message.answer(
        f"🎫 **Твои билеты**\n\n"
        f"Друзей: {stats['invites']}\n"
        f"Билетов: {stats['tickets']}\n"
        f"Шанс: {chance:.1f}%\n"
        f"Приз: {config.WEEKLY_PRIZE}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.message(lambda message: message.text == "📊 Топ недели")
async def top_week(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❌ Нет подписки", reply_markup=get_subscription_keyboard())
        return
    
    top = db.get_top_users(10)
    if not top:
        await message.answer("Пока нет участников")
        return
    
    text = "🏆 **Топ 10**\n\n"
    for i, u in enumerate(top, 1):
        name = u[2] or f"User{u[0]}"
        text += f"{i}. {name} — {u[4]} билетов\n"
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_keyboard(is_admin(user_id)))

@dp.message(lambda message: message.text == "🔗 Пригласить друга")
async def invite_friend(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❌ Нет подписки", reply_markup=get_subscription_keyboard())
        return
    
    bot_user = await bot.me()
    link = f"https://t.me/{bot_user.username}?start=ref{user_id}"
    await message.answer(
        f"🔗 **Твоя ссылка**\n`{link}`\n\nПриглашай друзей!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

@dp.message(lambda message: message.text == "🏆 О розыгрыше")
async def about_prize(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❌ Нет подписки", reply_markup=get_subscription_keyboard())
        return
    
    week = db.get_week_start()
    db.cursor.execute("SELECT COUNT(*), SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", (week,))
    data = db.cursor.fetchone()
    participants = data[0] or 0
    tickets = data[1] or 0
    
    await message.answer(
        f"🏆 **Розыгрыш**\n\n"
        f"Приз: {config.WEEKLY_PRIZE}\n"
        f"Участников: {participants}\n"
        f"Билетов: {tickets}\n"
        f"Итоги: воскресенье",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard(is_admin(user_id))
    )

# ==================== АДМИН-ПАНЕЛЬ ====================

@dp.message(lambda message: message.text == "⚙️ Админ панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⚙️ Админка", reply_markup=get_admin_keyboard())

@dp.callback_query(lambda c: c.data == "admin_change_prize")
async def admin_change_prize(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("Отправь новый приз")
    db.cursor.execute("INSERT OR REPLACE INTO admin_states VALUES (?,?,?)",
                     (callback.from_user.id, "waiting_prize", "{}"))
    db.conn.commit()

@dp.callback_query(lambda c: c.data == "admin_users_list")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db.cursor.execute("SELECT user_id, username, first_name, joined_date FROM users ORDER BY joined_date DESC LIMIT 20")
    users = db.cursor.fetchall()
    text = "📋 **Последние 20**\n\n"
    for u in users:
        name = u[2] or f"User{u[0]}"
        user = f"@{u[1]}" if u[1] and u[1] != "NoUsername" else ""
        text += f"{name} {user} - {u[3]}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(lambda c: c.data == "admin_referrals")
async def admin_referrals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db.cursor.execute("""
        SELECT users.first_name, users.username, COUNT(*) as cnt
        FROM referrals JOIN users ON referrals.referrer_id = users.user_id
        GROUP BY referrals.referrer_id ORDER BY cnt DESC LIMIT 10
    """)
    top = db.cursor.fetchall()
    text = "👥 **Топ приглашающих**\n\n"
    for i, t in enumerate(top, 1):
        name = t[0] or "NoName"
        user = f"(@{t[1]})" if t[1] else ""
        text += f"{i}. {name} {user} - {t[2]}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT COUNT(*) FROM referrals")
    total_refs = db.cursor.fetchone()[0]
    
    week = db.get_week_start()
    db.cursor.execute("SELECT COUNT(*), SUM(invites_count), SUM(tickets_count) FROM weekly_stats WHERE week_start = ?", (week,))
    w = db.cursor.fetchone()
    
    await callback.message.edit_text(
        f"📊 **Статистика**\n\n"
        f"Всего:\n👤 {total_users}\n🔄 {total_refs}\n\n"
        f"Неделя:\n👥 {w[0] or 0}\n➕ {w[1] or 0}\n🎫 {w[2] or 0}\n"
        f"🏆 {config.WEEKLY_PRIZE}",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(lambda c: c.data == "admin_draw")
async def admin_draw(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    week = db.get_week_start()
    db.cursor.execute("SELECT user_id, tickets_count FROM weekly_stats WHERE week_start = ? AND tickets_count > 0", (week,))
    participants = db.cursor.fetchall()
    
    if not participants:
        await callback.answer("Нет участников", show_alert=True)
        return
    
    pool = []
    for uid, cnt in participants:
        pool.extend([uid] * cnt)
    
    winner = random.choice(pool)
    db.cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (winner,))
    name = db.cursor.fetchone()
    name = name[0] if name else f"User{winner}"
    
    await callback.message.edit_text(
        f"🎉 **Победитель**\n\n{name}\n\nПриз: {config.WEEKLY_PRIZE}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        await bot.send_message(winner, f"🎉 Ты выиграл {config.WEEKLY_PRIZE}!")
    except:
        pass

@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("Отправь сообщение для рассылки")
    db.cursor.execute("INSERT OR REPLACE INTO admin_states VALUES (?,?,?)",
                     (callback.from_user.id, "waiting_broadcast", "{}"))
    db.conn.commit()

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

@dp.message()
async def handle_messages(message: Message):
    user_id = message.from_user.id
    
    # Проверка состояний админа
    db.cursor.execute("SELECT state FROM admin_states WHERE user_id = ?", (user_id,))
    state = db.cursor.fetchone()
    
    if state and is_admin(user_id):
        if state[0] == "waiting_prize":
            config.WEEKLY_PRIZE = message.text.strip()
            db.cursor.execute("DELETE FROM admin_states WHERE user_id = ?", (user_id,))
            db.conn.commit()
            await message.answer(f"✅ Приз: {config.WEEKLY_PRIZE}", reply_markup=get_main_keyboard(True))
            return
        
        elif state[0] == "waiting_broadcast":
            await message.answer("📤 Рассылка...")
            db.cursor.execute("SELECT user_id FROM users")
            users = db.cursor.fetchall()
            ok = 0
            for u in users:
                try:
                    await message.copy_to(u[0])
                    ok += 1
                    await asyncio.sleep(0.05)
                except:
                    pass
            db.cursor.execute("DELETE FROM admin_states WHERE user_id = ?", (user_id,))
            db.conn.commit()
            await message.answer(f"✅ Отправлено: {ok}")
            return
    
    # Проверка подписки для обычных пользователей
    if not await check_subscription(user_id):
        await message.answer("❌ Нет подписки", reply_markup=get_subscription_keyboard())

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

async def clean_expired_codes():
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        expired = [uid for uid, data in pending_confirmations.items() if data["expires"] < now]
        for uid in expired:
            del pending_confirmations[uid]

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 10000).start()
    logging.info("Server started")

# ==================== ЗАПУСК ====================

async def main():
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
