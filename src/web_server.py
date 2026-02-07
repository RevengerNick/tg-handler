import os
import sqlite3
import markdown
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from src.config import ROOT_DIR, MY_DOMAIN, INSTANT_VIEW_RHASH
import uuid
import datetime

app = FastAPI()

BASE_DIR = ROOT_DIR
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "src", "templates")
DB_PATH = os.path.join(BASE_DIR, "database.db")

class ArticleModel(BaseModel):
    title: str
    content: str

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Инициализация БД
try:
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS articles
                    (
                        id TEXT PRIMARY KEY,
                        title TEXT,
                        content TEXT,
                        date TEXT
                    )''')
    conn.commit()
    conn.close()
    print("✅ Web Server: Database initialized.")
except Exception as e:
    print(f"❌ Web Server: Database error: {e}")

@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>Gemini Userbot Web Server is running</h1>"

@app.get("/view/{article_id}", response_class=HTMLResponse)
async def view_article(request: Request, article_id: str):
    """Отображение статьи по её ID"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()

    if not article:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    # Простая предобработка Markdown для красоты
    html_body = markdown.markdown(article['content'], extensions=['fenced_code', 'tables', 'nl2br'])
    description = re.sub(r'[#*`_]', '', article['content'])[:150] + "..."

    return templates.TemplateResponse("article.html", {
        "request": request,
        "title": article['title'],
        "content": html_body,
        "date": article['date'],
        "description": description,
        "article_id": article_id
    })