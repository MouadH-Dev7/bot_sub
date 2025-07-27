# webhook.py
import os
import json
import stripe
import asyncio
import pytz
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.background import BackgroundScheduler
from db_utils import add_user, delete_user, update_user, get_all_users

# تحميل المتغيرات من .env
load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
PRICE_ID = os.getenv("PRICE_ID")

bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

SETTINGS_FILE = "settings.json"

def load_settings():
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

async def remove_expired_users():
    db = get_all_users()
    now = datetime.now(timezone.utc)
    settings = load_settings()
    warning_minutes = settings.get("warning_minutes", 5)

    for uid, data in list(db.items()):
        try:
            end = datetime.fromisoformat(data["end_date"])
            remaining = (end - now).total_seconds()

            if 0 < remaining <= warning_minutes * 60 and not data.get("notified", False):
                await bot.send_message(int(uid), "⚠️ تبقّت دقائق معدودة على انتهاء اشتراكك.")
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
                    text="❌ انتهى اشتراكك وتم طردك من القناة.\n📌 اضغط أدناه لإعادة الاشتراك:",
                    reply_markup=markup
                )
                delete_user(uid)

        except Exception as e:
            print(f"⚠️ خطأ مع {uid}: {e}")

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})

        user_id = metadata.get("user_id")
        username = metadata.get("username", "unknown")

        if user_id and username:
            print(f"📥 اشتراك جديد: {username} ({user_id})")

            settings = load_settings()
            subscription_days = settings.get("subscription_days", 30)
            end_date = (datetime.now(timezone.utc) + timedelta(days=subscription_days)).isoformat()

            add_user(user_id, username, end_date=end_date)

            try:
                bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id))

                invite = bot.create_chat_invite_link(
                    chat_id=CHANNEL_ID,
                    expire_date=datetime.now(timezone.utc) + timedelta(minutes=10),
                    member_limit=1
                )

                bot.send_message(
                    chat_id=int(user_id),
                    text=f"✅ تم تفعيل اشتراكك!\n🔗 هذا رابط خاص بك (صالح لمدة 10 دقائق أو استخدام واحد):\n{invite.invite_link}"
                )

            except Exception as e:
                print(f"❌ خطأ أثناء إرسال رابط الدعوة: {e}")
        else:
            print("⚠️ بيانات ناقصة")

    return jsonify(success=True)

if __name__ == "__main__":
    interval = load_settings().get("check_interval_minutes", 2)
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(lambda: asyncio.run(remove_expired_users()), "interval", minutes=interval)
    scheduler.start()
    app.run(port=5000)
