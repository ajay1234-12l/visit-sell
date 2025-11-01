# Configuration settings
# config.py
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

CFG = {
    "SECRET_KEY": "replace_with_a_strong_secret",    # change before prod
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "admin123",
    "VISIT_API_TEMPLATE": "https://visits-api-yash-ff.vercel.app/visit?uid={uid}&region=IND",
    "VISITS_PER_COIN": 1000,
    "RUPEE_PER_COIN": 5.0,
    "SIGNUP_BONUS": 10,
    "HIT_INTERVAL": 10,
    "MAX_CONCURRENT_TASKS_PER_USER": 3,
    "MAX_THREADS_TOTAL": 120,
    "JWT_EXPIRE_DAYS": 7,
    "FILES": {
        "users": os.path.join(DATA_DIR, "users.json"),
        "tasks": os.path.join(DATA_DIR, "tasks.json"),
        "redeems": os.path.join(DATA_DIR, "redeems.json"),
        "audit": os.path.join(DATA_DIR, "audit.json"),
        "settings": os.path.join(DATA_DIR, "settings.json"),
    }
}