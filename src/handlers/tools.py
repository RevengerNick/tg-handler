import os
import time
import asyncio
from pyrogram import Client, filters
from src.services import edit_or_reply, get_currency, olx_parser, download_video, download_yandex_track, analyze_chat_history
from src.access_filters import AccessFilter


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
            os.remove(path)
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
            return await message.edit(
                "🔍 **OLX Парсер**\n\nПримеры:\n`.olx iphone` (1 стр, с фото)\n`.olx iphone 3` (3 стр, с фото)\n`.olx iphone noimg` (1 стр, без фото)\n`.olx iphone 5 noimg` (5 стр, без фото)")

        # Дефолтные значения
        max_pages = 1
        with_images = True
        query_parts = []

        # Парсим аргументы с конца
        for arg in args[1:]:
            # Проверка на флаг "без картинок"
            if arg.lower() in ["noimg", "noimage", "безфото", "-i"]:
                with_images = False
            # Проверка на количество страниц
            elif arg.isdigit() and int(arg) < 20:  # Ограничим 20 страницами для безопасности
                max_pages = int(arg)
            # Иначе это часть поискового запроса
            else:
                query_parts.append(arg)

        query = " ".join(query_parts)
        if not query:
            return await message.edit("❌ Вы не указали, что искать.")

        mode_text = "с картинками" if with_images else "без картинок (быстро)"
        await message.edit(f"🔍 Паршу OLX: **{query}**\n📄 Страниц: {max_pages}\n🚀 Режим: {mode_text}...")

        f = await olx_parser(query, max_pages, with_images)

        if f:
            await client.send_document(
                message.chat.id,
                f,
                caption=f"📦 **Результаты OLX**\n🔎 Запрос: `{query}`\n📄 Страниц: {max_pages}"
            )
            os.remove(f)
            # Чистим временные картинки
            for i in os.listdir():
                if i.startswith("temp_img_") and i.endswith(".png"): os.remove(i)
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