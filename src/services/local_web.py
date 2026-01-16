import sqlite3
import uuid
import os
from datetime import datetime
from urllib.parse import quote  # Для кодирования URL
from src.state import SETTINGS
from src.config import INSTANT_VIEW_RHASH  # Импортируем rhash

# Путь к базе данных
DB_PATH = os.path.join(os.getcwd(), "database.db")


async def save_to_local_web(title, markdown_text):
    article_id = str(uuid.uuid4())[:8]
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Твой домен из .env
    domain = os.getenv("MY_DOMAIN", "http://localhost:8000")

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO articles (id, title, content, date) VALUES (?, ?, ?, ?)",
            (article_id, title, markdown_text, date_str)
        )
        conn.commit()
    finally:
        conn.close()

    # Формируем ссылку на статью
    article_url = f"{domain}/view/{article_id}"

    # --- ГЕНЕРАЦИЯ IV ССЫЛКИ ---
    # Кодируем URL для передачи в параметре
    encoded_url = quote(article_url, safe='')

    # Возвращаем ссылку с rhash
    return f"https://t.me/iv?url={encoded_url}&rhash={INSTANT_VIEW_RHASH}"