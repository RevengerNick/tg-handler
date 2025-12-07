import json
import os
from src.config import SETTINGS_FILE, AVAILABLE_MODELS

# Хранилище АСИНХРОННЫХ сессий чата
ASYNC_CHAT_SESSIONS = {}

SETTINGS = {
    "model_key": "1",
    "voice_key": "1",
    "tts_model_key": "1",
    "sys_global": "",
    "sys_chats": {},
    "blacklist": [],
    # --- НОВЫЕ ПОЛЯ ДЛЯ TELEGRAPH ---
    "telegraph_token": None,  # Токен авторизации (чтобы редактировать свои посты)
    "help_page_path": None,  # Адрес страницы (например, 'Gemini-Bot-Commands-12-08')
    "help_page_url": None  # Полная ссылка
}


def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                for k, v in saved.items():
                    SETTINGS[k] = v

            if "blacklist" not in SETTINGS: SETTINGS["blacklist"] = []

            model_info = AVAILABLE_MODELS.get(SETTINGS.get("model_key", "1"))
            print(f"⚙️ Settings Loaded. Model: {model_info['name']}")
        except Exception as e:
            print(f"⚠️ Settings Load Error: {e}")


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(SETTINGS, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Settings Save Error: {e}")


load_settings()