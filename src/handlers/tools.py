import os
import re
import time
import asyncio
from pyrogram import Client, filters
from src.services import edit_or_reply, get_currency, olx_parser, download_video, download_yandex_track, analyze_chat_history
from src.access_filters import AccessFilter
from src.services.files import remove_generated_file


# --- КАЛЬКУЛЯТОР ---
@Client.on_message(filters.command(["cal", "кал", "calc", "счет"], prefixes=".") & AccessFilter)
async def calc_handler(client, message):
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            return await edit_or_reply(message, "🔢 Введите выражение: `.cal 2+2`")

        # Убираем пробелы и заменяем символы
        expr = args[1].lower().replace(" ", "")
        expr = expr.replace("х", "*").replace("x", "*")  # Русская и англ Х
        expr = expr.replace("^", "**")
        expr = expr.replace(":", "/")
        expr = expr.replace(",", ".")

        # Безопасность
        if not set(expr).issubset(set("0123456789.+-*/()%**")):
            return await edit_or_reply(message, "❌ Ошибка: Недопустимые символы.")

        res = eval(expr, {"__builtins__": None}, {})

        # Форматирование
        if isinstance(res, (int, float)):
            if int(res) == res:
                res = int(res)
            else:
                res = round(res, 4)

        await edit_or_reply(message, f"🔢 **{args[1]}** = `{res}`")
    except ZeroDivisionError:
        await edit_or_reply(message, "❌ Деление на ноль!")
    except Exception as e:
        await edit_or_reply(message, f"❌ Ошибка: {e}")


# --- ВАЛЮТА (УЛУЧШЕННАЯ) ---
# Добавили алиасы: .валюта, .exchange, .курс
@Client.on_message(filters.command(["cur", "кон", "кур", "валюта", "курс", "exchange"], prefixes=".") & AccessFilter)
async def cur_handler(client, message):
    try:
        args = message.text.split()

        # Проверка на дурака (просто .cur)
        if len(args) < 3:
            return await edit_or_reply(message, "⚠️ Пример: `.валюта 100 долларов` или `.cur 50 EUR UZS`")

        # Парсинг аргументов
        # 1. Сумма (всегда второй элемент)
        try:
            amount = float(args[1].replace(",", "."))
        except ValueError:
            return await edit_or_reply(message, "⚠️ Ошибка: Сумма должна быть числом (например, 100 или 10.5)")

        # 2. Исходная валюта (третий элемент)
        # Здесь может быть "долларов", "USD", "баксов"
        raw_from = args[2]

        # 3. Целевая валюта (четвертый элемент, опционально)
        raw_to = args[3] if len(args) > 3 else None

        # Вызов сервиса (нормализация внутри)
        res = await get_currency(amount, raw_from, raw_to)
        await edit_or_reply(message, res)

    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["stat", "стат", "анализ"], prefixes=".") & AccessFilter)
async def stats_handler(client, message):
    args = message.text.split()
    days = 30  # По умолчанию месяц

    if len(args) > 1:
        param = args[1].lower()
        if "год" in param or "year" in param:
            days = 365
        elif "недел" in param or "week" in param:
            days = 7
        elif "день" in param or "day" in param:
            days = 1
        elif param.isdigit():
            days = int(param)

    # Запускаем анализ
    await analyze_chat_history(client, message, period_days=days)

# --- УДАЛЕНИЕ ПРОБЕЛОВ ---
@Client.on_message(filters.command(["s", "c", "с"], prefixes=".") & AccessFilter)
async def strip_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            clean_text = parts[1].replace(" ", "")
            await message.edit(clean_text)
    except:
        pass


# --- ЗАГРУЗЧИК (Только админ) ---
@Client.on_message(filters.me & filters.command(["dl", "скачать", "дл"], prefixes="."))
async def dl_handler(client, message):
    args = message.text.split()
    if len(args) < 2:
        return await message.edit("❌ Ссылка?")

    url = args[-1]
    # Определение режима (0-best, 1-low, 2-audio)
    mode = 0
    if len(args) > 2 and args[1].isdigit():
        mode = int(args[1])

    await message.edit("📥 Скачиваю на сервер...")
    try:
        path = None
        if "music.yandex" in url:
            paths = await download_yandex_track(url)
            path = paths[0] if paths else None
        else:
            path = await download_video(url, mode)

        if path and os.path.exists(path):
            await message.edit("📤 Загружаю в Telegram...")

            # Прогресс бар
            last_update_time = 0

            async def progress(current, total):
                nonlocal last_update_time
                if time.time() - last_update_time > 2:
                    percent = current * 100 / total
                    try:
                        await message.edit(f"📤 Загрузка: {percent:.1f}%"); last_update_time = time.time()
                    except:
                        pass

            await client.send_document(message.chat.id, path, caption="✅ Готово", progress=progress)
            remove_generated_file(path)
            await message.delete()
        else:
            await message.edit("❌ Ошибка скачивания или файл не найден.")
    except Exception as e:
        await message.edit(f"DL Fatal Error: {e}")

# --- OLX ПАРСЕР (Только админ) ---
@Client.on_message(filters.me & filters.command(["olx", "олх"], prefixes="."))
async def olx_handler(client, message):
    try:
        args = message.text.split()
        if len(args) < 2:
            help_text = """🔍 **OLX Парсер**

**Базовый поиск:**
`.olx iphone` - 1 стр, с фото
`.olx iphone p=3` - 3 стр, с фото
`.olx iphone noimg` - без фото (быстрее)

**Несколько запросов в один файл:**
`.olx Phillips, Braun, Tefal p=5` - всё в 1 xlsx

**Фильтры по цене:**
`.olx iphone from=100000` - от 100,000 сум
`.olx iphone to=500000` - до 500,000 сум
`.olx iphone from=100000 to=500000` - диапазон

**Фильтр по состоянию:**
`.olx iphone state=new` - только новые
`.olx iphone state=used` - только б/у

**Комбинировано:**
`.olx iphone p=5 from=100000 to=500000 state=new noimg`
(5 стр, цена 100к-500к, новые, без фото)"""
            return await message.edit(help_text)

        # Дефолтные значения
        max_pages = 1
        with_images = True
        price_from = None
        price_to = None
        state = None
        query_parts = []

        # Парсим аргументы
        for arg in args[1:]:
            arg_lower = arg.lower()

            if arg_lower in ["noimg", "noimage", "безфото", "-i"]:
                with_images = False
            elif arg_lower.startswith("p=") or arg_lower.startswith("стр=") or arg_lower.startswith("pages="):
                try:
                    max_pages = int(arg.split("=")[1])
                    if max_pages < 1 or max_pages > 50:
                        max_pages = 1
                except:
                    pass
            elif arg_lower.startswith("from=") or arg_lower.startswith("от="):
                try:
                    price_from = int(arg.split("=")[1].replace(" ", "").replace(",", ""))
                except:
                    pass
            elif arg_lower.startswith("to=") or arg_lower.startswith("до="):
                try:
                    price_to = int(arg.split("=")[1].replace(" ", "").replace(",", ""))
                except:
                    pass
            elif arg_lower.startswith("state=") or arg_lower.startswith("сост="):
                state_val = arg.split("=")[1].lower()
                if state_val in ["new", "новый", "новое", "новая"]:
                    state = "new"
                elif state_val in ["used", "б/у", "б\у", "бу"]:
                    state = "used"
            else:
                query_parts.append(arg)

        raw_query = " ".join(query_parts)
        if not raw_query:
            return await message.edit("❌ Вы не указали, что искать.")

        # Разделители: запятая, точка с запятой, слеш
        queries = [q.strip() for q in re.split(r'[,;/]', raw_query) if q.strip()]
        if not queries:
            return await message.edit("❌ Вы не указали, что искать.")

        # Формируем текст статуса
        filters_text = []
        if price_from:
            filters_text.append(f"от {price_from:,} сум")
        if price_to:
            filters_text.append(f"до {price_to:,} сум")
        if state:
            state_ru = "новое" if state == "new" else "б/у"
            filters_text.append(f"сост: {state_ru}")

        filters_str = " | ".join(filters_text) if filters_text else "без фильтров"
        mode_text = "с фото" if with_images else "без фото"

        total = len(queries)
        multi_mode = total > 1

        await message.edit(
            f"🔍 **OLX Поиск{'и' if multi_mode else ''}**\n"
            f"📦 Запрос{'ы' if multi_mode else ''}: `{', '.join(queries)}`\n"
            f"📄 Страниц: {max_pages}\n"
            f"⚙️ Фильтры: {filters_str}\n"
            f"🚀 Режим: {mode_text}..."
        )

        f = await olx_parser(queries, max_pages, with_images, price_from, price_to, state)

        if f:
            caption = f"📦 **Результаты OLX**\n🔎 `{', '.join(queries)}`\n📄 Страниц: {max_pages}"
            if filters_text:
                caption += f"\n⚙️ Фильтры: {filters_str}"
            if multi_mode:
                caption += f"\n🔢 Запросов: {total}"

            await client.send_document(message.chat.id, f, caption=caption)
            remove_generated_file(f)
            await message.delete()
        else:
            await message.edit("❌ Ничего не найдено или ошибка парсера.")

    except Exception as e:
        await message.edit(f"OLX Err: {e}")


# --- SPAM (Только админ) ---
@Client.on_message(filters.me & filters.command(["spam", "спам"], prefixes="."))
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


@Client.on_message(filters.me & filters.command(["spam0", "спам0"], prefixes="."))
async def spam0_handler(client, message):
    try:
        _, count, text = message.text.split(maxsplit=2)
        count = int(count)
        await message.delete()
        msg = (text + "\n") * count
        await client.send_message(message.chat.id, msg)
    except:
        pass


@Client.on_message(filters.me & filters.command(["spam1", "спам1"], prefixes="."))
async def spam1_handler(client, message):
    try:
        _, count, text = message.text.split(maxsplit=2)
        count = int(count)
        await message.delete()
        msg = text * count
        await client.send_message(message.chat.id, msg)
    except:
        pass


# --- FUN / ARTS ---
@Client.on_message(filters.command(["sar", "сар"], prefixes=".") & AccessFilter)
async def sar_handler(client, message):
    try:
        text = message.text.split(maxsplit=1)[1]
        res = "".join([c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text)])
        await edit_or_reply(message, res)
    except:
        pass


@Client.on_message(filters.command(["шрек", "shrek"], prefixes=".") & AccessFilter)
async def shrek_handler(client, message):
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


@Client.on_message(filters.command(["девушка", "girl"], prefixes=".") & AccessFilter)
async def girl_handler(client, message):
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
    await edit_or_reply(message, mess)


@Client.on_message(filters.command(["дэвушка", "assgirl"], prefixes=".") & AccessFilter)
async def assgirl_handler(client, message):
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
    await edit_or_reply(message, mess)
