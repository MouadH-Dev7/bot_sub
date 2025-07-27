# db_utils.py
import json
import os
from datetime import datetime, timezone

DB_FILE = "db.json"  # يمكنك لاحقًا استبداله بقاعدة بيانات حقيقية

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

# ✅ تعديل هنا: end_date يجب أن يتم تمريره من الخارج
def add_user(user_id, username, end_date):
    db = load_db()
    db[str(user_id)] = {
        "username": username,
        "end_date": end_date,
        "notified": False
    }
    save_db(db)

def get_user_end_date(user_id):
    db = load_db()
    user_data = db.get(str(user_id))
    return user_data["end_date"] if user_data else None

def update_user(user_id, **kwargs):
    db = load_db()
    if str(user_id) in db:
        db[str(user_id)].update(kwargs)
        save_db(db)

def delete_user(user_id):
    db = load_db()
    if str(user_id) in db:
        del db[str(user_id)]
        save_db(db)

def get_all_users():
    return load_db()

def get_user_stats():
    db = load_db()
    total = len(db)
    now = datetime.now(timezone.utc)
    active = 0
    expired = 0
    for user in db.values():
        try:
            end = datetime.fromisoformat(user["end_date"])
            if end > now:
                active += 1
            else:
                expired += 1
        except:
            pass
    return {"total": total, "active": active, "expired": expired}

def search_users(keyword):
    db = load_db()
    result = {}
    for uid, user in db.items():
        if keyword.lower() in uid or keyword.lower() in user.get("username", "").lower():
            result[uid] = user
    return result
