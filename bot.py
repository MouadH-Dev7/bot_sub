import os
import json
import stripe
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from db_utils import add_user, get_all_users, delete_user, update_user, get_user_stats

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
PRICE_ID = os.getenv("PRICE_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
stripe.api_key = STRIPE_SECRET_KEY

SETTINGS_FILE = "settings.json"

# Load settings
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"subscription_days": 30, "warning_minutes": 1, "check_interval_minutes": 1}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

settings = load_settings()

class AdminStates(StatesGroup):
    change_subscription_days = State()
    change_warning_minutes = State()
    change_check_interval = State()

# ========== إزالة المستخدمين منتهيي الاشتراك ==========
async def remove_expired_users():
    db = get_all_users()
    now = datetime.now(timezone.utc)

    for uid, data in list(db.items()):
        try:
            end = datetime.fromisoformat(data["end_date"])
            remaining = (end - now).total_seconds()

            if 0 < remaining <= settings["warning_minutes"] * 60 and not data.get("notified", False):
                await bot.send_message(int(uid), "⚠️ تنبيه: تبقّت دقيقة واحدة على انتهاء اشتراكك.")
                update_user(uid, notified=True)

            elif remaining <= 0:
                await bot.kick_chat_member(CHANNEL_ID, int(uid))

                checkout = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{"price": PRICE_ID, "quantity": 1}],
                    mode="subscription",
                    success_url=f"https://t.me/{(await bot.get_me()).username}",
                    cancel_url=f"https://t.me/{(await bot.get_me()).username}",
                    metadata={"user_id": uid, "username": data.get("username", "unknown")}
                )

                markup = InlineKeyboardMarkup().add(
                    InlineKeyboardButton("💳 إعادة الاشتراك", url=checkout.url)
                )

                await bot.send_message(
                    chat_id=int(uid),
                    text="❌ انتهى اشتراكك وتم طردك.\n📌 اضغط أدناه لإعادة الاشتراك:",
                    reply_markup=markup
                )
                delete_user(uid)

        except Exception as e:
            print(f"⚠️ خطأ: {e}")

# ========== أمر /start ==========
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    if msg.from_user.id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("📊 إحصائيات", callback_data="stats"),
            InlineKeyboardButton("👥 عرض المشتركين", callback_data="list_users"),
            InlineKeyboardButton("✉️ إرسال رسالة جماعية", callback_data="broadcast"),
            InlineKeyboardButton("🛠 إعدادات", callback_data="settings")
        )
        await msg.answer("👋 مرحبًا بك أيها الأدمن!\nاختر من لوحة التحكم:", reply_markup=markup)
    else:
        db = get_all_users()
        user_id = str(msg.from_user.id)

        if user_id in db:
            end = db[user_id]["end_date"]
            await msg.answer(f"✅ اشتراكك ساري حتى: {end}")
        else:
            checkout = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price": PRICE_ID, "quantity": 1}],
                mode="subscription",
                success_url=f"https://t.me/{(await bot.get_me()).username}",
                cancel_url=f"https://t.me/{(await bot.get_me()).username}",
                metadata={"user_id": msg.from_user.id, "username": msg.from_user.username or "unknown"}
            )

            markup = InlineKeyboardMarkup().add(
                InlineKeyboardButton("💳 ادفع الآن", url=checkout.url)
            )

            await msg.answer("🔒 لم يتم تفعيل اشتراكك.\nيرجى الدفع:", reply_markup=markup)

# ========== رد على ضغط الأزرار ==========
@dp.callback_query_handler(lambda c: c.data)
async def process_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    await callback.answer()

    if callback.from_user.id != ADMIN_ID:
        return

    if data == "stats":
        stats = get_user_stats()
        await callback.message.answer(
            f"📊 إحصائيات:\n"
            f"- جميع المستخدمين: {stats['total']}\n"
            f"- النشطين: {stats['active']}\n"
            f"- المنتهية صلاحيتهم: {stats['expired']}"
        )
    elif data == "list_users":
        users = get_all_users()
        if not users:
            await callback.message.answer("❗ لا يوجد مستخدمون بعد.")
            return
        text = "👥 قائمة المستخدمين:\n"
        for uid, u in users.items():
            text += f"• @{u.get('username', 'غير معروف')} — {u['end_date']}\n"
        await callback.message.answer(text[:4096])
    elif data == "broadcast":
        await callback.message.answer("✍️ أرسل الآن الرسالة التي تريد إرسالها للمستخدمين:")
        await state.set_state("awaiting_broadcast")
    elif data == "settings":
        markup = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🕒 مدة الاشتراك", callback_data="sub_days"),
            InlineKeyboardButton("⏰ وقت التنبيه", callback_data="warn_minutes"),
            InlineKeyboardButton("🔄 وقت المراقبة", callback_data="check_interval")
        )
        await callback.message.answer("⚙️ اختر الإعداد الذي تريد تغييره:", reply_markup=markup)
    elif data == "sub_days":
        await callback.message.answer("📥 أرسل عدد أيام الاشتراك الجديد:")
        await AdminStates.change_subscription_days.set()
    elif data == "warn_minutes":
        await callback.message.answer("📥 أرسل عدد الدقائق قبل التنبيه:")
        await AdminStates.change_warning_minutes.set()
    elif data == "check_interval":
        await callback.message.answer("📥 أرسل عدد دقائق المراقبة:")
        await AdminStates.change_check_interval.set()

# ========== التعامل مع تغييرات الإعدادات ==========
@dp.message_handler(state=AdminStates.change_subscription_days)
async def process_sub_days(msg: types.Message, state: FSMContext):
    try:
        val = int(msg.text)
        settings["subscription_days"] = val
        save_settings(settings)
        await msg.answer(f"✅ تم تحديث مدة الاشتراك إلى {val} يومًا.")
    except:
        await msg.answer("❌ أرسل رقمًا صحيحًا.")
    await state.finish()

@dp.message_handler(state=AdminStates.change_warning_minutes)
async def process_warn_minutes(msg: types.Message, state: FSMContext):
    try:
        val = int(msg.text)
        settings["warning_minutes"] = val
        save_settings(settings)
        await msg.answer(f"✅ تم تحديث وقت التنبيه إلى {val} دقيقة.")
    except:
        await msg.answer("❌ أرسل رقمًا صحيحًا.")
    await state.finish()

@dp.message_handler(state=AdminStates.change_check_interval)
async def process_check_interval(msg: types.Message, state: FSMContext):
    try:
        val = int(msg.text)
        settings["check_interval_minutes"] = val
        save_settings(settings)
        await msg.answer(f"✅ تم تحديث وقت المراقبة إلى {val} دقيقة.")
    except:
        await msg.answer("❌ أرسل رقمًا صحيحًا.")
    await state.finish()

# ========== إرسال رسالة جماعية ==========
@dp.message_handler(state="awaiting_broadcast")
async def broadcast_message(msg: types.Message, state: FSMContext):
    users = get_all_users()
    count = 0
    for uid in users:
        try:
            await bot.send_message(uid, msg.text)
            count += 1
        except:
            pass
    await msg.answer(f"✅ تم إرسال الرسالة إلى {count} مستخدم.")
    await state.finish()

# ========== تشغيل البوت ==========
scheduler = AsyncIOScheduler(timezone=pytz.utc)
async def on_startup(_):
    scheduler.add_job(remove_expired_users, "interval", minutes=settings["check_interval_minutes"])
    scheduler.start()
    print("✅ البوت جاهز")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
