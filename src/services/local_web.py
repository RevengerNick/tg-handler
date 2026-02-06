import sqlite3
import uuid
import os
from datetime import datetime
from urllib.parse import quote
from src.config import INSTANT_VIEW_RHASH, MY_DOMAIN

DB_PATH = os.path.join(os.getcwd(), "database.db")

async def save_to_local_web(title, markdown_text):
    """Сохраняет статью в локальную БД и возвращает ссылку с Instant View"""
    article_id = str(uuid.uuid4())[:8]
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO articles (id, title, content, date) VALUES (?, ?, ?, ?)",
            (article_id, title, markdown_text, date_str)
        )
        conn.commit()
    except Exception as e:
        print(f"Database Error: {e}")
        return "error_db"
    finally:
        conn.close()

    article_url = f"{MY_DOMAIN}/view/{article_id}"
    encoded_url = quote(article_url, safe='')
    
    # Если задан RHASH, возвращаем ссылку для Instant View, иначе просто ссылку
    if INSTANT_VIEW_RHASH:
        return f"https://t.me/iv?url={encoded_url}&rhash={INSTANT_VIEW_RHASH}"
    return article_url