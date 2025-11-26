import asyncio
import os
import logging
import re
import time
import json
import psutil
from io import BytesIO
from datetime import datetime

# Pyrogram
from pyrogram import Client, filters, idle
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PasswordHashInvalid,
    PhoneCodeExpired
)

# Utils
import aiohttp
import markdown
import yt_dlp
from PIL import Image
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from yandex_music import Client as YMClient
from telegraph import Telegraph
from dotenv import load_dotenv

# Google Gen AI
from google import genai
from google.genai import types

# --- SETUP LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)
logger = logging.getLogger(__name__)

load_dotenv()

# --- CONFIGURATION ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
PHONES = os.getenv("PHONES", "").split(",")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
EXCHANGE_KEY = os.getenv("EXCHANGE_API_KEY")
SETTINGS_FILE = "settings.json"

AVAILABLE_MODELS = {
    "1": {"id": "gemini-2.5-flash", "name": "⚡️ 2.5 Flash (Google Search)", "search": True},
    "2": {"id": "gemini-2.5-pro", "name": "🧠 2.5 Pro (Thinking)", "search": False},
    "3": {"id": "gemini-2.0-flash", "name": "🚀 2.0 Flash (Fast)", "search": False},
}

# --- GLOBAL STATE ---
# Хранилище АСИНХРОННЫХ сессий чата: {chat_id: chat_session_object}
ASYNC_CHAT_SESSIONS = {}

SETTINGS = {
    "model_key": "1",
    "sys_global": "",
    "sys_chats": {}
}

# Telegraph Init
telegraph_client = Telegraph()
try:
    telegraph_client.create_account(short_name='GeminiBot')
except: pass

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                for k, v in saved.items(): SETTINGS[k] = v
            model_info = AVAILABLE_MODELS.get(SETTINGS.get("model_key", "1"))
            print(f"⚙️ Config Loaded. Model: {model_info['name']}")
        except Exception as e: print(f"⚠️ Config Err: {e}")

def save_settings():
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(SETTINGS, f, indent=4, ensure_ascii=False)
    except: pass

load_settings()

# --- INIT CLIENTS ---
ai_client = None
if GEMINI_KEY:
    try:
        ai_client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"❌ Ошибка Init Gemini: {e}")

ym_client = YMClient(YANDEX_TOKEN).init() if YANDEX_TOKEN else None


# --- HELPER FUNCTIONS ---


async def create_telegraph_page(title, markdown_text):
    """
    Конвертирует Markdown в HTML и загружает статью на Telegra.ph.
    Возвращает ссылку.
    """

    def _sync_upload():
        try:
            # 1. Конвертируем ответ Gemini (Markdown) в HTML
            # extensions=['fenced_code'] нужен для красивых блоков кода
            html_content = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables'])

            # 2. Немного магии: Telegraph API не любит чистый HTML, ему нужны параграфы
            # Простейший хак: заменяем переносы строк на <br> если их нет
            html_content = html_content.replace("\n", "<br>")

            # 3. Загружаем
            response = telegraph_client.create_page(
                title=title,
                html_content=html_content,
                author_name="Gemini Userbot"
            )
            return response['url']
        except Exception as e:
            return f"Error Telegraph: {e}"

    return await asyncio.to_thread(_sync_upload)

def smart_split(text, limit=4000):
    """
    Разбивает длинный текст на куски, стараясь не резать слова.
    Лимит 4000 (с запасом до 4096).
    """
    if len(text) <= limit:
        return [text]

    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break

        # Ищем перенос строки ближе к концу лимита
        cut = text[:limit].rfind('\n')
        if cut == -1:
            # Если нет переноса, ищем пробел
            cut = text[:limit].rfind(' ')

        if cut == -1:
            # Если вообще нет разделителей, режем жестко
            cut = limit

        parts.append(text[:cut])
        text = text[cut:].lstrip()  # Убираем пробелы в начале следующего куска
    return parts


async def get_message_context(client, message):
    """
    Извлекает текст и медиа из сообщения, на которое ответили (Reply).
    Возвращает кортеж: (текст_контекста, картинка_PIL_или_None)
    """
    reply = message.reply_to_message
    if not reply:
        return "", None

    # 1. Извлекаем текст
    text_context = reply.text or reply.caption or ""

    # Форматируем, чтобы нейросеть понимала, где чьи слова
    if text_context:
        text_context = f"--- Начало пересылаемого сообщения ---\n{text_context}\n--- Конец пересылаемого сообщения ---\n\n"

    # 2. Извлекаем фото (если есть)
    image = None
    if reply.photo:
        try:
            # Скачиваем фото в память (BytesIO)
            photo_io = await client.download_media(reply, in_memory=True)
            if photo_io:
                image = Image.open(photo_io)
        except Exception as e:
            print(f"Error downloading reply photo: {e}")

    return text_context, image

def format_grounding(text, candidates):
    """Добавляет источники (ссылки) к ответу, если они есть"""
    try:
        # Проверяем, есть ли метаданные поиска
        if not candidates or not candidates[0].grounding_metadata:
            return text

        metadata = candidates[0].grounding_metadata
        if not metadata.grounding_chunks:
            return text

        sources_text = "\n\n🌐 **Источники:**"
        unique_links = set()

        for chunk in metadata.grounding_chunks:
            if chunk.web and chunk.web.uri:
                title = chunk.web.title or "Link"
                if chunk.web.uri not in unique_links:
                    sources_text += f"\n🔹 [{title}]({chunk.web.uri})"
                    unique_links.add(chunk.web.uri)

        return text + sources_text
    except Exception:
        return text


def get_ai_config(chat_id=None):
    """Сборка конфигурации: Модель + Поиск + Инструкции"""
    # 1. Получаем модель
    key = SETTINGS.get("model_key", "1")
    model_info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["1"])

    # 2. Собираем инструкцию (Глобальная + Локальная)
    sys_instr = SETTINGS.get("sys_global", "")
    if chat_id:
        local_sys = SETTINGS.get("sys_chats", {}).get(str(chat_id), "")
        if local_sys:
            sys_instr = f"{sys_instr}\n\n[Context: {local_sys}]".strip()

    # 3. Настраиваем инструменты (Поиск)
    tools = []
    if model_info["search"]:
        # Включаем Google Search Tool
        tools = [types.Tool(google_search=types.GoogleSearch())]

    config = types.GenerateContentConfig(
        system_instruction=sys_instr if sys_instr else None,
        tools=tools,
        # Для 2.5 Flash можно отключить thinking, если нужно быстрее, но пока оставим дефолт
    )

    return model_info["id"], config


async def ask_gemini_oneshot(contents):
    if not ai_client: return "⚠️ API Key missing."
    model_id, config = get_ai_config()
    try:
        response = await ai_client.aio.models.generate_content(
            model=model_id, contents=contents, config=config
        )
        return format_grounding(response.text, response.candidates)
    except Exception as e:
        return f"Gemini Error ({model_id}): {e}"


async def ask_gemini_chat(chat_id, contents):
    if not ai_client: return "⚠️ API Key missing."
    model_id, config = get_ai_config(chat_id)
    try:
        # ASYNC CREATE (Client.aio.chats.create)
        if chat_id not in ASYNC_CHAT_SESSIONS:
            ASYNC_CHAT_SESSIONS[chat_id] = ai_client.aio.chats.create(
                model=model_id, config=config
            )

        chat = ASYNC_CHAT_SESSIONS[chat_id]
        # ASYNC SEND
        response = await chat.send_message(contents)
        return format_grounding(response.text, response.candidates)
    except Exception as e:
        if chat_id in ASYNC_CHAT_SESSIONS: del ASYNC_CHAT_SESSIONS[chat_id]
        return f"Chat Error: {e}"


async def get_sys_info():
    """Получение инфо о системе (для RPi)"""
    try:
        cpu_usage = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())

        # Температура (работает на Linux/RPi)
        temp = "N/A"
        try:
            temps = psutil.sensors_temperatures()
            if 'cpu_thermal' in temps:
                temp = f"{temps['cpu_thermal'][0].current}°C"
        except Exception as e:
            pass

        info = (
            f"🖥 **System Status (RPi):**\n"
            f"🌡 Temp: `{temp}`\n"
            f"🧠 CPU: `{cpu_usage}%`\n"
            f"💾 RAM: `{ram.percent}%` ({ram.used // (1024 * 1024)}MB / {ram.total // (1024 * 1024)}MB)\n"
            f"⏱ Uptime: `{str(uptime).split('.')[0]}`"
        )
        return info
    except Exception as e:
        return f"Sys info error: {e}"


async def download_yandex_track(url: str):
    def _sync_download():
        tracks_paths = []
        try:
            if "track" in url:
                track_id = re.search(r'track/(\d+)', url).group(1)
                tracks = [ym_client.tracks([track_id])[0]]
            elif "album" in url:
                album_id = re.search(r'album/(\d+)', url).group(1)
                album = ym_client.albums_with_tracks(album_id)
                tracks = album.volumes[0]
            else:
                return []

            for track in tracks:
                info = track.get_download_info(get_direct_links=True)
                if not info: continue
                direct_link = info[0].get_direct_link()

                import requests
                track_data = requests.get(direct_link).content

                filename = f"{track.title} - {track.artists[0].name}.mp3"
                # Очистка имени файла от недопустимых символов
                filename = re.sub(r'[\\/*?:"<>|]', "", filename)

                with open(filename, 'wb') as f:
                    f.write(track_data)
                tracks_paths.append(filename)
            return tracks_paths
        except Exception as e:
            logger.error(f"YM Error: {e}")
            return []

    return await asyncio.to_thread(_sync_download)


async def download_video(link: str, quality_mode: int):
    def _sync_dl():
        options = {
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
        }
        if quality_mode == 2:
            options.update({
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            })
        elif quality_mode == 1:
            options.update({'format': 'bestvideo[height<=480]+bestaudio/best'})
        else:
            options.update({'format': 'bestvideo+bestaudio/best'})

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(link, download=True)
            if quality_mode == 2:
                title = info['title']
                # yt-dlp может заменить расширение
                potential_name = f"{title}.mp3"
                # Простая проверка, иногда имя файла сложнее
                return potential_name
            return ydl.prepare_filename(info)

    try:
        return await asyncio.to_thread(_sync_dl)
    except Exception as e:
        logger.error(f"DL Error: {e}")
        return None


async def olx_parser(query: str):
    def _scrape():
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # Маскируемся, чтобы сервер отдавал контент как человеку
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")

        driver = webdriver.Chrome(options=chrome_options)

        # Настройка Excel
        wb = Workbook()
        ws = wb.active
        ws.append(['Фото', 'Ссылка', 'Цена', 'Название', 'Дата/Место', 'Состояние'])

        # Красивые ширины колонок
        dims = {'A': 22, 'B': 15, 'C': 20, 'D': 40, 'E': 25, 'F': 15}
        for col, width in dims.items(): ws.column_dimensions[col].width = width

        try:
            url = f"https://www.olx.uz/list/q-{query}/"
            driver.get(url)
            time.sleep(2)  # Ждем инициализации JS

            # Находим карточки через Selenium, чтобы можно было к ним скроллить
            # Используем CSS селектор по data-cy (надежно)
            card_elements = driver.find_elements("css selector", "div[data-cy='l-card']")

            row = 2
            # Берем первые 10
            for card in card_elements[:10]:
                try:
                    # --- SCROLLING (ВАЖНО ДЛЯ КАРТИНОК) ---
                    # Скроллим к элементу, чтобы сработал Lazy Load
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", card)
                    time.sleep(0.5)  # Даем полсекунды на прогрузку картинки

                    # Теперь парсим HTML уже прогруженной карточки
                    card_html = card.get_attribute('outerHTML')
                    soup = BeautifulSoup(card_html, 'lxml')

                    # 1. Текстовые данные
                    title_tag = soup.find("h6") or soup.find("h4")
                    link_tag = soup.find("a")
                    price_tag = soup.find("p", {"data-testid": "ad-price"})

                    if not (title_tag and link_tag): continue

                    title = title_tag.text.strip()
                    price = price_tag.text.strip() if price_tag else "Договорная"

                    href = link_tag.get("href")
                    link = f"https://www.olx.uz{href}" if href.startswith("/") else href

                    # Доп инфо
                    loc_tag = soup.find("p", {"data-testid": "location-date"})
                    loc_date = loc_tag.text.strip() if loc_tag else "-"
                    cond_tag = soup.find("span", title=True)
                    condition = cond_tag['title'] if cond_tag and len(cond_tag['title']) < 20 else "-"

                    # 2. Обработка КАРТИНКИ (HD Quality)
                    img_tag = soup.find("img")
                    if img_tag:
                        # Пытаемся взять src или srcset
                        img_src = img_tag.get("src") or img_tag.get("srcset", "").split()[0]

                        # Бывает, что src всё еще пустой или base64 заглушка
                        if not img_src or "data:image" in img_src:
                            # Пробуем достать из стилей или других атрибутов, но обычно скролл помогает
                            pass

                        if img_src and "http" in img_src:
                            # --- HD FIX ---
                            # Ссылка обычно выглядит как .../image;s=200x200;...
                            # Меняем размер на большой с помощью Regex
                            hd_src = re.sub(r';s=\d+x\d+', ';s=1000x1000', img_src)

                            import requests
                            resp = requests.get(hd_src, timeout=5)
                            if resp.status_code == 200:
                                img = Image.open(BytesIO(resp.content))
                                img.thumbnail((150, 150))  # Для Excel уменьшаем, но источник был качественный

                                path = f"temp_img_{row}.png"
                                img.save(path)
                                excel_img = ExcelImage(path)
                                excel_img.width = 150;
                                excel_img.height = 120
                                ws.add_image(excel_img, f"A{row}")
                                ws.row_dimensions[row].height = 100

                    # Запись в ячейки
                    ws[f"B{row}"] = f'=HYPERLINK("{link}", "Перейти")'
                    ws[f"B{row}"].style = "Hyperlink"
                    ws[f"C{row}"] = price
                    ws[f"D{row}"] = title
                    ws[f"E{row}"] = loc_date
                    ws[f"F{row}"] = condition

                    row += 1
                except Exception as e:
                    print(f"Item parse err: {e}")
                    continue

            fname = f"olx_{query}_{int(datetime.now().timestamp())}.xlsx"
            wb.save(fname)
            return fname
        finally:
            driver.quit()

    return await asyncio.to_thread(_scrape)


async def get_currency(amount, from_cur, to_cur=None):
    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_KEY}/latest/{from_cur}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()

    if data.get('result') != 'success':
        return "Ошибка API валют"

    rates = data['conversion_rates']
    flags = {'USD': '🇺🇸', 'EUR': '🇪🇺', 'RUB': '🇷🇺', 'UZS': '🇺🇿'}

    result = f"💰 **{amount} {from_cur}** {flags.get(from_cur, '')}\n\n"
    targets = [to_cur] if to_cur else ['USD', 'UZS', 'RUB']

    for t in targets:
        if t in rates:
            val = round(amount * rates[t], 2)
            result += f"{t} {flags.get(t, '')}: {val:,.2f}\n".replace(",", " ")

    return result


# --- BOT HANDLERS REGISTER ---

def register_handlers(app: Client):
    # 0. HELP COMMAND

    async def edit_or_reply(message, text, **kwargs):
        if message.outgoing:
            await message.edit(text, **kwargs)
            return message  # Возвращаем само сообщение
        else:
            # Если чужое - отвечаем реплаем
            return await message.reply(text, **kwargs)

    @app.on_message(filters.command(["help", "помощь"], prefixes="."))
    async def help_cmd(client, message):
        text = (
            "🤖 **FULL COMMAND LIST**\n\n"

            "🧠 **AI (Нейросети):**\n"
            "• `.ai` [вопрос] — Разовый запрос (без памяти)\n"
            "• `.ait` [тема] — Написать статью в Telegraph\n"
            "• `.chat` [текст] — Диалог с памятью контекста\n"
            "• `.chatt` [текст] — Ответ контекста в Telegraph\n"
            "• `.model` [1-3] — Выбор модели (Google Search)\n"
            "• `.history` — Показать последние 10 сообщений\n"
            "• `.reset` — Сброс памяти чата + Бэкап\n\n"

            "🎭 **Роли и Инструкции:**\n"
            "• `.sysglobal` [текст] — Глобальная инструкция (для всех чатов)\n"
            "• `.syschat` [текст] — Инструкция для текущего чата\n"
            "• `.syschat -` — Удалить инструкцию чата\n\n"

            "🛠 **Инструменты:**\n"
            "• `.cal` [выражение] — Калькулятор (2+2*2)\n"
            "• `.dl` [1/2] [ссылка] — Скачать (2=mp3, 1=low, 0=best)\n"
            "• `.olx` [запрос] — Парсинг OLX в Excel (с фото)\n"
            "• `.cur` [100] [USD] — Конвертер валют\n"
            "• `.sys` — Статус сервера (RPi)\n\n"

            "🤡 **Fun & Spam:**\n"
            "• `.sar` [текст] — СдЕлАтЬ сАрКаЗм\n"
            "• `.spam` [число] [текст] — Спам отдельными сообщениями\n"
            "• `.spam0` [число] [текст] — Спам столбиком (в одном смс)\n"
            "• `.spam1` [число] [текст] — Спам в строчку (слитно)\n"
            "• `.shrek`, `.girl`, `.assgirl` — ASCII арты"
        )
        await edit_or_reply(message, text)

    @app.on_message(filters.command(["ai", "аи"], prefixes="."))
    async def ai_handler(client, message):
        try:
            parts = message.text.split(maxsplit=1)
            prompt = parts[1] if len(parts) > 1 else ""
            reply_txt, reply_img = await get_message_context(client, message)

            if not prompt and not reply_txt and not reply_img:
                return await edit_or_reply(message, "🤖 Введите вопрос.")

            m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
            status = await edit_or_reply(message, f"🤖 Думаю ({m_name})...")

            final = f"{reply_txt}Вопрос: {prompt}" if reply_txt else prompt
            content = [reply_img, final] if reply_img else final

            resp = await ask_gemini_oneshot(content)
            chunks = smart_split(f"**Gemini ({m_name}):**\n\n{resp}")

            await status.edit(chunks[0], disable_web_page_preview=True)
            for c in chunks[1:]: await client.send_message(message.chat.id, c, disable_web_page_preview=True)
        except Exception as e:
            await edit_or_reply(message, f"Err: {e}")

    @app.on_message(filters.command(["ait", "аит"], prefixes="."))
    async def ait_handler(client, message):
        try:
            parts = message.text.split(maxsplit=1)
            prompt = parts[1] if len(parts) > 1 else "Analysis"
            reply_txt, reply_img = await get_message_context(client, message)

            m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
            status = await edit_or_reply(message, f"📝 {m_name} пишет статью...")

            final = f"{reply_txt}\nЗадание: {prompt}"
            content = [reply_img, final] if reply_img else final

            resp = await ask_gemini_oneshot(content)
            title = f"AI: {prompt[:30]}..."
            link = await create_telegraph_page(title, resp)

            await status.edit(f"🧠 **Gemini ({m_name}):**\n📄 **Статья:**\n👉 {link}")
        except Exception as e:
            await edit_or_reply(message, f"Err: {e}")

    @app.on_message(filters.command(["cal", "кал", "calc", "счет"], prefixes="."))
    async def calc_handler(client, message):
        try:
            # Получаем выражение
            args = message.text.split(maxsplit=1)
            if len(args) < 2:
                return await edit_or_reply(message, "🔢 Введите выражение: `.cal 2+2`")

            # Убираем пробелы и заменяем некоторые знаки для удобства
            expr = args[1].lower().replace(" ", "")
            expr = expr.replace("х", "*").replace("x", "*")  # Русская и англ Х на умножение
            expr = expr.replace("^", "**")  # Степень
            expr = expr.replace(":", "/")  # Деление
            expr = expr.replace(",", ".")  # Запятая на точку

            # БЕЗОПАСНОСТЬ: Разрешаем только цифры и мат. знаки
            allowed_chars = set("0123456789.+-*/()%**")
            if not set(expr).issubset(allowed_chars):
                return await edit_or_reply(message, "❌ Ошибка: Недопустимые символы.")

            # Считаем
            # eval безопасен здесь, так как мы проверили символы выше
            result = eval(expr, {"__builtins__": None}, {})

            # Форматируем (убираем .0 если число целое)
            if isinstance(result, (int, float)):
                if int(result) == result:
                    result = int(result)
                # Округляем до 4 знаков, если дробь длинная
                else:
                    result = round(result, 4)

            await edit_or_reply(message, f"🔢 **{args[1]}** = `{result}`")

        except ZeroDivisionError:
            await edit_or_reply(message, "❌ Деление на ноль!")
        except Exception as e:
            await edit_or_reply(message, f"❌ Ошибка: {e}")

    @app.on_message(filters.command(["cur", "кон"], prefixes="."))
    async def cur_handler(client, message):
        try:
            a = message.text.split()
            if len(a) < 3: return await edit_or_reply(message, "⚠️ .cur 100 USD")
            res = await get_currency(float(a[1]), a[2].upper(), a[3].upper() if len(a) > 3 else None)
            await edit_or_reply(message, res)
        except:
            await edit_or_reply(message, "Err")

    # 1. AI CHAT (CONTEXT AWARE)
    @app.on_message(filters.me & filters.command(["chat", "чат"], prefixes="."))
    async def chat_handler(client, message):
        try:
            parts = message.text.split(maxsplit=1)
            prompt = parts[1] if len(parts) > 1 else ""

            # Получаем контекст (если был реплай)
            reply_txt, reply_img = await get_message_context(client, message)

            if not prompt and not reply_txt and not reply_img:
                return await message.edit("💬 Введите текст или ответьте на сообщение.")

            # Получаем имя модели
            m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]

            # Статус "Думаю..."
            await message.edit(f"💬 {m_name} думает...")

            # Формируем полный запрос для ИИ
            final_prompt = f"{reply_txt}{prompt}"
            content = [reply_img, final_prompt] if reply_img else final_prompt

            # Делаем запрос
            resp = await ask_gemini_chat(message.chat.id, content)
            chunks = smart_split(resp)

            # Формируем красивый заголовок для первого сообщения
            # Если prompt был пустой (только реплай), пишем "Контекст"
            user_header = f"👤 **Вы:** {prompt}" if prompt else "👤 **Контекст реплая**"

            # Собираем первое сообщение
            first_msg = f"{user_header}\n\n🤖 **{m_name}:**\n{chunks[0]}"

            await message.edit(first_msg, disable_web_page_preview=True)

            # Если ответ длинный, отправляем остальные куски следом
            for c in chunks[1:]:
                await client.send_message(message.chat.id, c, disable_web_page_preview=True)

        except Exception as e:
            await message.edit(f"Err: {e}")

    @app.on_message(filters.me & filters.command(["chatt", "чатт"], prefixes="."))
    async def chatt_handler(client, message):
        try:
            parts = message.text.split(maxsplit=1)
            prompt = parts[1] if len(parts) > 1 else "Продолжай"
            reply_txt, reply_img = await get_message_context(client, message)

            m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
            await message.edit(f"💬📝 {m_name} пишет...")

            final = f"{reply_txt}{prompt}"
            content = [reply_img, final] if reply_img else final

            resp = await ask_gemini_chat(message.chat.id, content)
            link = await create_telegraph_page(f"Context: {prompt[:20]}...", resp)
            await message.edit(f"💬📝 **Ответ (Telegraph):**\n👉 {link}")
        except Exception as e:
            await message.edit(f"Err: {e}")

    @app.on_message(filters.me & filters.command(["history", "история"], prefixes="."))
    async def history_handler(client, message):
        chat_id = message.chat.id
        if chat_id not in ASYNC_CHAT_SESSIONS: return await message.edit("🤷 Нет диалога")
        try:
            chat = ASYNC_CHAT_SESSIONS[chat_id]
            # ASYNC GET HISTORY
            history = chat.get_history()
            text = "📜 **Последние 10 сообщений:**\n\n"
            print (history)
            for i, msg in enumerate(history[-10:], 1):
                role = "👤" if msg.role == "user" else "🤖"
                content = msg.parts[0].text if msg.parts else "[media]"
                text += f"{role}: {content[:60]}...\n"
            await message.edit(text)
        except Exception as e:
            await message.edit(f"Err: {e}")

    @app.on_message(filters.me & filters.command(["reset", "сброс"], prefixes="."))
    async def reset_handler(client, message):
        chat_id = message.chat.id
        if chat_id in ASYNC_CHAT_SESSIONS:
            try:
                chat = ASYNC_CHAT_SESSIONS[chat_id]
                hist = await chat.get_history()

                msgs = []
                for m in hist:
                    msgs.append({'role': m.role, 'content': m.parts[0].text if m.parts else ""})

                fname = f"chat_backup_{chat_id}_{int(time.time())}.json"
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(msgs, f, ensure_ascii=False, indent=2)

                del ASYNC_CHAT_SESSIONS[chat_id]
                await message.edit(f"🧹 Очищено.\n💾 Бэкап: `{fname}`")
            except:
                del ASYNC_CHAT_SESSIONS[chat_id]
                await message.edit("🧹 Очищено.")
        else:
            await message.edit("🧹 Пусто.")

    @app.on_message(filters.me & filters.command(["model", "модель"], prefixes="."))
    async def model_handler(client, message):
        args = message.text.split()
        curr = SETTINGS.get("model_key", "1")
        if len(args) < 2:
            t = "🧠 **Models:**\n\n"
            for k, v in AVAILABLE_MODELS.items():
                mark = "✅" if k == curr else ""
                icon = "🔎" if v["search"] else ""
                t += f"`{k}` — {v['name']} {icon} {mark}\n"
            return await message.edit(t + "\nEx: `.model 2`")

        c = args[1]
        if c in AVAILABLE_MODELS:
            SETTINGS["model_key"] = c;
            save_settings();
            ASYNC_CHAT_SESSIONS.clear()
            m = AVAILABLE_MODELS[c]
            await message.edit(f"✅ Set: `{m['name']}`")
        else:
            await message.edit("❌ Invalid.")

    @app.on_message(filters.me & filters.command(["sysglobal"], prefixes="."))
    async def sysg_handler(client, message):
        if len(message.text.split()) == 1:
            return await message.edit(f"🌐 Global:\n`{SETTINGS.get('sys_global', '-')}`")
        SETTINGS["sys_global"] = message.text.split(maxsplit=1)[1];
        save_settings();
        ASYNC_CHAT_SESSIONS.clear()
        await message.edit(f"🌐 Updated:\n`{SETTINGS['sys_global']}`")

    @app.on_message(filters.me & filters.command(["syschat"], prefixes="."))
    async def sysc_handler(client, message):
        cid = str(message.chat.id)
        if len(message.text.split()) == 1:
            return await message.edit(f"💬 Chat:\n`{SETTINGS.get('sys_chats', {}).get(cid, '-')}`")

        instr = message.text.split(maxsplit=1)[1]
        if "sys_chats" not in SETTINGS: SETTINGS["sys_chats"] = {}

        if instr == "-":
            if cid in SETTINGS["sys_chats"]: del SETTINGS["sys_chats"][cid]
            msg = "🗑 Removed."
        else:
            SETTINGS["sys_chats"][cid] = instr
            msg = f"💬 Set:\n`{instr}`"

        save_settings()
        if message.chat.id in ASYNC_CHAT_SESSIONS: del ASYNC_CHAT_SESSIONS[message.chat.id]
        await message.edit(msg)
    # 4. DOWNLOADER
    @app.on_message(filters.me & filters.command(["dl", "скачать", "дл"], prefixes="."))
    async def dl_handler(client, message):
        args = message.text.split()
        if len(args) < 2:
            return await message.edit("❌ Ссылка?")

        url = args[-1]
        mode = 0
        if len(args) > 2 and args[1].isdigit():
            mode = int(args[1])

        await message.edit("📥 Скачиваю на сервер...")
        path = None

        try:
            if "music.yandex" in url:
                paths = await download_yandex_track(url)
                path = paths[0] if paths else None
            else:
                path = await download_video(url, mode)

            if path and os.path.exists(path):
                await message.edit("📤 Загружаю в Telegram...")

                # Функция прогресс бара
                last_update_time = 0

                async def progress(current, total):
                    nonlocal last_update_time
                    # Обновляем не чаще раза в 2 секунды
                    if time.time() - last_update_time > 2:
                        percent = current * 100 / total
                        try:
                            await message.edit(f"📤 Загрузка: {percent:.1f}%")
                            last_update_time = time.time()
                        except:
                            pass

                await client.send_document(
                    message.chat.id,
                    document=path,
                    caption="✅ Готово",
                    progress=progress
                )
                os.remove(path)
                await message.delete()
            else:
                await message.edit("❌ Ошибка скачивания или файл не найден.")
        except Exception as e:
            await message.edit(f"DL Fatal Error: {e}")

    # 5. OLX PARSER
    @app.on_message(filters.me & filters.command(["olx", "олх"], prefixes="."))
    async def olx_handler_func(client, message):
        try:
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2: return await message.edit("Введите запрос.")

            query = parts[1]
            await message.edit(f"🔍 Паршу OLX: {query}...")
            file_path = await olx_parser(query)

            if file_path:
                await client.send_document(message.chat.id, file_path)
                os.remove(file_path)
                # Чистим картинки
                for f in os.listdir():
                    if f.startswith("temp_img_"): os.remove(f)
                await message.delete()
            else:
                await message.edit("Ничего не найдено.")
        except Exception as e:
            await message.edit(f"OLX Err: {e}")

    # 7. SYSTEM INFO (Raspberry Pi)
    @app.on_message(filters.me & filters.command(["sys", "сис"], prefixes="."))
    async def sys_handler(client, message):
        info = await get_sys_info()
        await message.edit(info)

    @app.on_message(filters.me & filters.command(["s", "c", "с"], prefixes="."))
    async def strip_handler(client, message):
        try:
            # Делим сообщение на ["команда", "остальной_текст"]
            parts = message.text.split(maxsplit=1)

            if len(parts) < 2:
                # Если текста нет, можно ничего не делать или удалить сообщение
                return

            # Берем текст и удаляем ВСЕ пробелы
            clean_text = parts[1].replace(" ", "")

            # Редактируем
            await message.edit(clean_text)
        except Exception as e:
            await message.edit(f"Err: {e}")

    # 8. SPAM
    @app.on_message(filters.me & filters.command(["spam", "спам"], prefixes="."))
    async def spam_handler(client, message):
        try:
            _, count, text = message.text.split(maxsplit=2)
            count = int(count)
            await message.delete()
            for _ in range(count):
                await client.send_message(message.chat.id, text)
                await asyncio.sleep(0.3)
        except:
            pass

    @app.on_message(filters.me & filters.command(["spam0", "спам0"], prefixes="."))
    async def spam_handler(client, message):
        try:
            _, count, text = message.text.split(maxsplit=2)
            count = int(count)
            await message.delete()
            text_message = ''
            for _ in range(count):
                text_message += f"{text}\n"

            await client.send_message(message.chat.id, text_message)
        except:
            pass

    @app.on_message(filters.me & filters.command(["spam1", "спам1"], prefixes="."))
    async def spam_handler(client, message):
        try:
            _, count, text = message.text.split(maxsplit=2)
            count = int(count)
            await message.delete()
            text_message = ''
            for _ in range(count):
                text_message += f"{text}"

            await client.send_message(message.chat.id, text_message)
        except:
            pass

    # 9. SARCASM
    @app.on_message(filters.me & filters.command(["sar", "сар"], prefixes="."))
    async def sar_handler(client, message):
        try:
            text = message.text.split(maxsplit=1)[1]
            res = "".join([c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text)])
            await message.edit(res)
        except:
            pass

    @app.on_message(filters.command(["шрек", "shrek"], prefixes="."))
    async def sar_handler(client, message):
        try:
            mess = """
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⢟⣩⡍⣙⠛⢛⣿⣿⣿⠛⠛⠛⠛⠻⣿⣿⣿⣿
⠙⢿⣿⣿⣿⡿⠿⠛⠛⢛⣧⣿⠇⠄⠂⠄⠄⠄⠘⣿⣿⣿
⣶⣄⣾⣿⢟⣼⠒⢲⡔⣺⣿⣧⠄⠄⣠⠤⢤⡀⠄⠟⠉⣠
⣿⣿⣿⣿⣿⣟⣀⣬⣵⣿⣿⣿⣶⡤⠙⠄⠘⠃⠄⣴⣾⣿
⣿⣿⣿⣿⣿⡿⢻⠿⢿⣿⣿⠿⠋⠁⠄⠂⠉⠒⢘⣿⣿⣿
⣿⣿⣿⣿⡿⣡⣷⣶⣤⣤⣀⡀⠄⠄⠄⠄⠄⠄⠄⣾⣿⣿
⣿⣿⣿⡿⣸⣿⣿⣿⣿⣿⣿⣿⣷⣦⣰⠄⠄⠄⠄⢾⠿⢿
⣾⣿⣿⣿⡟⠉⠉⠈⠉⠉⠉⠉⠉⠄⠄⠄⠑⠄⠄⠐⡇⠄
⣿⣿⣿⡿⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⢠⡇⠄
⣿⣿⣿⣯⠄⢠⡀⠄⠄⠄⠄⠄⠄⠄⠄⣀⠄⠄⠄⠄⠁⠄
⣿⣿⣿⣯⣧⣬⣿⣤⣐⣂⣄⣀⣠⡴⠖⠈⠄⠄⠄⠄⠄⠄
⣿⣿⣿⣿⣿⣿⣿⣿⣽⣉⡉⠉⠈⠁⠄⠁⠄⠄⠄⠄⡂⠄
⣿⠿⣿⣿⣿⣿⣷⡤⠈⠉⠉⠁⠄⠄⠄⠄⠄⠄⠄⠠⠔⠄
⢿⣷⣿⣿⢿⣿⣿⣷⡦⢤⡀⠄⠄⠄⠄⠄⠄⢐⣠⡿⠁⠄
    """
            await edit_or_reply(message, mess)
        except:
            pass

    @app.on_message(filters.me & filters.command(["девушка", "girl"], prefixes="."))
    async def sar_handler(client, message):
        try:
            mess = """
⠄⠄⣿⣿⣿⣿⠘⡿⢛⣿⣿⣿⣿⣿⣧⢻⣿⣿⠃⠸⣿⣿⣿⠄⠄⠄⠄⠄
⠄⠄⣿⣿⣿⣿⢀⠼⣛⣛⣭⢭⣟⣛⣛⣛⠿⠿⢆⡠⢿⣿⣿⠄⠄⠄⠄⠄
⠄⠄⠸⣿⣿⢣⢶⣟⣿⣖⣿⣷⣻⣮⡿⣽⣿⣻⣖⣶⣤⣭⡉⠄⠄⠄⠄⠄
⠄⠄⠄⢹⠣⣛⣣⣭⣭⣭⣁⡛⠻⢽⣿⣿⣿⣿⢻⣿⣿⣿⣽⡧⡄⠄⠄⠄
⠄⠄⠄⠄⣼⣿⣿⣿⣿⣿⣿⣿⣿⣶⣌⡛⢿⣽⢘⣿⣷⣿⡻⠏⣛⣀⠄⠄
⠄⠄⠄⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⠙⡅⣿⠚⣡⣴⣿⣿⣿⡆⠄
⠄⠄⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⠄⣱⣾⣿⣿⣿⣿⣿⣿⠄
⠄⢀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢸⣿⣿⣿⣿⣿⣿⣿⣿⠄
⠄⣸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠣⣿⣿⣿⣿⣿⣿⣿⣿⣿⠄
⠄⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⠛⠑⣿⣮⣝⣛⠿⠿⣿⣿⣿⣿⠄
⢠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⠄⠄⠄⠄⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠄ 
                """
            await message.edit(mess)
        except:
            pass

    @app.on_message(filters.me & filters.command(["дэвушка", "assgirl"], prefixes="."))
    async def sar_handler(client, message):
        try:
            mess = """
⣿⣿⣿⣿⠛⠛⠉⠄⠁⠄⠄⠉⠛⢿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⡟⠁⠄⠄⠄⠄⠄⠄⠄⠄⠄⠄⣿⣿⣿⣿⣿⣿⣿
⣿⣿⡇⠄⠄⠄⠐⠄⠄⠄⠄⠄⠄⠄⠠⣿⣿⣿⣿⣿⣿
⣿⣿⡇⠄⢀⡀⠠⠃⡐⡀⠠⣶⠄⠄⢀⣿⣿⣿⣿⣿⣿
⣿⣿⣶⠄⠰⣤⣕⣿⣾⡇⠄⢛⠃⠄⢈⣿⣿⣿⣿⣿⣿
⣿⣿⣿⡇⢀⣻⠟⣻⣿⡇⠄⠧⠄⢀⣾⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣟⢸⣻⣭⡙⢄⢀⠄⠄⠄⠈⢹⣯⣿⣿⣿⣿⣿
⣿⣿⣿⣭⣿⣿⣿⣧⢸⠄⠄⠄⠄⠄⠈⢸⣿⣿⣿⣿⣿
⣿⣿⣿⣼⣿⣿⣿⣽⠘⡄⠄⠄⠄⠄⢀⠸⣿⣿⣿⣿⣿
⡿⣿⣳⣿⣿⣿⣿⣿⠄⠓⠦⠤⠤⠤⠼⢸⣿⣿⣿⣿⣿
⡹⣧⣿⣿⣿⠿⣿⣿⣿⣿⣿⣿⣿⢇⣓⣾⣿⣿⣿⣿⣿
⡞⣸⣿⣿⢏⣼⣶⣶⣶⣶⣤⣶⡤⠐⣿⣿⣿⣿⣿⣿⣿
⣯⣽⣛⠅⣾⣿⣿⣿⣿⣿⡽⣿⣧⡸⢿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⡷⠹⠛⠉⠁⠄⠄⠄⠄⠄⠄⠐⠛⠻⣿⣿⣿⣿
⣿⣿⣿⠃⠄⠄⠄⠄⠄⣠⣤⣤⣤⡄⢤⣤⣤⣤⡘⠻⣿
⣿⣿⡟⠄⠄⣀⣤⣶⣿⣿⣿⣿⣿⣿⣆⢻⣿⣿⣿⡎⠝
⣿⡏⠄⢀⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡎⣿⣿⣿⣿⠐
⣿⡏⣲⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢇⣿⣿⣿⡟⣼
⣿⡠⠜⣿⣿⣿⣿⣟⡛⠿⠿⠿⠿⠟⠃⠾⠿⢟⡋⢶⣿
⣿⣧⣄⠙⢿⣿⣿⣿⣿⣿⣷⣦⡀⢰⣾⣿⣿⡿⢣⣿⣿
⣿⣿⣿⠂⣷⣶⣬⣭⣭⣭⣭⣵⢰⣴⣤⣤⣶⡾⢐⣿⣿
⣿⣿⣿⣷⡘⣿⣿⣿⣿⣿⣿⣿⢸⣿⣿⣿⣿⢃⣼⣿⣿
                    """
            await message.edit(mess)
        except:
            pass

    # DEBUG
    @app.on_message()
    async def debug_monitor(client, message):
        # Проверяем, есть ли текст, если нет - берем подпись, если нет - пишем тип
        text_content = message.text or message.caption or f"[{message.media or 'Service Message'}]"

        # Безопасное получение ID отправителя (в каналах from_user может не быть)
        user_id = message.from_user.id if message.from_user else message.chat.id

        # Заменяем переносы строк на пробелы для лога, чтобы не засорять консоль
        clean_text = text_content.replace("\n", " ")
        print(f"DEBUG: Msg from {user_id}: {clean_text[:50]}...")

        message.continue_propagation()

def create_app(phone: str):
    clean_phone = re.sub(r'\D', '', phone)
    app = Client(
        name=f"sessions/{clean_phone}",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=phone
    )
    register_handlers(app)
    return app


# --- AUTHENTICATION ---

async def interactive_auth(app: Client):
    print(f"🔄 Check session: {app.name}")
    try:
        await app.connect()
    except Exception as e:
        print(f"Conn err: {e}")
        return False

    try:
        me = await app.get_me()
        print(f"✅ Active: {me.first_name}")
        await app.disconnect()
        return True
    except Exception:
        print("👤 Login required...")

    try:
        sent_code = await app.send_code(app.phone_number)
    except Exception as e:
        print(f"❌ Send code err: {e}")
        await app.disconnect()
        return False

    while True:
        code = input(f"📩 Code for {app.phone_number}: ").strip()
        try:
            await app.sign_in(app.phone_number, sent_code.phone_code_hash, code)
            break
        except PhoneCodeInvalid:
            print("❌ Invalid code.")
        except PhoneCodeExpired:
            print("❌ Expired.")
            await app.disconnect();
            return False
        except SessionPasswordNeeded as e:
            print("🔐 2FA Enabled.")
            hint = getattr(e, "hint", e.password_hint if hasattr(e, "password_hint") else None)
            if hint: print(f"💡 Hint: {hint}")

            while True:
                password = input("🔑 Password: ").strip()
                try:
                    await app.check_password(password)
                    break
                except PasswordHashInvalid:
                    print("❌ Wrong password.")
            break

    await app.disconnect()
    return True


# --- MAIN ---

async def main():
    if not os.path.exists("sessions"):
        os.makedirs("sessions")

    apps_pool = []
    for phone in PHONES:
        clean = phone.strip()
        if clean: apps_pool.append(create_app(clean))

    if not apps_pool:
        print("❌ PHONES missing.")
        return

    # Auth Loop
    valid_apps = []
    print("\n--- AUTH PHASE ---")
    for app in apps_pool:
        if await interactive_auth(app):
            valid_apps.append(app)

    if not valid_apps:
        print("❌ No valid clients.")
        return

    # Start Loop
    print("\n--- START PHASE ---")
    started_apps = []
    for app in valid_apps:
        try:
            await app.start()
            me = await app.get_me()
            print(f"🟢 Started: {me.first_name}")
            started_apps.append(app)
        except Exception as e:
            print(f"❌ Fail start {app.name}: {e}")

    if not started_apps: return

    print("🤖 Bot Running. Press Ctrl+P -> Ctrl+Q to detach.")
    await idle()

    for app in started_apps:
        if app.is_connected: await app.stop()


if __name__ == "__main__":
    asyncio.run(main())