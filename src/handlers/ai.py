import os
from pyrogram import Client, filters
from src.services import (
    edit_or_reply, smart_reply, get_message_context,
    ask_gemini_oneshot, ask_gemini_chat, generate_gemini_tts,
    convert_wav_to_ogg, transcribe_via_gemini, generate_multispeaker_tts,
    generate_imagen, generate_flux, get_gemini_stream
)
from src.services.utils import handle_stream_output
from src.state import SETTINGS, ASYNC_CHAT_SESSIONS
from src.config import AVAILABLE_MODELS, AVAILABLE_VOICES, VOICE_NAMES_LIST
from src.access_filters import AccessFilter
from src.services.local_web import save_to_local_web
import re


# --- AI COMMANDS (TEXT) ---

@Client.on_message(filters.command(["ai", "аи"], prefixes=".") & AccessFilter)
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

        # --- СТРИМИНГ ---
        # 1. Получаем генератор
        stream = await get_gemini_stream(None, content, is_chat=False)

        if stream:
            # 2. Запускаем обработчик вывода
            header = f"**Gemini ({m_name}):**"
            await handle_stream_output(client, status, stream, title=f"AI: {prompt[:20]}", header=header)
        else:
            await status.edit("❌ Ошибка запуска стрима (все ключи перебраны?).")

    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["chat", "чат"], prefixes=".") & AccessFilter)
async def chat_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else ""
        reply_txt, reply_img = await get_message_context(client, message)

        if not prompt and not reply_txt and not reply_img:
            return await edit_or_reply(message, "💬 Текст?")

        m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
        status = await edit_or_reply(message, f"💬 {m_name} думает...")

        final = f"{reply_txt}{prompt}"
        content = [reply_img, final] if reply_img else final

        # --- СТРИМИНГ (ЧАТ) ---
        stream = await get_gemini_stream(message.chat.id, content, is_chat=True)

        if stream:
            user_header = f"👤 **Вы:** {prompt}" if prompt else "👤 **Контекст**"
            header = f"{user_header}\n\n🤖 **{m_name}:**"

            await handle_stream_output(client, status, stream, title=f"Chat: {prompt[:20]}", header=header)
        else:
            await status.edit("❌ Ошибка стрима.")

    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


def parse_ai_response_with_title(raw_response: str) -> tuple:
    """
    Парсит ответ AI, ожидая формат:
    TITLE: [заголовок]
    CONTENT:
    [основной текст]
    
    Возвращает (title, content) или (fallback_title, full_response) при ошибке парсинга.
    """
    try:
        lines = raw_response.strip().split('\n')
        title = None
        content_start = 0
        
        # Ищем TITLE: в первых 5 строках
        for i, line in enumerate(lines[:5]):
            if line.strip().upper().startswith('TITLE:'):
                title = line.split(':', 1)[1].strip()
                # Ищем CONTENT: после TITLE
                for j in range(i + 1, min(i + 3, len(lines))):
                    if lines[j].strip().upper().startswith('CONTENT:'):
                        content_start = j + 1
                        break
                if content_start == 0:
                    content_start = i + 1
                break
        
        if title:
            # Очищаем заголовок
            title = title.strip().strip('"').strip("'")
            if len(title) > 80:
                title = title[:77] + "..."
            content = '\n'.join(lines[content_start:]).strip()
            return title, content
        
        # Fallback: берём первую непустую строку как заголовок
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) > 5:
                title = stripped[:60] if len(stripped) > 60 else stripped
                # Убираем markdown заголовки
                title = title.lstrip('#').strip()
                return title, raw_response.strip()
        
        return "Статья", raw_response.strip()
    except Exception:
        return "Статья", raw_response.strip()


@Client.on_message(filters.command(["ait", "аит"], prefixes=".") & AccessFilter)
async def ait_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else "Анализ"
        reply_txt, reply_img = await get_message_context(client, message)

        m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
        status = await edit_or_reply(message, f"📝 {m_name} пишет статью...")

        # Один запрос: просим сгенерировать и заголовок, и контент
        enhanced_prompt = (
            f"{reply_txt}\n\n" if reply_txt else ""
        ) + (
            f"Задание: {prompt}\n\n"
            "ВАЖНО: Ответь в следующем формате (без изменений):\n"
            "TITLE: [короткий ёмкий заголовок статьи, максимум 60 символов]\n"
            "CONTENT:\n"
            "[твой подробный ответ здесь]"
        )
        
        content_input = [reply_img, enhanced_prompt] if reply_img else enhanced_prompt
        
        raw_resp = await ask_gemini_oneshot(content_input)
        
        # Парсим ответ на заголовок и контент
        article_title, article_content = parse_ai_response_with_title(raw_resp)
        
        # Форматируем контент: Заголовок → Вопрос → Ответ
        full_content = (
            f"# {article_title}\n\n"
            f"## Вопрос\n\n"
            f"{prompt}\n\n"
            f"---\n\n"
            f"## Ответ\n\n"
            f"{article_content}"
        )

        link = await save_to_local_web(article_title, full_content)
        await status.edit(f"🧠 **Gemini ({m_name}):**\n📄 **{article_title}**\n👉 {link}", disable_web_page_preview=False)
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.me & filters.command(["chatt", "чатт"], prefixes="."))
async def chatt_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else "Продолжай"
        reply_txt, reply_img = await get_message_context(client, message)

        m_name = AVAILABLE_MODELS[SETTINGS.get("model_key", "1")]["name"]
        status = await edit_or_reply(message, f"💬📝 {m_name} пишет в контексте...")

        # Один запрос: просим сгенерировать и заголовок, и контент
        enhanced_prompt = (
            f"{reply_txt}\n\n" if reply_txt else ""
        ) + (
            f"Запрос: {prompt}\n\n"
            "ВАЖНО: Ответь в следующем формате (без изменений):\n"
            "TITLE: [короткий ёмкий заголовок, максимум 60 символов]\n"
            "CONTENT:\n"
            "[твой ответ здесь]"
        )
        
        content_input = [reply_img, enhanced_prompt] if reply_img else enhanced_prompt
        
        raw_resp = await ask_gemini_chat(message.chat.id, content_input)
        
        # Парсим ответ на заголовок и контент
        article_title, article_content = parse_ai_response_with_title(raw_resp)
        
        # Форматируем контент: Заголовок → Вопрос → Ответ
        full_content = (
            f"# {article_title}\n\n"
            f"## Вопрос\n\n"
            f"{prompt}\n\n"
            f"---\n\n"
            f"## Ответ\n\n"
            f"{article_content}"
        )

        link = await save_to_local_web(article_title, full_content)
        await status.edit(f"💬📝 **{article_title}**\n👉 {link}")
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


# --- AUDIO / VOICE COMMANDS ---

@Client.on_message(filters.command(["say", "скажи", "saywav", "sayfile"], prefixes=".") & AccessFilter)
async def say_handler(client, message):
    try:
        # Определяем режим (файл или голосовое) по команде
        cmd = message.command[0].lower()
        send_as_file = "wav" in cmd or "file" in cmd or "файл" in cmd

        parts = message.text.split(maxsplit=1)
        user_text = parts[1] if len(parts) > 1 else ""

        # Чистим реплай от наших системных заголовков
        reply_txt, _ = await get_message_context(client, message)
        if reply_txt:
            clean_reply = reply_txt.replace("--- Reply Start ---\n", "").replace("\n--- Reply End ---\n\n", "")
            final_text = clean_reply
        else:
            final_text = user_text

        if not final_text: return await edit_or_reply(message, "🗣 Введите текст.")

        v_name = AVAILABLE_VOICES.get(SETTINGS.get("voice_key", "1"))["name"]
        status = await edit_or_reply(message, f"🗣 {v_name} генерирует...")

        # Генерируем WAV
        wav_path = await generate_gemini_tts(final_text[:4000])

        if wav_path and os.path.exists(wav_path):
            await status.edit("🗣 Отправка...")

            if send_as_file:
                # Отправляем WAV как файл
                await client.send_audio(
                    message.chat.id,
                    wav_path,
                    title="Gemini TTS",
                    performer=v_name,
                    caption=f"🗣 **WAV Audio** ({v_name})"
                )
            else:
                # Конвертируем в OGG для голосового
                ogg_path = await convert_wav_to_ogg(wav_path)
                if ogg_path:
                    await client.send_voice(
                        message.chat.id,
                        ogg_path,
                        caption=f"🗣 **Voice** ({v_name})"
                    )
                    os.remove(ogg_path)
                else:
                    await status.edit("⚠️ Ошибка конвертации ffmpeg. Отправляю WAV.")
                    await client.send_audio(message.chat.id, wav_path)

            os.remove(wav_path)
            if message.outgoing: await message.delete()
            if status != message: await status.delete()
        else:
            await status.edit("❌ Ошибка генерации TTS.")
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["text", "stt", "текст"], prefixes=".") & AccessFilter)
async def stt_handler(client, message):
    try:
        reply = message.reply_to_message
        # Проверяем наличие медиа
        if not reply or not (reply.voice or reply.audio or reply.video or reply.video_note):
            return await edit_or_reply(message, "⚠️ Ответьте на голосовое, аудио или видео.")

        status = await edit_or_reply(message, "👂 Скачиваю файл...")
        path = await client.download_media(reply)

        await status.edit("🧠 Распознаю речь...")
        res = await transcribe_via_gemini(path)

        # Удаляем сразу
        if os.path.exists(path): os.remove(path)

        if "error" in res: return await status.edit(f"❌ Ошибка: {res['error']}")

        # Форматирование результата
        out = f"📝 **Суть:** {res.get('summary', '-')}\n\n"

        emojis = {"Happy": "😄", "Sad": "😔", "Angry": "😡", "Neutral": "😐", "Excited": "🤩", "Serious": "🤔"}
        for s in res.get('segments', []):
            emo = emojis.get(s.get('emotion'), "🗣")
            out += f"`{s.get('time')}` {emo} **{s.get('speaker')}:** {s.get('text')}\n"

        await smart_reply(status, out, title="Transcription")
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["dialog", "диалог", "t"], prefixes=".") & AccessFilter)
async def dialog_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        raw_input = parts[1] if len(parts) > 1 else ""

        reply_txt, _ = await get_message_context(client, message)
        if reply_txt:
            clean = reply_txt.replace("--- Reply Start ---\n", "").replace("\n--- Reply End ---\n\n", "")
            raw_input = f"{raw_input}\n{clean}".strip()

        if not raw_input:
            return await edit_or_reply(message,
                                       "🎭 **Диалог**\nФормат:\n`.t 1: Привет`\nИли: `.t 1=Puck 2=Kore`\n`1: ...`")

        status = await edit_or_reply(message, "🎭 Распределяю роли...")

        # Парсинг кастомных ролей в первой строке
        lines = raw_input.split("\n")
        cast_pairs = re.findall(r"(\w+)=([A-Za-z]+)", lines[0])
        cast = {}
        script = raw_input

        if cast_pairs:
            for n, v in cast_pairs:
                # Проверка по значениям словаря
                found = False
                for _, vdata in AVAILABLE_VOICES.items():
                    if vdata["name"] == v: found = True; break

                # Или по списку имен
                if not found and v in VOICE_NAMES_LIST: found = True

                if found: cast[n] = v

            # Удаляем строку настроек
            script = "\n".join(lines[1:])

        wav_path = await generate_multispeaker_tts(script, cast)

        if wav_path:
            await status.edit("🎭 Отправка...")
            ogg_path = await convert_wav_to_ogg(wav_path)

            desc = ", ".join([f"{k}={v}" for k, v in cast.items()]) if cast else "Auto-Cast"
            await client.send_voice(
                message.chat.id,
                ogg_path if ogg_path else wav_path,
                caption=f"🎭 **Dialogue** ({desc})"
            )

            if ogg_path: os.remove(ogg_path)
            os.remove(wav_path)
            if message.outgoing: await message.delete()
            if status != message: await status.delete()
        else:
            await status.edit("❌ Ошибка генерации диалога.")
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["podcast", "подкаст"], prefixes=".") & AccessFilter)
async def podcast_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        topic = parts[1] if len(parts) > 1 else "будущем"

        status = await edit_or_reply(message, f"🎙 Придумываю сценарий про: {topic}...")

        # 1. Генерируем текст
        prompt = (
            f"Напиши диалог подкаста на тему '{topic}'. "
            "Спикеры: '1' (мужчина) и '2' (женщина). "
            "Формат: '1: текст', '2: текст'. Длина 8 реплик. Язык: Русский."
        )
        script_resp = await ask_gemini_oneshot(prompt)
        # Чистка
        script_clean = script_resp.replace("**", "").replace("##", "")

        await status.edit(f"🎙 Озвучиваю...\n\n{script_clean[:100]}...")

        # 2. Озвучиваем (Жесткий кастинг для подкаста)
        cast = {"1": "Puck", "2": "Aoede"}
        wav_path = await generate_multispeaker_tts(script_clean, cast)

        if wav_path:
            ogg_path = await convert_wav_to_ogg(wav_path)
            await client.send_voice(
                message.chat.id,
                ogg_path if ogg_path else wav_path,
                caption=f"🎙 **AI Podcast**\nТема: {topic}"
            )
            if ogg_path: os.remove(ogg_path)
            os.remove(wav_path)
            if message.outgoing: await message.delete()
            if status != message: await status.delete()
        else:
            await status.edit("❌ Ошибка озвучки.")
    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["img", "имг", "imagen"], prefixes=".") & AccessFilter)
async def imagen_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else ""

        if not prompt:
            return await edit_or_reply(message, "🎨 Введите описание картинки (на английском лучше).")

        status = await edit_or_reply(message, "🎨 **Imagen 3** рисует...")

        # Запускаем генерацию
        file_path, error = await generate_imagen(prompt)

        if file_path:
            await status.edit("🎨 Отправляю...")
            await client.send_photo(
                message.chat.id,
                photo=file_path,
                caption=f"🎨 **Imagen 3**\n`{prompt}`"
            )
            os.remove(file_path)
            if message.outgoing: await message.delete()
            if status != message: await status.delete()
        else:
            await status.edit(f"❌ Ошибка Imagen: {error}")

    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")


@Client.on_message(filters.command(["flux", "флакс", "арт"], prefixes=".") & AccessFilter)
async def flux_handler(client, message):
    try:
        parts = message.text.split(maxsplit=1)
        prompt = parts[1] if len(parts) > 1 else ""

        if not prompt:
            return await edit_or_reply(message, "🎨 Введите описание для Flux.")

        status = await edit_or_reply(message, "🎨 **Flux** рисует...")

        # Запускаем генерацию
        file_path, error = await generate_flux(prompt)

        if file_path:
            await status.edit("🎨 Отправляю...")
            await client.send_photo(
                message.chat.id,
                photo=file_path,
                caption=f"🎨 **Flux.1**\n`{prompt}`"
            )
            os.remove(file_path)
            if message.outgoing: await message.delete()
            if status != message: await status.delete()
        else:
            await status.edit(f"❌ Ошибка Flux: {error}")

    except Exception as e:
        await edit_or_reply(message, f"Err: {e}")