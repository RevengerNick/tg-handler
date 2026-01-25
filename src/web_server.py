import os
import sqlite3
import markdown
import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uuid
import datetime
# Инициализация FastAPI
app = FastAPI()

# --- ПУТИ ---
# Определяем пути относительно КОРНЯ проекта, а не папки src
# Это важно, чтобы сервер находил файлы, когда запускается из папки tg-handler
BASE_DIR = os.getcwd()
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "src", "templates")
DB_PATH = os.path.join(BASE_DIR, "database.db")

class ArticleModel(BaseModel):
    title: str
    content: str

# Создаем папки, если их нет
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# --- НАСТРОЙКА ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- БАЗА ДАННЫХ (SQLite) ---
# Создаем таблицу при старте сервера, если её нет.
try:
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS articles
                    (
                        id
                        TEXT
                        PRIMARY
                        KEY,
                        title
                        TEXT,
                        content
                        TEXT,
                        date
                        TEXT
                    )''')
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully.")
except Exception as e:
    print(f"❌ Database init error: {e}")


# --- РОУТЫ ---
@app.post("/api/create")
async def create_article(article: ArticleModel):
    """API для создания статьи ботом"""
    article_id = str(uuid.uuid4())[:8]  # Генерируем короткий ID
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO articles (id, title, content, date) VALUES (?, ?, ?, ?)",
        (article_id, article.title, article.content, date_str)
    )
    conn.commit()
    conn.close()

    # Возвращаем боту ID новой статьи
    return {"status": "ok", "id": article_id, "url": f"/view/{article_id}"}
@app.get("/", response_class=HTMLResponse)
async def index():
    """Главная страница (заглушка)"""
    return "<h1>Gemini Userbot Web Server is running</h1><p>Ready to serve articles.</p>"


@app.get("/view/{article_id}", response_class=HTMLResponse)
async def view_article(request: Request, article_id: str):
    """Отображение статьи по её ID"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени

    # Ищем статью
    article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()

    # Если не нашли - 404
    if not article:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    # 1. Готовим описание для Open Graph (Rich Preview)
    # Удаляем Markdown символы и берем первые 150 символов
    description = re.sub(r'[#*`_]', '', article['content'])[:150] + "..."

    # 2. Конвертируем основной Markdown в HTML
    # nl2br добавляет <br> на переносах строк
    html_body = markdown.markdown(article['content'], extensions=['fenced_code', 'tables', 'nl2br'])

    # 3. Рендерим шаблон, передавая в него данные
    return templates.TemplateResponse("article.html", {
        "request": request,
        "title": article['title'],
        "content": html_body,
        "date": article['date'],
        "description": description,
        "article_id": article_id
    })