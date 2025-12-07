from google import genai
from google.genai import types
from src.config import GEMINI_KEY, AVAILABLE_MODELS
from src.state import SETTINGS, ASYNC_CHAT_SESSIONS

# Инициализация клиента
ai_client = None
if GEMINI_KEY:
    try:
        ai_client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"❌ AI Init Error: {e}")


def get_ai_config(chat_id=None):
    """Собирает конфиг (модель + инструкции + поиск)"""
    key = SETTINGS.get("model_key", "1")
    model_info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["1"])

    # Инструкции
    sys_instr = SETTINGS.get("sys_global", "")
    if chat_id:
        local_sys = SETTINGS.get("sys_chats", {}).get(str(chat_id), "")
        if local_sys:
            sys_instr = f"{sys_instr}\n\n[Context: {local_sys}]".strip()

    # Инструменты (Поиск)
    tools = [types.Tool(google_search=types.GoogleSearch())] if model_info["search"] else []

    config = types.GenerateContentConfig(
        system_instruction=sys_instr if sys_instr else None,
        tools=tools
    )
    return model_info["id"], config


def format_grounding(text, candidates):
    """Добавляет ссылки на источники (Grounding)"""
    try:
        if not candidates or not candidates[0].grounding_metadata:
            return text

        metadata = candidates[0].grounding_metadata
        if not metadata.grounding_chunks:
            return text

        sources = set()
        text += "\n\n🌐 **Sources:**"

        for chunk in metadata.grounding_chunks:
            if chunk.web and chunk.web.uri and chunk.web.uri not in sources:
                title = chunk.web.title or "Link"
                text += f"\n🔹 [{title}]({chunk.web.uri})"
                sources.add(chunk.web.uri)

        return text
    except:
        return text


async def ask_gemini_oneshot(contents):
    """Разовый запрос"""
    if not ai_client: return "⚠️ API Key missing."

    model_id, config = get_ai_config()
    try:
        response = await ai_client.aio.models.generate_content(
            model=model_id,
            contents=contents,
            config=config
        )
        return format_grounding(response.text, response.candidates)
    except Exception as e:
        return f"AI Error: {e}"


async def ask_gemini_chat(chat_id, contents):
    """Запрос в контексте чата"""
    if not ai_client: return "⚠️ API Key missing."

    model_id, config = get_ai_config(chat_id)
    try:
        # Создаем сессию, если её нет
        if chat_id not in ASYNC_CHAT_SESSIONS:
            ASYNC_CHAT_SESSIONS[chat_id] = await ai_client.aio.chats.create(
                model=model_id,
                config=config
            )

        chat = ASYNC_CHAT_SESSIONS[chat_id]
        response = await chat.send_message(contents)
        return format_grounding(response.text, response.candidates)
    except Exception as e:
        # Если ошибка (например, история сломалась), сбрасываем сессию
        if chat_id in ASYNC_CHAT_SESSIONS:
            del ASYNC_CHAT_SESSIONS[chat_id]
        return f"Chat Error: {e}"