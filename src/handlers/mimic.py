import asyncio
import random

import pyrogram
from pyrogram import Client, filters
from src.services.mimic import learn_user_style, get_mimic_response
from src.services import edit_or_reply
from src.state import SETTINGS, save_settings, MIMIC_STATE
from src.access_filters import AccessFilter


# 1. Обучение (.learn 30)
@Client.on_message(filters.command(["learn", "изучи"], prefixes=".") & AccessFilter)
async def learn_handler(client, message):
    try:
        args = message.text.split()
        days = 30
        if len(args) > 1 and args[1].isdigit():
            days = int(args[1])
        await learn_user_style(client, message, days)
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


# 2. Вкл/Выкл Мимикрии
@Client.on_message(filters.command(["mimic", "auto", "авто"], prefixes=".") & AccessFilter)
async def toggle_mimic_handler(client, message):
    chat_id = message.chat.id

    if chat_id in SETTINGS["mimic_chats"]:
        SETTINGS["mimic_chats"].remove(chat_id)
        # Если была активная задача таймера - отменяем
        if chat_id in MIMIC_STATE["tasks"]:
            MIMIC_STATE["tasks"][chat_id].cancel()
            del MIMIC_STATE["tasks"][chat_id]

        save_settings()
        # Просто удаляем команду, как просил. Если ошибка - не страшно.
        try:
            await message.delete()
        except:
            pass
        # Для отладки можно раскомментить:
        # await edit_or_reply(message, "🤖 Mimic OFF")
    else:
        SETTINGS["mimic_chats"].append(chat_id)
        save_settings()
        try:
            await message.delete()
        except:
            pass


# --- ФОНОВАЯ ЗАДАЧА ОТВЕТА ---
async def mimic_delay_worker(client, chat_id):
    """
    Ждет рандомное время, потом забирает всё из буфера и отвечает.
    """
    try:
        # 1. Ждем (Имитация занятости)
        # Рандом от 40 до 300 секунд (можно до 600, но для тестов лучше меньше)
        delay = random.randint(40, 180)
        print(f"🤖 Mimic: Waiting {delay}s for chat {chat_id}...")

        await asyncio.sleep(delay)

        # 2. Проверяем, не выключили ли режим за это время
        if chat_id not in SETTINGS["mimic_chats"]:
            return

        # 3. Забираем сообщения из буфера
        if chat_id in MIMIC_STATE["buffers"] and MIMIC_STATE["buffers"][chat_id]:
            incoming_msgs = MIMIC_STATE["buffers"][chat_id]
            # Очищаем буфер СРАЗУ, чтобы новые сообщения шли в следующий пакет
            MIMIC_STATE["buffers"][chat_id] = []

            # 4. Генерируем ответ
            # Ставим статус "печатает" (typing) перед ответом
            await client.send_chat_action(chat_id, pyrogram.enums.ChatAction.TYPING)
            await asyncio.sleep(random.randint(2, 5))  # Типа печатает

            response_text = await get_mimic_response(incoming_msgs)

            if response_text:
                # 5. Разбиваем на сообщения (по переносам строк)
                # Это и есть эмуляция "отдельных сообщений"
                messages_to_send = [line for line in response_text.split('\n') if line.strip()]

                for msg_part in messages_to_send:
                    await client.send_message(chat_id, msg_part)
                    # Небольшая пауза между отправкой сообщений (как человек жмет Enter)
                    await asyncio.sleep(random.uniform(0.5, 2.0))

    except asyncio.CancelledError:
        pass  # Задача отменена (режим выключили)
    except Exception as e:
        print(f"Mimic Worker Error: {e}")
    finally:
        # Удаляем себя из списка активных задач
        if chat_id in MIMIC_STATE["tasks"]:
            del MIMIC_STATE["tasks"][chat_id]


# 3. WATCHER (Слушает входящие)
@Client.on_message(filters.incoming & ~filters.bot & ~filters.service)
async def mimic_watcher(client, message):
    chat_id = message.chat.id

    # Если режим выключен - игнор
    if chat_id not in SETTINGS.get("mimic_chats", []):
        return

    # Игнорируем команды
    text = message.text or message.caption
    if not text or text.startswith(".") or text.startswith("/"):
        return

    # 1. Добавляем сообщение в буфер
    if chat_id not in MIMIC_STATE["buffers"]:
        MIMIC_STATE["buffers"][chat_id] = []

    MIMIC_STATE["buffers"][chat_id].append(text)

    # 2. Если таймер уже тикает - ничего не делаем, просто копим буфер
    if chat_id in MIMIC_STATE["tasks"]:
        return

    # 3. Если таймера нет - запускаем
    task = asyncio.create_task(mimic_delay_worker(client, chat_id))
    MIMIC_STATE["tasks"][chat_id] = task