from google import genai
from google.genai import types, errors
from src.config import GEMINI_KEYS, AVAILABLE_MODELS
from src.state import SETTINGS, ASYNC_CHAT_SESSIONS

# Глобальный индекс текущего ключа и активный клиент
current_key_index = 0
_active_client = None


def init_client():
    """Инициализирует клиента с текущим ключом из списка"""
    global _active_client, current_key_index

    if not GEMINI_KEYS:
        print("❌ No Gemini Keys found in .env!")
        return None

    # Берем ключ по текущему индексу
    key = GEMINI_KEYS[current_key_index]

    try:
        _active_client = genai.Client(api_key=key)
        # print(f"🔑 Init Client with Key #{current_key_index + 1}")
    except Exception as e:
        print(f"❌ Error init client (Key #{current_key_index}): {e}")

    return _active_client


def get_ai_client():
    """Возвращает активного клиента (или создает его, если нет)"""
    global _active_client
    if _active_client is None:
        init_client()
    return _active_client


async def rotate_key_and_retry(func, *args, **kwargs):
    """
    Обертка: Выполняет функцию. При ошибке 429/503 меняет ключ и пробует снова.
    Пробует ровно столько раз, сколько есть ключей.
    """
    global current_key_index

    # Количество попыток = количеству ключей.
    # Если ключей 3, мы попробуем 3 раза.
    max_retries = len(GEMINI_KEYS)

    if max_retries == 0:
        raise Exception("No API Keys configured")

    last_error = None

    for attempt in range(max_retries):
        try:
            # 1. Пытаемся выполнить переданную функцию
            return await func(*args, **kwargs)

        except errors.APIError as e:
            # Ловим ошибки лимитов (429) или перегрузки (503)
            # Код 400 (Bad Request) ротировать нет смысла, это ошибка в запросе
            if e.code in [429, 503] or "429" in str(e) or "quota" in str(e).lower():
                print(f"⚠️ Key #{current_key_index} Limit Hit ({e.message}...). Rotating...")

                # 2. Меняем индекс по кругу
                # Если ключей 3: 0 -> 1 -> 2 -> 0 ...
                current_key_index = (current_key_index + 1) % max_retries

                # 3. Пересоздаем клиента с новым ключом
                init_client()

                last_error = e
                # Идем на следующий круг цикла (повторная попытка с новым ключом)
                continue
            else:
                # Если ошибка не связана с лимитами (например, неверный промпт), просто падаем
                raise e
        except Exception as e:
            # Другие ошибки (сеть и т.д.) тоже можно попробовать обойти сменой ключа/переподключением
            print(f"⚠️ Network/Unknown Error on Key #{current_key_index}: {e}")
            current_key_index = (current_key_index + 1) % max_retries
            init_client()
            last_error = e
            continue

    # Если цикл закончился, а мы так и не вернули результат
    raise Exception(f"All {max_retries} API keys exhausted. Last error: {last_error}")


# --- AI LOGIC (HELPERS) ---
async def get_gemini_stream(chat_id, contents, is_chat=False):
    """
    Возвращает асинхронный генератор (iterator), который выдает кусочки текста.
    Использует ротацию ключей при СТАРТЕ генерации.
    """

    async def _get_iterator():
        client = get_ai_client()
        if not client: raise Exception("No Client")

        model_id, config = get_ai_config(chat_id)

        # Режим чата или одиночный
        if is_chat:
            if chat_id not in ASYNC_CHAT_SESSIONS:
                ASYNC_CHAT_SESSIONS[chat_id] = await client.aio.chats.create(
                    model=model_id, config=config
                )
            chat = ASYNC_CHAT_SESSIONS[chat_id]
            # Важно: send_message_stream
            return await chat.send_message_stream(contents)
        else:
            # Одиночный запрос: generate_content_stream
            return await client.aio.models.generate_content_stream(
                model=model_id, contents=contents, config=config
            )

    try:
        # Мы используем ротацию, чтобы ПОЛУЧИТЬ итератор.
        # Если ключ забанен, мы переключимся и попробуем снова.
        # Но если ошибка возникнет в середине стрима, ротация уже не поможет
        # (нельзя продолжить генерацию с середины фразы).
        stream = await rotate_key_and_retry(_get_iterator)
        return stream
    except Exception as e:
        # Если даже начать не смогли
        print(f"Stream Init Error: {e}")
        return None


def get_ai_config(chat_id=None):
    key = SETTINGS.get("model_key", "1")
    model_info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["1"])

    sys_instr = SETTINGS.get("sys_global", "")
    if chat_id:
        local_sys = SETTINGS.get("sys_chats", {}).get(str(chat_id), "")
        if local_sys:
            sys_instr = f"{sys_instr}\n\n[Context: {local_sys}]".strip()

    tools = [types.Tool(google_search=types.GoogleSearch())] if model_info["search"] else []

    config = types.GenerateContentConfig(
        system_instruction=sys_instr if sys_instr else None,
        tools=tools
    )
    return model_info["id"], config


def format_grounding(text, candidates):
    try:
        if not candidates or not candidates[0].grounding_metadata: return text
        metadata = candidates[0].grounding_metadata
        if not metadata.grounding_chunks: return text
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


# --- EXPORTED FUNCTIONS (Wrapped) ---

async def ask_gemini_oneshot(contents):
    """Обертка для разового запроса"""

    async def _request():
        client = get_ai_client()
        if not client: raise Exception("No Client")

        model_id, config = get_ai_config()
        response = await client.aio.models.generate_content(
            model=model_id, contents=contents, config=config
        )
        return format_grounding(response.text, response.candidates)

    return await rotate_key_and_retry(_request)


async def ask_gemini_chat(chat_id, contents):
    """Обертка для чата"""

    async def _request():
        client = get_ai_client()
        if not client: raise Exception("No Client")

        model_id, config = get_ai_config(chat_id)

        # Если сессии нет или клиент сменился (старая сессия привязана к старому клиенту?)
        # На самом деле, объект ChatSession в genai SDK привязан к клиенту.
        # Поэтому если мы меняем ключ (client), старые сессии в ASYNC_CHAT_SESSIONS станут невалидны.
        # Нам нужно их пересоздавать.

        # Проверяем, жив ли чат и привязан ли он к текущему клиенту (косвенно)
        # Проще всего: если ловим ошибку авторизации внутри чата, удалять сессию и создавать новую.

        if chat_id not in ASYNC_CHAT_SESSIONS:
            ASYNC_CHAT_SESSIONS[chat_id] = await client.aio.chats.create(
                model=model_id, config=config
            )

        chat = ASYNC_CHAT_SESSIONS[chat_id]

        try:
            response = await chat.send_message(contents)
            return format_grounding(response.text, response.candidates)
        except Exception as e:
            # Если ошибка внутри чата (например, ключ протух), удаляем сессию
            # Чтобы в следующей попытке (в цикле rotate_key_and_retry) она создалась заново с НОВЫМ клиентом
            if chat_id in ASYNC_CHAT_SESSIONS:
                del ASYNC_CHAT_SESSIONS[chat_id]
            raise e  # Пробрасываем ошибку наверх, чтобы сработал rotate_key_and_retry

    return await rotate_key_and_retry(_request)