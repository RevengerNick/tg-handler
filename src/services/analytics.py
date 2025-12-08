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
    """
    chat_id = message.chat.id
    start_date = datetime.now() - timedelta(days=period_days)

    total_messages = 0
    words_counter = Counter()
    bad_words_counter = Counter()
    users_counter = Counter()

    status_msg = await edit_or_reply(message, f"📊 Кеширую чат и начинаю анализ ({period_days} дн)...")

    try:
        # Обновляем инфо о чате (fix PeerIdInvalid)
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

                # Обновление статуса
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

                # Активность
                if msg.from_user:
                    name = msg.from_user.first_name or msg.from_user.username or "Unknown"
                    users_counter[name] += 1

                # Очистка
                clean_text = re.sub(r'[^\w\s-]', ' ', text)
                words = clean_text.split()

                for word in words:
                    if len(word) < 3 or word in STOP_WORDS: continue

                    # Топ слов
                    words_counter[word] += 1

                    # --- ПРОВЕРКА НА МАТ (НОВАЯ ЛОГИКА) ---
                    is_bad = False

                    # 1. Точное совпадение (для коротких слов: хуй, бля)
                    if word in BAD_EXACT:
                        is_bad = True

                    # 2. Начало слова (для производных: ебать, хуевый)
                    if not is_bad:
                        for root in BAD_STARTS:
                            if word.startswith(root):
                                is_bad = True
                                break

                    # 3. Жесткие корни (везде: пизд, бляд)
                    if not is_bad:
                        for root in BAD_CONTAINS:
                            if root in word:
                                is_bad = True
                                break

                    if is_bad:
                        bad_words_counter[word] += 1

            except FloodWait as e:
                print(f"FW: {e.value}s");
                await asyncio.sleep(e.value + 1)
            except Exception:
                continue

        # --- ОТЧЕТ ---
        date_str = f"{start_date.strftime('%d.%m')} - {datetime.now().strftime('%d.%m')}"

        report = f"# 📊 Статистика чата\n"
        report += f"**Период:** {date_str} ({period_days} дн.)\n"
        report += f"**Всего сообщений:** {total_messages}\n\n"

        # Слова
        report += "🗣 Топ-15 слов:\n"
        if words_counter:
            for i, (word, count) in enumerate(words_counter.most_common(15), 1):
                report += f"{i}. **{word}** — {count}\n"
        else:
            report += "_Пусто_\n"

        # Мат
        report += "\n🤬 Топ-10 ругательств:\n"
        if bad_words_counter:
            for i, (word, count) in enumerate(bad_words_counter.most_common(10), 1):
                # Цензура: х*й
                censored = word[0] + "*" + word[2:] if len(word) > 1 else word
                report += f"{i}. **{censored}** — {count}\n"
        else:
            report += "✨ _Культурный чат_ ✨\n"

        # Люди
        report += "\n🏆 Топ-10 писателей:\n"
        if users_counter:
            for i, (user, count) in enumerate(users_counter.most_common(10), 1):
                report += f"{i}. **{user}** — {count} смс\n"
        else:
            report += "_Пусто_\n"

        chat_title = message.chat.title or "Chat"
        await smart_reply(status_msg, report, title=f"Stats: {chat_title}")

    except Exception as e:
        await status_msg.edit(f"❌ Ошибка анализа: {e}")