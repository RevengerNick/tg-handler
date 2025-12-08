import asyncio
import re
import time
from datetime import datetime, timedelta
from collections import Counter
from pyrogram.errors import FloodWait

from src.config import STOP_WORDS, BAD_EXACT, BAD_STARTS, BAD_CONTAINS
from src.services.utils import edit_or_reply, smart_reply


async def analyze_chat_history(client, message, period_days=30):
    """
    Анализирует историю чата за указанный период.
    Выводит статистику со спойлерами для мата и без лишних хештегов.
    """
    chat_id = message.chat.id
    start_date = datetime.now() - timedelta(days=period_days)

    total_messages = 0
    words_counter = Counter()
    bad_words_counter = Counter()
    users_counter = Counter()

    status_msg = await edit_or_reply(message, f"📊 Кеширую чат и начинаю анализ ({period_days} дн)...")

    try:
        await client.get_chat(chat_id)
    except:
        pass

    last_update_time = time.time()

    try:
        history_iter = client.get_chat_history(chat_id)

        async for msg in history_iter:
            try:
                if msg.date < start_date:
                    break

                total_messages += 1

                if time.time() - last_update_time > 5:
                    try:
                        await status_msg.edit(f"📊 Анализ... Обработано: {total_messages}")
                        last_update_time = time.time()
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value)
                    except:
                        pass

                if not msg.text and not msg.caption: continue

                text = (msg.text or msg.caption).lower()

                if msg.from_user:
                    name = msg.from_user.first_name or msg.from_user.username or "Unknown"
                    users_counter[name] += 1

                clean_text = re.sub(r'[^\w\s-]', ' ', text)
                words = clean_text.split()

                for word in words:
                    if len(word) < 3 or word in STOP_WORDS: continue

                    # Считаем слово в общий топ
                    words_counter[word] += 1

                    # Проверка на мат (Логика из предыдущего шага)
                    is_bad = False
                    if word in BAD_EXACT: is_bad = True
                    if not is_bad:
                        for root in BAD_STARTS:
                            if word.startswith(root):
                                is_bad = True;
                                break
                    if not is_bad:
                        for root in BAD_CONTAINS:
                            if root in word:
                                is_bad = True;
                                break

                    if is_bad:
                        bad_words_counter[word] += 1

            except FloodWait as e:
                print(f"FW: {e.value}s");
                await asyncio.sleep(e.value + 1)
            except Exception:
                continue

        # --- ГЕНЕРАЦИЯ ОТЧЕТА ---

        date_str = f"{start_date.strftime('%d.%m')} - {datetime.now().strftime('%d.%m')}"

        # Убрали #, используем жирный шрифт для заголовков
        report = f"📊 **Статистика чата**\n"
        report += f"📅 Период: {date_str} ({period_days} дн.)\n"
        report += f"✉️ Всего сообщений: {total_messages}\n\n"

        # 1. Топ слов (с проверкой на мат для спойлеров)
        report += "🗣 **Топ-15 слов:**\n"
        if words_counter:
            for i, (word, count) in enumerate(words_counter.most_common(15), 1):
                # Если слово есть в списке найденного мата - скрываем его
                if word in bad_words_counter:
                    display_word = f"||{word}||"
                else:
                    display_word = word

                report += f"{i}. {display_word} — {count}\n"
        else:
            report += "_Пусто_\n"

        # 2. Топ мата (всегда под спойлером)
        report += "\n🤬 **Топ-10 ругательств:**\n"
        if bad_words_counter:
            for i, (word, count) in enumerate(bad_words_counter.most_common(10), 1):
                # Используем синтаксис спойлера Telegram
                report += f"{i}. ||{word}|| — {count}\n"
        else:
            report += "✨ _Культурный чат_ ✨\n"

        # 3. Топ людей
        report += "\n🏆 **Топ-10 писателей:**\n"
        if users_counter:
            for i, (user, count) in enumerate(users_counter.most_common(10), 1):
                report += f"{i}. **{user}** — {count} смс\n"
        else:
            report += "_Пусто_\n"

        chat_title = message.chat.title or "Chat"

        # Используем smart_reply (если текст > 4000, уйдет в Telegraph)
        # В Telegraph спойлеры ||...|| отобразятся просто текстом ||...||,
        # но зато в Телеграме будет красивая анимация скрытия.
        await smart_reply(status_msg, report, title=f"Stats: {chat_title}")

    except Exception as e:
        await status_msg.edit(f"❌ Ошибка анализа: {e}")