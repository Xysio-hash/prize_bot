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
    """Проверяет, подписан ли пользователь на канал сейчас"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        print(f"Ошибка проверки подписки для {user_id}: {e}")
        return False

# НОВАЯ ФУНКЦИЯ: Проверка, был ли пользователь когда-либо подписан
async def was_ever_subscribed(user_id: int) -> bool:
    """
    Проверяет, был ли пользователь когда-либо подписан на канал.
    Использует историю чата (бот должен быть админом)
    """
    try:
        # Пытаемся получить информацию о пользователе
        # Если пользователь есть в канале (даже если сейчас не подписан),
        # мы получим статус 'left' или 'kicked'
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        
        # Если получили любой статус, значит пользователь когда-то был в канале
        # Даже статус 'left' означает, что он был подписан ранее
        if member.status in ['member', 'administrator', 'creator', 'left', 'kicked', 'restricted']:
            print(f"Пользователь {user_id} найден в истории канала со статусом: {member.status}")
            return True
        return False
    except Exception as e:
        # Ошибка "user not found" означает, что пользователь НИКОГДА не был в канале
        if "user not found" in str(e).lower():
            print(f"Пользователь {user_id} никогда не был в канале")
            return False
        else:
            # Другие ошибки (бот не админ, проблемы с сетью) - лучше не пускать
            print(f"Ошибка при проверке истории канала для {user_id}: {e}")
            return True  # Консервативно - считаем что был, чтобы не накрутили

# НОВАЯ ФУНКЦИЯ: Проверка, можно ли засчитать друга
async def can_count_as_referral(friend_id: int, referrer_id: int) -> tuple:
    """
    Проверяет, можно ли засчитать друга пригласившему
    Возвращает (можно_ли, причина)
    """
    # Проверка 1: Друг не должен быть самим собой
    if friend_id == referrer_id:
        return False, "Нельзя пригласить самого себя"
    
    # Проверка 2: Друг не должен быть в таблице рефералов
    db.cursor.execute(
        "SELECT id FROM referrals WHERE friend_id = ?",
        (friend_id,)
    )
    if db.cursor.fetchone():
        return False, "Этот пользователь уже был приглашен ранее"
    
    # Проверка 3: Друг должен быть подписан прямо сейчас
    is_subscribed_now = await check_subscription(friend_id)
    if not is_subscribed_now:
        return False, "Пользователь не подписан на канал"
    
    # Проверка 4: Друг должен быть НОВЫМ подписчиком (никогда не был подписан ранее)
    was_subscribed = await was_ever_subscribed(friend_id)
    if was_subscribed:
        return False, "Пользователь уже был подписан на канал ранее"
    
    # Все проверки пройдены
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
    builder.add(InlineKeyboardButton(text="👥 Реферальная сеть", callback_data="admin_referrals"))
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="🎲 Розыгрыш", callback_data="admin_draw"))
    builder.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.adjust(2)
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
        # Проверяем, существует ли пригласивший
        if db.get_referrer_by_start_param(referrer_id):
            
            # НОВОЕ: Проверяем, можно ли засчитать этого друга
            can_count, reason = await can_count_as_referral(user_id, referrer_id)
            
            if not can_count:
                # Если нельзя засчитать, но пользователь подписан - просто пускаем в бота
                await message.answer(
                    f"👋 Привет, {first_name}!\n\n"
                    f"Вы перешли по приглашению, но {reason.lower()}.\n"
                    f"Поэтому приглашение не засчитано, но вы можете участвовать в розыгрыше!\n\n"
                    f"🎲 Каждую неделю мы разыгрываем призы!\n"
                    f"💰 Текущий приз: {config.WEEKLY_PRIZE}",
                    reply_markup=get_main_keyboard(is_admin(user_id))
                )
                return
            
            # Если можно засчитать - генерируем код подтверждения
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
    
    # Если нет пригласившего или он не существует
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

# Обработчик подтверждения по коду (ОБНОВЛЁННЫЙ)
@dp.callback_query(lambda c: c.data and c.data.startswith('confirm_'))
async def confirm_referral_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    received_code = callback_query.data.replace('confirm_', '')
    
    if user_id not in pending_confirmations:
        await callback_query.answer("❌ Срок действия кода истек", show_alert=True)
        await callback_query.message.edit_text("❌ Код недействителен")
        return
    
    confirm_data = pending_confirmations[user_id]
    referrer_id = confirm_data["referrer_id"]
    
    # Проверяем срок действия
    if datetime.now() > confirm_data["expires"]:
        del pending_confirmations[user_id]
        await callback_query.answer("❌ Время действия кода истекло (10 минут)", show_alert=True)
        await callback_query.message.edit_text("❌ Время действия кода истекло")
        return
    
    # Проверяем код
    if received_code != confirm_data["code"]:
        await callback_query.answer("❌ Неверный код подтверждения", show_alert=True)
        return
    
    # НОВОЕ: Финальная проверка перед добавлением
    can_count, reason = await can_count_as_referral(user_id, referrer_id)
    
    if not can_count:
        del pending_confirmations[user_id]
        await callback_query.answer(f"❌ {reason}", show_alert=True)
        await callback_query.message.edit_text(
            f"❌ {reason}.\n\n"
            f"Вы можете участвовать в розыгрыше самостоятельно!"
        )
        # Отправляем главное меню
        await callback_query.message.answer(
            "Добро пожаловать!",
            reply_markup=get_main_keyboard(is_admin(user_id))
        )
        return
    
    # Все проверки пройдены - добавляем реферала
    success = db.add_referral(referrer_id, user_id)
    
    if success:
        del pending_confirmations[user_id]
        
        # Уведомляем пригласившего
        try:
            friend_name = callback_query.from_user.first_name
            await bot.send_message(
                referrer_id,
                f"🎉 По вашей ссылке зарегистрировался новый участник {friend_name}!\n"
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
        await callback_query.answer("❌ Ошибка при добавлении приглашения", show_alert=True)

# АДМИН-ПАНЕЛЬ (добавляем новую функцию проверки подписчиков)
@dp.callback_query(lambda c: c.data == "admin_check_subscriber")
async def admin_check_subscriber(callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав", show_alert=True)
        return
    
    await callback_query.message.edit_text(
        "🔍 **Проверка подписчика**\n\n"
        "Отправьте ID пользователя или перешлите его сообщение, "
        "чтобы проверить, был ли он когда-либо подписан на канал."
    )
    
    # Сохраняем состояние ожидания
    db.cursor.execute(
        "INSERT OR REPLACE INTO admin_states (user_id, state, data) VALUES (?, ?, ?)",
        (callback_query.from_user.id, "waiting_subscriber_check", "{}")
    )
    db.conn.commit()
    
    await callback_query.answer()

# Добавляем обработчик для проверки подписчика
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
            
            db.cursor.execute("SELECT user_id FROM users")
            users = db.cursor.fetchall()
            
            success = 0
            failed = 0
            
            for user in users:
                try:
                    await message.copy_to(user[0])
                    success += 1
                    await asyncio.sleep(0.05)
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
        
        elif state == "waiting_subscriber_check":
            # Проверяем подписчика
            try:
                # Пробуем извлечь ID из сообщения
                if message.forward_from:
                    check_user_id = message.forward_from.id
                elif message.text and message.text.isdigit():
                    check_user_id = int(message.text)
                else:
                    await message.answer("❌ Отправьте ID пользователя или перешлите его сообщение")
                    return
                
                # Проверяем подписку
                is_subscribed_now = await check_subscription(check_user_id)
                was_subscribed = await was_ever_subscribed(check_user_id)
                
                # Получаем информацию о пользователе из БД
                db.cursor.execute(
                    "SELECT username, first_name, joined_date FROM users WHERE user_id = ?",
                    (check_user_id,)
                )
                user_info = db.cursor.fetchone()
                
                text = f"🔍 **Результат проверки пользователя {check_user_id}**\n\n"
                
                if user_info:
                    username, first_name, joined_date = user_info
                    text += f"Имя: {first_name}\n"
                    text += f"Username: @{username if username != 'NoUsername' else 'нет'}\n"
                    text += f"Зарегистрирован в боте: {joined_date}\n\n"
                else:
                    text += "Пользователь не зарегистрирован в боте\n\n"
                
                text += f"**Статус в канале:**\n"
                text += f"Подписан сейчас: {'✅ Да' if is_subscribed_now else '❌ Нет'}\n"
                text += f"Был подписан ранее: {'✅ Да' if was_subscribed else '❌ Нет'}\n\n"
                
                if was_subscribed:
                    text += "⚠️ **Этот пользователь НЕ может быть засчитан как новый друг!**"
                else:
                    text += "✅ **Этот пользователь может быть засчитан как новый друг!**"
                
                await message.answer(text, parse_mode=ParseMode.MARKDOWN)
                
            except Exception as e:
                await message.answer(f"❌ Ошибка при проверке: {e}")
            
            # Удаляем состояние
            db.cursor.execute(
                "DELETE FROM admin_states WHERE user_id = ?",
                (user_id,)
            )
            db.conn.commit()
            return
    
    # Если не админское состояние - проверяем подписку
    if not await check_subscription(user_id):
        await message.answer(
            "❌ Вы отписались от канала. Подпишитесь снова для доступа к боту.",
            reply_markup=get_subscription_keyboard()
        )
        return

# [ВСТАВЬТЕ СЮДА ВСЕ ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ИЗ ПРЕДЫДУЩЕЙ ВЕРСИИ:
# - my_tickets
# - top_week
# - invite_friend
# - about_prize
# - copy_link_callback
# - check_subscription_callback
# - admin_* обработчики (кроме добавленного выше admin_check_subscriber)
# - clean_expired_codes
# - start_web_server
# - main
# ]

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
    # Создаем таблицу для состояний админа
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
