import asyncio
import time
import os
import re
import platform # Для определения ОС
import psutil   # Для системной инфо
import aiohttp
import markdown
import requests
import shutil
from io import BytesIO
from urllib.parse import quote, urlencode
from PIL import Image
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from telegraph import Telegraph

from src.config import EXCHANGE_KEY, OLX_SEARCH_MODE
from src.services.files import output_path, temporary_directory
from src.state import SETTINGS, save_settings

# Инициализация Telegraph
telegraph_client = Telegraph()

try:
    # 1. Пробуем загрузить токен из настроек
    stored_token = SETTINGS.get("telegraph_token")

    if stored_token:
        telegraph_client = Telegraph(access_token=stored_token)
        print("✅ Telegraph: Logged in with saved token.")
    else:
        # 2. Если токена нет, регистрируем новый аккаунт
        print("🆕 Telegraph: Creating new account...")
        telegraph_client.create_account(short_name='GeminiBot')

        # 3. Сохраняем токен
        SETTINGS["telegraph_token"] = telegraph_client.get_access_token()
        save_settings()
        print("✅ Telegraph: Account created and saved.")
except Exception as e:
    print(f"❌ Telegraph Init Error: {e}")

# --- ВАЛЮТНЫЕ НАСТРОЙКИ ---

CURRENCY_ALIASES = {
    'USD': ['usd', 'dollar', 'dollars', 'доллар', 'доллара', 'долларов', 'бакс', 'баксов', '$'],
    'EUR': ['eur', 'euro', 'euros', 'евро', 'еврей', '€'],
    'RUB': ['rub', 'ruble', 'rubles', 'рубль', 'рубля', 'рублей', 'деревянных', '₽'],
    'UZS': ['uzs', 'sum', 'sums', 'som', 'soms', 'сум', 'сума', 'сумов', 'сомов'],
    'KZT': ['kzt', 'tenge', 'тенге', 'тг'],
    'CNY': ['cny', 'yuan', 'юань', 'юаня', 'юаней', '¥'],
    'GBP': ['gbp', 'pound', 'pounds', 'фунт', 'фунтов', 'стерлингов', '£'],
    'JPY': ['jpy', 'yen', 'yens', 'йена', 'йены', 'иена'],
    'BTC': ['btc', 'bitcoin', 'биток', 'биткоин'],
    'ETH': ['eth', 'ethereum', 'эфир'],
    'UAH': ['uah', 'hryvnia', 'гривна', 'гривны', 'гривен'],
    'BYN': ['byn', 'ruble', 'белруб', 'зайчиков'],
    'KRW': ['krw', 'won', 'вон'],
    'TRY': ['try', 'lira', 'лир', 'лира']
}

CURRENCY_FLAGS = {
    'USD': '🇺🇸', 'EUR': '🇪🇺', 'RUB': '🇷🇺', 'UZS': '🇺🇿',
    'GBP': '🇬🇧', 'JPY': '🇯🇵', 'KZT': '🇰🇿', 'CNY': '🇨🇳',
    'UAH': '🇺🇦', 'BYN': '🇧🇾', 'BTC': '₿', 'ETH': 'Ξ',
    'TRY': '🇹🇷', 'KRW': '🇰🇷'
}

# Значки валют для красивого вывода
CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'RUB': '₽', 'UZS': 'сум',
    'GBP': '£', 'JPY': '¥', 'KZT': '₸', 'CNY': '¥',
    'BTC': '₿', 'ETH': 'Ξ', 'KRW': '₩', 'TRY': '₺',
    'UAH': '₴', 'BYN': 'Br'
}

def normalize_currency(raw_input: str) -> str:
    clean = raw_input.lower().strip()
    for code, aliases in CURRENCY_ALIASES.items():
        if clean == code.lower() or clean in aliases:
            return code
    return clean.upper()


def sanitize_html_for_telegraph(html_content):
    """
    Telegra.ph не поддерживает H1 и H2 в теле статьи.
    Заменяем их на H3 и H4.
    """
    html_content = html_content.replace("<h1>", "<h3>").replace("</h1>", "</h3>")
    html_content = html_content.replace("<h2>", "<h4>").replace("</h2>", "</h4>")
    return html_content


async def update_help_page(title, markdown_text):
    """
    Создает ИЛИ Редактирует страницу помощи.
    """

    def _sync_action():
        try:
            # Конвертация
            html_content = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables'])
            html_content = html_content.replace("\n", "<br>")
            # ВАЖНО: Убираем запрещенные теги
            html_content = sanitize_html_for_telegraph(html_content)

            # Проверяем сохраненную страницу
            path = SETTINGS.get("help_page_path")

            # --- ПОПЫТКА РЕДАКТИРОВАНИЯ ---
            if path:
                try:
                    telegraph_client.edit_page(
                        path=path,
                        title=title,
                        html_content=html_content,
                        author_name="Gemini Userbot"
                    )
                    return SETTINGS["help_page_url"]
                except Exception as e:
                    print(f"⚠️ Edit failed (creating new): {e}")

            # --- СОЗДАНИЕ НОВОЙ ---
            response = telegraph_client.create_page(
                title=title,
                html_content=html_content,
                author_name="Gemini Userbot"
            )

            SETTINGS["help_page_path"] = response['path']
            SETTINGS["help_page_url"] = response['url']
            save_settings()

            return response['url']

        except Exception as e:
            return f"Error Telegraph: {e}"

    return await asyncio.to_thread(_sync_action)


async def create_telegraph_page(title, markdown_text):
    """
    Создает НОВУЮ статью (для .ait и .chatt).
    """

    def _sync_upload():
        try:
            html_content = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables'])
            html_content = html_content.replace("\n", "<br>")
            # ВАЖНО: Убираем запрещенные теги
            html_content = sanitize_html_for_telegraph(html_content)

            for attempt in range(3):
                try:
                    response = telegraph_client.create_page(
                        title=title,
                        html_content=html_content,
                        author_name="Gemini Bot"
                    )
                    return response['url']
                except Exception as e:
                    print(f"Telegraph attempt {attempt} error: {e}")
                    time.sleep(2)
            return "Error: Timeout"
        except Exception as e:
            return f"Error: {e}"

    return await asyncio.to_thread(_sync_upload)


OLX_HTTP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
}


def _build_olx_url(query: str, page: int, price_from: int | None,
                   price_to: int | None, state: str | None) -> str:
    """Собирает один и тот же URL для браузерного и HTTP-режима поиска."""
    url = f"https://www.olx.uz/list/q-{quote(query, safe='')}/"
    params = []
    if page > 1:
        params.append(("page", page))
    if price_from is not None:
        params.append(("search[filter_float_price:from]", price_from))
    if price_to is not None:
        params.append(("search[filter_float_price:to]", price_to))
    if state in {"new", "used"}:
        params.append(("search[filter_enum_state][0]", state))
    return f"{url}?{urlencode(params)}" if params else url


def _create_olx_workbook():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "OLX"
    worksheet.append([
        "Фото", "Ссылка", "Цена", "Название", "Дата/Место", "Состояние",
        "Запрос", "Страница",
    ])
    dimensions = {"A": 22, "B": 15, "C": 20, "D": 40, "E": 25, "F": 15, "G": 30, "H": 10}
    for column, width in dimensions.items():
        worksheet.column_dimensions[column].width = width
    return workbook, worksheet


def _parse_olx_card(card) -> dict | None:
    """Извлекает поля объявления из разметки, полученной любым способом."""
    title_tag = card.find("h6") or card.find("h4")
    link_tag = card.find("a", href=True)
    if not title_tag or not link_tag:
        return None

    href = link_tag["href"]
    link = f"https://www.olx.uz{href}" if href.startswith("/") else href
    price_tag = card.find("p", {"data-testid": "ad-price"})
    location_tag = card.find("p", {"data-testid": "location-date"})
    condition_tag = card.find("span", title=True)
    condition = condition_tag["title"] if condition_tag and len(condition_tag["title"]) < 30 else "-"

    return {
        "title": title_tag.get_text(" ", strip=True),
        "link": link,
        "price": price_tag.get_text(" ", strip=True) if price_tag else "Договорная",
        "location": location_tag.get_text(" ", strip=True) if location_tag else "-",
        "condition": condition,
        "image": card.find("img"),
    }


def _write_olx_row(worksheet, row: int, item: dict, query: str, page: int,
                   photo_label: str) -> None:
    worksheet[f"A{row}"] = photo_label
    worksheet[f"B{row}"] = f'=HYPERLINK("{item["link"]}", "Перейти")'
    worksheet[f"B{row}"].style = "Hyperlink"
    worksheet[f"C{row}"] = item["price"]
    worksheet[f"D{row}"] = item["title"]
    worksheet[f"E{row}"] = item["location"]
    worksheet[f"F{row}"] = item["condition"]
    worksheet[f"G{row}"] = query
    worksheet[f"H{row}"] = page


def _save_olx_report(workbook, first_query: str, suffix: str) -> str:
    safe_query = re.sub(r'[\\/:*?"<>|]', "_", first_query)
    filename = output_path("olx", f"olx_{safe_query}_{suffix}.xlsx")
    workbook.save(filename)
    return filename


def _get_olx_http_page(session: requests.Session, url: str):
    """Делает до двух попыток: OLX иногда кратко закрывает соединение."""
    for attempt in range(2):
        try:
            response = session.get(url, timeout=(5, 25))
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            if attempt == 0:
                print(f"OLX HTTP temporary error: {error}; retrying once.")
                time.sleep(1)
            else:
                print(f"OLX HTTP Error: {error}")
    return None


def _create_olx_driver():
    """Запускает Chromium, а при его отсутствии — Firefox."""
    user_agent = OLX_HTTP_HEADERS["User-Agent"]
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(f"--user-agent={user_agent}")

    chromium_binary = next(
        (path for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(path)),
        None,
    )
    if chromium_binary:
        chrome_options.binary_location = chromium_binary

    try:
        driver_path = os.getenv("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
        service = ChromeService(driver_path) if driver_path else None
        return webdriver.Chrome(service=service, options=chrome_options) if service else webdriver.Chrome(options=chrome_options)
    except Exception as chrome_error:
        firefox_options = FirefoxOptions()
        firefox_options.add_argument("--headless")
        firefox_options.set_preference("general.useragent.override", user_agent)
        try:
            geckodriver_path = os.getenv("GECKODRIVER_PATH") or shutil.which("geckodriver")
            service = FirefoxService(geckodriver_path) if geckodriver_path else None
            return webdriver.Firefox(service=service, options=firefox_options) if service else webdriver.Firefox(options=firefox_options)
        except Exception as firefox_error:
            raise RuntimeError(
                f"Cannot start Chromium ({chrome_error}) or Firefox ({firefox_error})"
            ) from firefox_error


def _scrape_olx_over_http(clean_queries: list[str], max_pages: int,
                          price_from: int | None, price_to: int | None,
                          state: str | None) -> str | None:
    """Запасной режим без Selenium: быстрее и подходит для слабых ARM-устройств.

    OLX может ограничить такие запросы или изменить HTML. Тогда функция вернёт
    ``None`` без падения userbot; в отчёте этот режим намеренно не загружает фото.
    """
    workbook, worksheet = _create_olx_workbook()
    row = 2
    total_found = 0

    with requests.Session() as session:
        session.headers.update(OLX_HTTP_HEADERS)
        for query in clean_queries:
            for page in range(1, max_pages + 1):
                url = _build_olx_url(query, page, price_from, price_to, state)
                print(f"📄 OLX HTTP Query='{query}' Page={page}: {url}")
                response = _get_olx_http_page(session, url)
                if response is None:
                    break

                page_soup = BeautifulSoup(response.text, "html.parser")
                cards = page_soup.select("div[data-cy='l-card']")
                if not cards:
                    print("OLX HTTP: объявления не найдены или страница ограничила запрос.")
                    break

                found_on_page = 0
                for card in cards:
                    item = _parse_olx_card(card)
                    if not item:
                        continue
                    _write_olx_row(worksheet, row, item, query, page, "Без фото (HTTP)")
                    row += 1
                    total_found += 1
                    found_on_page += 1

                if found_on_page == 0 or len(cards) < 5:
                    break

    if total_found == 0:
        return None
    return _save_olx_report(workbook, clean_queries[0], "http")


def _scrape_olx_with_browser(driver, clean_queries: list[str], max_pages: int,
                              with_images: bool, price_from: int | None,
                              price_to: int | None, state: str | None,
                              temp_dir: str) -> str | None:
    workbook, worksheet = _create_olx_workbook()
    row = 2
    total_found = 0

    for query in clean_queries:
        for page in range(1, max_pages + 1):
            url = _build_olx_url(query, page, price_from, price_to, state)
            print(f"📄 OLX browser Query='{query}' Page={page}: {url}")
            driver.get(url)
            time.sleep(2 if page == 1 else 1.5)

            if "Ничего не найдено" in driver.page_source:
                break

            cards = driver.find_elements("css selector", "div[data-cy='l-card']")
            if not cards:
                break

            found_on_page = 0
            for card in cards:
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", card
                    )
                    time.sleep(0.5 if with_images else 0.1)
                    item = _parse_olx_card(BeautifulSoup(card.get_attribute("outerHTML"), "html.parser"))
                    if not item:
                        continue

                    _write_olx_row(
                        worksheet, row, item, query, page,
                        "Фото недоступно" if with_images else "Без фото",
                    )
                    if with_images and item["image"]:
                        srcset = item["image"].get("srcset", "")
                        source = item["image"].get("src") or (srcset.split()[0] if srcset else None)
                        if source and source.startswith("http"):
                            try:
                                image_url = re.sub(r";s=\d+x\d+", ";s=1000x1000", source)
                                response = requests.get(image_url, headers=OLX_HTTP_HEADERS, timeout=(3, 10))
                                if response.status_code == 200:
                                    image = Image.open(BytesIO(response.content))
                                    image.thumbnail((150, 150))
                                    image_path = os.path.join(temp_dir, f"temp_img_{row}.png")
                                    image.save(image_path)
                                    excel_image = ExcelImage(image_path)
                                    excel_image.width = 150
                                    excel_image.height = 120
                                    worksheet.add_image(excel_image, f"A{row}")
                                    worksheet.row_dimensions[row].height = 100
                            except Exception as error:
                                print(f"OLX image error: {error}")

                    row += 1
                    total_found += 1
                    found_on_page += 1
                except Exception as error:
                    print(f"OLX card error: {error}")

            if found_on_page == 0 or len(cards) < 5:
                break

    if total_found == 0:
        return None
    return _save_olx_report(workbook, clean_queries[0], "multi")


async def olx_parser(queries: list, max_pages: int = 1, with_images: bool = True,
                     price_from: int = None, price_to: int = None, state: str = None):
    """Ищет OLX через браузер или HTTP с безопасным резервным переключением."""

    def _scrape():
        clean_queries = [str(query).strip() for query in queries if str(query).strip()]
        if not clean_queries:
            return None
        try:
            max_page_count = max(1, min(int(max_pages), 50))
        except (TypeError, ValueError):
            max_page_count = 1

        if OLX_SEARCH_MODE == "http":
            return _scrape_olx_over_http(
                clean_queries, max_page_count, price_from, price_to, state
            )

        driver = None
        temp_dir = temporary_directory("olx")
        browser_failed = False
        browser_result = None
        try:
            driver = _create_olx_driver()
            browser_result = _scrape_olx_with_browser(
                driver, clean_queries, max_page_count, with_images, price_from,
                price_to, state, temp_dir,
            )
        except Exception as error:
            browser_failed = True
            print(f"OLX browser error: {error}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as error:
                    print(f"OLX browser shutdown error: {error}")
            shutil.rmtree(temp_dir, ignore_errors=True)

        if OLX_SEARCH_MODE == "auto" and (browser_failed or browser_result is None):
            print("OLX: переключаюсь на HTTP-режим без браузера и изображений.")
            return _scrape_olx_over_http(
                clean_queries, max_page_count, price_from, price_to, state
            )
        return browser_result

    return await asyncio.to_thread(_scrape)


async def get_currency(amount, raw_from, raw_to=None):
    """
    Конвертация валют: Красивый и понятный вывод.
    """
    from_cur = normalize_currency(raw_from)
    to_cur = normalize_currency(raw_to) if raw_to else None

    url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_KEY}/latest/{from_cur}"

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                data = await r.json()
    except Exception as e:
        return f"❌ Network Error: {e}"

    if data.get('result') != 'success':
        return f"❌ API Error (Invalid currency: {from_cur})"

    rates = data['conversion_rates']
    flag_from = CURRENCY_FLAGS.get(from_cur, '')

    # Красивое число (10 000.50)
    fmt_amount = f"{amount:,.2f}".replace(",", " ").replace(".", ",")

    # Заголовок сообщения
    res = f"💸 **Конвертация:**\n"
    res += f"{flag_from} **{fmt_amount} {from_cur}** равны:\n\n"

    # Если целевая валюта не задана, берем топ популярных
    if not to_cur:
        targets = ['USD', 'EUR', 'RUB', 'UZS', 'CNY', 'KZT']
    else:
        targets = [to_cur]

    for t in targets:
        # Не конвертируем в саму себя
        if t == from_cur: continue

        if t in rates:
            val = amount * rates[t]
            flag_to = CURRENCY_FLAGS.get(t, '')
            symbol = CURRENCY_SYMBOLS.get(t, '')

            # Форматирование: 1 234.56
            val_str = f"{val:,.2f}".replace(",", " ").replace(".", ",")

            # Строка вида: 🇷🇺 RUB: 9 234,43 ₽
            res += f"{flag_to} {t}: **{val_str} {symbol}**\n"

    # Футер с датой
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    res += f"\n📅 _Курс на {now}_"

    return res


async def get_sys_info():
    """
    Системная информация (Кроссплатформенная, через psutil).
    Работает и на Windows, и на Raspberry Pi.
    """
    try:
        # Определяем ОС
        sys_name = platform.system()

        # 1. CPU & RAM (работает везде)
        cpu_usage = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()

        # 2. Uptime
        uptime_seconds = time.time() - psutil.boot_time()
        m, s = divmod(uptime_seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        uptime_str = f"{int(h)}h {int(m)}m"
        if d > 0: uptime_str = f"{int(d)}d {uptime_str}"

        # 3. Температура (Сложно для Windows, легко для Linux)
        temp = "N/A"
        if sys_name == "Linux":
            try:
                # Пробуем через psutil
                temps = psutil.sensors_temperatures()
                if 'cpu_thermal' in temps:
                    temp = f"{temps['cpu_thermal'][0].current}°C"
                # Фолбэк для RPi (файловый)
                elif os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                        temp = f"{int(f.read()) / 1000:.1f}°C"
            except:
                pass
        else:
            temp = "N/A (Win)"
        model = SETTINGS.get("model_key", "?")

        return (
            f"🖥 **System Info ({sys_name}):**\n"
            f"🌡 Temp: `{temp}`\n"
            f"🧠 CPU: `{cpu_usage}%`\n"
            f"💾 RAM: `{ram.percent}%`\n"
            f"⏱ Uptime: `{uptime_str}`\n"
            f"🤖 AI Model: `{model}`"
        )
    except Exception as e:
        return f"Sys info error: {e}"
