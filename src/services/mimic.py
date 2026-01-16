import os
import asyncio
from datetime import datetime, timedelta
from src.services.utils import edit_or_reply
from src.services.ai_core import get_ai_client, rotate_key_and_retry
from src.state import SETTINGS
from google.genai import types

PERSONALITY_FILE = "sessions/personality.txt"


async def learn_user_style(client, message, days=30):
    """
    Умное обучение: Сохраняет диалоги в формате [CONTEXT] -> [REPLY].
    Группирует подряд идущие сообщения от одного автора.
    """
    chat_id = message.chat.id
    start_date = datetime.now() - timedelta(days=days)

    status = await edit_or_reply(message, f"🧠 Анализирую переписку за {days} дн (Группировка диалогов)...")

    # Структура для истории: список словарей {'is_me': bool, 'text': "..."}
    history_buffer = []

    try:
        # 1. Выкачиваем историю
        async for msg in client.get_chat_history(chat_id):
            if msg.date < start_date:
                break

            text = msg.text or msg.caption
            if not text or text.startswith("."): continue  # Пропускаем команды и пустые

            is_me = msg.outgoing

            # Группировка: Если предыдущее сообщение (которое мы добавили последним)
            # от того же автора, то склеиваем тексты через \n
            if history_buffer and history_buffer[-1]['is_me'] == is_me:
                # Добавляем в начало, так как читаем историю в обратном порядке (от новых к старым)
                # Поэтому старое сообщение должно быть ПЕРЕД новым в блоке
                history_buffer[-1]['text'] = text + "\n" + history_buffer[-1]['text']
            else:
                history_buffer.append({'is_me': is_me, 'text': text})

        # 2. Формируем датасет
        # history_buffer сейчас идет от Новых к Старым. Развернем для записи.
        history_buffer.reverse()

        pairs_count = 0

        os.makedirs("sessions", exist_ok=True)
        with open(PERSONALITY_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n\n--- SESSION LEARN {datetime.now()} ---\n")

            # Ищем пары: Чужое -> Моё
            for i in range(len(history_buffer) - 1):
                curr = history_buffer[i]
                nxt = history_buffer[i + 1]

                # Если текущее НЕ мое, а следующее МОЕ - это контекст и ответ
                if not curr['is_me'] and nxt['is_me']:
                    # Формат:
                    # Q: текст собеседника
                    # A: мой ответ (возможно многострочный)
                    block = (
                        f"Q: {curr['text']}\n"
                        f"A: {nxt['text']}\n"
                        f"---\n"
                    )
                    f.write(block)
                    pairs_count += 1

        await status.edit(
            f"🧠 **Обучение завершено!**\nСохранено диалоговых пар: {pairs_count}\nТеперь я понимаю контекст и твой стиль ответов.")

    except Exception as e:
        await status.edit(f"❌ Ошибка обучения: {e}")


async def get_mimic_response(incoming_text_list):
    """
    incoming_text_list: Список сообщений от собеседника (буфер).
    """
    if not os.path.exists(PERSONALITY_FILE):
        return None

    # Читаем базу (обрезаем если слишком большая, оставляем свежее в конце)
    with open(PERSONALITY_FILE, "r", encoding="utf-8") as f:
        data = f.read()
        if len(data) > 300000: data = data[-300000:]

    # Собираем входящие сообщения в один блок
    incoming_context = "\n".join(incoming_text_list)

    async def _worker():
        client = get_ai_client()
        if not client: return None

        system_instruction = (
            "Ты — цифровой двойник человека. Твоя задача — ответить на сообщение, ПОЛНОСТЬЮ имитируя стиль автора из примеров ниже.\n"
            "Правила стиля:\n"
            "1. Используй сленг, манеру речи, пунктуацию (или её отсутствие), скобочки как в примерах.\n"
            "2. ВАЖНО: Автор часто пишет короткими сообщениями (разбивает мысль). \n"
            "   Если ответ длинный, РАЗБЕЙ ЕГО на несколько строк. Каждая новая строка в твоем ответе будет отправлена как отдельное сообщение.\n"
            "3. Не пиши как робот. Будь живым, токсичным или добрым — как в примерах.\n"
            "4. НЕ используй вступлений типа 'Вот ответ'. Сразу пиши текст.\n\n"
            f"--- ПРИМЕРЫ ДИАЛОГОВ АВТОРА ---\n{data}\n--- КОНЕЦ ПРИМЕРОВ ---\n"
        )

        prompt = f"Входящее сообщение (контекст):\n{incoming_context}\n\nТвой ответ (разбей на строки, если нужно несколько сообщений):"

        # Используем Flash для скорости и креативности
        model = "gemini-2.5-flash"

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.95,  # Максимальная "человечность"
            )
        )
        return response.text.strip()

    try:
        return await rotate_key_and_retry(_worker)
    except Exception as e:
        print(f"Mimic Gen Error: {e}")
        return None