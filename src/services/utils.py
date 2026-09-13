from pyrogram.errors import MessageNotModified

from src.services.local_web import save_to_local_web
from src.services.rich_messages import send_rich_or_article


def smart_split(text, limit=4000):
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text[:limit].rfind("\n")
        if cut == -1:
            cut = text[:limit].rfind(" ")
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    return parts


async def edit_or_reply(message, text, **kwargs):
    """Редактирует свое сообщение или отвечает на чужое (с защитой от MessageNotModified)."""
    try:
        if message.outgoing:
            await message.edit(text, **kwargs)
            return message
        else:
            return await message.reply(text, **kwargs)
    except MessageNotModified:
        return message
    except Exception as e:
        print(f"Edit/Reply Error: {e}")
        return message


async def smart_reply(message, text, title="AI Response", use_markdown=True):
    """
    Длинный текст -> Ссылка на локальный Web-сервер.
    """
    try:
        if len(text) > 4000:
            if message.outgoing:
                await edit_or_reply(message, "📝 Ответ длинный, создаю статью...")
            # Используем новый сервис для веба
            link = await save_to_local_web(title, text)
            final_text = f"📝 **{title} (Longread):**\n👉 {link}"
            await edit_or_reply(message, final_text)
        else:
            await edit_or_reply(message, text, disable_web_page_preview=True)
    except Exception as e:
        await edit_or_reply(message, f"SmartSend Err: {e}")


async def handle_stream_output(
    client, message, stream_generator, title="AI Response", header=""
):
    full_text = ""
    current_msg = message
    try:
        async for chunk in stream_generator:
            if chunk.text:
                full_text += chunk.text
        final_view = f"{header}\n\n{full_text}" if header else full_text
        await send_rich_or_article(client, current_msg, final_view, title=title)
    except Exception as e:
        print(f"Streaming Error: {type(e).__name__}")
        if full_text:
            await send_rich_or_article(
                client, current_msg, f"{header}\n\n{full_text}", title=title
            )
        else:
            await current_msg.edit(
                "❌ AI не смог ответить. Проверьте модель, лимиты API и ключи."
            )


async def get_message_context(client, message):
    from PIL import Image

    reply = message.reply_to_message
    if not reply:
        return "", None
    text_context = reply.text or reply.caption or ""
    if text_context:
        text_context = f"--- Reply Start ---\n{text_context}\n--- Reply End ---\n\n"
    image = None
    if reply.photo:
        try:
            photo_io = await client.download_media(reply, in_memory=True)
            if photo_io:
                image = Image.open(photo_io)
        except Exception:
            pass
    return text_context, image
