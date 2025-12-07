import asyncio
from src.services.web import create_telegraph_page


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
            link = await create_telegraph_page(title, text)

            final_text = f"📝 **{title} (Longread):**\n👉 {link}"
            await edit_or_reply(message, final_text)
        else:
            # disable_web_page_preview=True чтобы ссылки источников не создавали мусор
            await edit_or_reply(message, text, disable_web_page_preview=True)
    except Exception as e:
        await edit_or_reply(message, f"SmartSend Err: {e}")


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