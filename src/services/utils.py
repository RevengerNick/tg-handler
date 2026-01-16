import asyncio
import time
from src.services.local_web import save_to_local_web



# --- TEXT UTILS ---

def smart_split(text, limit=4000):
    """Разбивает текст на части, сохраняя целостность слов."""
    if len(text) <= limit:
        return [text]

    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break

        # Ищем перенос строки или пробел ближе к концу лимита
        cut = text[:limit].rfind('\n')
        if cut == -1:
            cut = text[:limit].rfind(' ')

        # Если совсем нет разделителей, режем жестко
        if cut == -1:
            cut = limit

        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return parts


# --- TELEGRAM UTILS ---

async def edit_or_reply(message, text, **kwargs):
    """Редактирует свое сообщение или отвечает на чужое."""
    if message.outgoing:
        await message.edit(text, **kwargs)
        return message
    else:
        return await message.reply(text, **kwargs)


async def smart_reply(message, text, title="AI Response", use_markdown=True):
    """
    Автоматически выбирает способ отправки:
    - Короткий текст -> В чат.
    - Длинный текст -> Ссылка на Telegraph.
    """
    try:
        if len(text) > 4000:
            if message.outgoing:
                await message.edit("📝 Ответ длинный, создаю статью...")

            # Функция из services/web.py
            link = await save_to_local_web(title, text)

            final_text = f"📝 **{title} (Longread):**\n👉 {link}"
            await edit_or_reply(message, final_text)
        else:
            await edit_or_reply(message, text, disable_web_page_preview=True)
    except Exception as e:
        await edit_or_reply(message, f"SmartSend Err: {e}")


async def handle_stream_output(client, message, stream_generator, title="AI Response", header=""):
    """
    Принимает поток от Gemini и обновляет сообщение в Telegram в реальном времени.
    Если текст > 4000, переключается на Telegraph.
    """
    full_text = ""
    last_update_time = 0
    is_telegraph_mode = False

    # Стартовое сообщение
    current_msg = message  # Сообщение, которое мы редактируем (обычно статус "Думаю...")

    try:
        # Перебираем кусочки (chunks)
        async for chunk in stream_generator:
            if chunk.text:
                full_text += chunk.text

                # --- ЛОГИКА TELEGRAPH ---
                if len(full_text) > 4000:
                    if not is_telegraph_mode:
                        is_telegraph_mode = True
                        # Один раз меняем сообщение, чтобы юзер знал
                        await current_msg.edit(
                            f"{header}\n\n📝 **Ответ стал слишком длинным.**\nГенерирую статью в Telegraph... ⏳")
                    # В режиме телеграфа мы просто копим текст, не редактируя сообщение
                    continue

                # --- ЛОГИКА ОБНОВЛЕНИЯ (Раз в 1.5 сек) ---
                now = time.time()
                if now - last_update_time > 1.5:
                    try:
                        # Формируем красивый вывод
                        display_text = f"{header}\n\n{full_text} █"  # █ курсор
                        await current_msg.edit(display_text, disable_web_page_preview=True)
                        last_update_time = now
                    except Exception:
                        # Если словили FloodWait или ошибку разметки - просто пропускаем кадр
                        pass

        # --- ФИНАЛ ---
        if is_telegraph_mode:
            # Создаем статью
            link = await save_to_local_web(title, full_text)
            final_view = f"{header}\n\n📝 **{title} (Longread):**\n👉 {link}"
            await current_msg.edit(final_view)
        else:
            # Убираем курсор и форматируем Markdown
            # Добавляем источники, если они есть (в стриме они приходят в конце, но в chunk.text их нет)
            # В v1 API grounding приходил отдельно, в v2 может быть в chunk.candidates
            # Пока оставим просто текст
            final_view = f"{header}\n\n{full_text}"
            await current_msg.edit(final_view, disable_web_page_preview=True)

    except Exception as e:
        print(f"Streaming Loop Error: {e}")
        # Если упали в процессе, выводим то, что успели накопить
        if full_text:
            await current_msg.edit(f"{header}\n\n{full_text}\n\n❌ **Обрыв связи:** {e}")
        else:
            await current_msg.edit(f"❌ Ошибка стрима: {e}")

async def get_message_context(client, message):
    """
    Извлекает текст реплая и скачивает фото, если оно есть.
    """
    from PIL import Image  # Импорт внутри, чтобы не грузить модуль лишний раз

    reply = message.reply_to_message
    if not reply:
        return "", None

    text_context = reply.text or reply.caption or ""
    if text_context:
        text_context = f"--- Reply Start ---\n{text_context}\n--- Reply End ---\n\n"

    image = None
    if reply.photo:
        try:
            # Скачиваем в память
            photo_io = await client.download_media(reply, in_memory=True)
            if photo_io:
                image = Image.open(photo_io)
        except Exception as e:
            print(f"Context Image Error: {e}")

    return text_context, image