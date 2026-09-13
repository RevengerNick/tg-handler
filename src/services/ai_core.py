import asyncio

from google import genai
from google.genai import errors, types

from src.config import AVAILABLE_MODELS, GEMINI_KEYS
from src.state import ASYNC_CHAT_SESSIONS, SETTINGS

# Глобальный индекс текущего ключа и активный клиент
current_key_index = 0
_active_client = None
_chat_locks: dict[int, asyncio.Lock] = {}

_ROTATABLE_API_CODES = {401, 403, 429, 500, 502, 503, 504}


def init_client():
    """Инициализирует клиента с текущим ключом из списка"""
    global _active_client

    if not GEMINI_KEYS:
        print("❌ No Gemini Keys found in .env!")
        return None

    # Берем ключ по текущему индексу
    key = GEMINI_KEYS[current_key_index]

    try:
        new_client = genai.Client(api_key=key)
        # AsyncChat keeps a reference to the client that created it. Sessions
        # therefore cannot be reused after an API-key/client rotation.
        ASYNC_CHAT_SESSIONS.clear()
        _active_client = new_client
        # print(f"🔑 Init Client with Key #{current_key_index + 1}")
    except Exception as error:  # noqa: BLE001 - SDK construction errors vary by release
        _active_client = None
        print(
            f"❌ Error init client (Key #{current_key_index}): {type(error).__name__}"
        )

    return _active_client


def get_ai_client():
    """Возвращает активного клиента (или создает его, если нет)"""
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
        raise RuntimeError("No API Keys configured")

    for attempt in range(max_retries):
        try:
            # 1. Пытаемся выполнить переданную функцию
            return await func(*args, **kwargs)

        except errors.APIError as e:
            # Rotate only for key-, quota-, and transient server failures.
            # Request/programming errors must surface immediately instead of
            # being reported as if every configured API key were exhausted.
            if e.code in _ROTATABLE_API_CODES:
                message = getattr(e, "message", str(e))
                print(
                    f"⚠️ Key #{current_key_index} API Error ({message}...). Rotating..."
                )

                # 2. Меняем индекс по кругу
                # Если ключей 3: 0 -> 1 -> 2 -> 0 ...
                current_key_index = (current_key_index + 1) % max_retries

                # 3. Пересоздаем клиента с новым ключом
                init_client()

                # Идем на следующий круг цикла (повторная попытка с новым ключом)
                continue
            else:
                raise

    # Если цикл закончился, а мы так и не вернули результат
    raise RuntimeError(f"All {max_retries} configured API keys are unavailable")


# --- AI LOGIC (HELPERS) ---
async def get_gemini_stream(chat_id, contents, is_chat=False):
    """
    Возвращает асинхронный генератор (iterator), который выдает кусочки текста.
    Использует ротацию ключей при СТАРТЕ генерации.
    """

    async def _get_iterator():
        client = get_ai_client()
        if not client:
            raise RuntimeError("Gemini client is unavailable")

        model_id, config = get_ai_config(chat_id)

        # Режим чата или одиночный
        if is_chat:
            if chat_id not in ASYNC_CHAT_SESSIONS:
                ASYNC_CHAT_SESSIONS[chat_id] = client.aio.chats.create(
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

    attempts = len(GEMINI_KEYS)
    if not attempts:
        raise RuntimeError("No API Keys configured")

    async def _stream_with_retry():
        global current_key_index
        last_error = None
        for attempt in range(attempts):
            emitted = False
            try:
                lock = (
                    _chat_locks.setdefault(chat_id, asyncio.Lock()) if is_chat else None
                )
                if lock:
                    async with lock:
                        iterator = await _get_iterator()
                        async for chunk in iterator:
                            emitted = True
                            yield chunk
                else:
                    iterator = await _get_iterator()
                    async for chunk in iterator:
                        emitted = True
                        yield chunk
                return
            except errors.APIError as error:
                last_error = error
                if (
                    emitted
                    or error.code not in _ROTATABLE_API_CODES
                    or attempt + 1 >= attempts
                ):
                    raise
                current_key_index = (current_key_index + 1) % attempts
                init_client()
        raise RuntimeError(f"All {attempts} API keys exhausted") from last_error

    return _stream_with_retry()


def get_ai_config(chat_id=None):
    key = SETTINGS.get("model_key", "1")
    model_info = AVAILABLE_MODELS.get(key, AVAILABLE_MODELS["1"])

    sys_instr = SETTINGS.get("sys_global", "")
    if chat_id:
        local_sys = SETTINGS.get("sys_chats", {}).get(str(chat_id), "")
        if local_sys:
            sys_instr = f"{sys_instr}\n\n[Context: {local_sys}]".strip()

    tools = (
        [types.Tool(google_search=types.GoogleSearch())]
        if model_info["search"]
        else None
    )

    config = types.GenerateContentConfig(
        system_instruction=sys_instr if sys_instr else None,
        tools=tools,
        # These commands use only server-side built-in tools (Google Search),
        # never local Python callables. Disable SDK-side AFC so one-shot model
        # calls follow the google-genai 2.x async contract without warnings.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return model_info["id"], config


def format_grounding(text, candidates):
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
    except (AttributeError, IndexError, TypeError):
        return text


# --- EXPORTED FUNCTIONS (Wrapped) ---


async def ask_gemini_oneshot(contents):
    """Обертка для разового запроса"""

    async def _request():
        client = get_ai_client()
        if not client:
            raise RuntimeError("Gemini client is unavailable")

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
        if not client:
            raise RuntimeError("Gemini client is unavailable")

        model_id, config = get_ai_config(chat_id)

        # Если сессии нет или клиент сменился (старая сессия привязана к старому клиенту?)
        # На самом деле, объект ChatSession в genai SDK привязан к клиенту.
        # Поэтому если мы меняем ключ (client), старые сессии в ASYNC_CHAT_SESSIONS станут невалидны.
        # Нам нужно их пересоздавать.

        # Проверяем, жив ли чат и привязан ли он к текущему клиенту (косвенно)
        # Проще всего: если ловим ошибку авторизации внутри чата, удалять сессию и создавать новую.

        if chat_id not in ASYNC_CHAT_SESSIONS:
            ASYNC_CHAT_SESSIONS[chat_id] = client.aio.chats.create(
                model=model_id, config=config
            )

        chat = ASYNC_CHAT_SESSIONS[chat_id]

        try:
            async with _chat_locks.setdefault(chat_id, asyncio.Lock()):
                response = await chat.send_message(contents)
            return format_grounding(response.text, response.candidates)
        except Exception:
            # A session belongs to the client/API key that created it.
            ASYNC_CHAT_SESSIONS.pop(chat_id, None)
            raise

    return await rotate_key_and_retry(_request)
