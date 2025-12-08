import asyncio
import re
import time
from datetime import datetime, timedelta
from collections import Counter
from pyrogram.errors import FloodWait

from src.config import STOP_WORDS, BAD_EXACT, BAD_STARTS, BAD_CONTAINS
from src.services.utils import edit_or_reply, smart_reply


def format_duration(seconds):
    """Конвертирует секунды в компактный вид (1д 2ч 30м)"""
    if seconds == 0:
        return "0м"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    parts = []
    if d > 0: parts.append(f"{d}д")
    if h > 0: parts.append(f"{h}ч")
    if m > 0: parts.append(f"{m}м")
    if s > 0 and d == 0 and h == 0 and m == 0: parts.append(f"{s}с")

    return " ".join(parts)


async def analyze_chat_history(client, message, period_days=30):
    """
    Анализирует историю чата: слова, мат, активность, ГС и СМЕХ.
    """
    chat_id = message.chat.id
    start_date = datetime.now() - timedelta(days=period_days)

    # Счетчики
    total_messages = 0
    total_voice_seconds = 0

    words_counter = Counter()
    bad_words_counter = Counter()
    users_msg_counter = Counter()
    users_voice_counter = Counter()
    users_laugh_counter = Counter()  # <--- НОВОЕ: Счетчик смеха

    # Паттерн смеха: допускаем только эти буквы и символы от начала до конца строки
    # Рус: х, а, п, з, в, ъ, э, ж, о, л
    # Англ: h, a, x, j, l, o
    # Символы: ) ( - и пробел
    laugh_pattern = re.compile(r"^[хахэпзвъжолhaxjlo\)\(\-\s]+$", re.IGNORECASE)

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

                # --- 1. ЮЗЕР ---
                user_name = "Unknown"
                if msg.from_user:
                    user_name = msg.from_user.first_name or msg.from_user.username or "NoName"
                    users_msg_counter[user_name] += 1

                # --- 2. ГОЛОСОВЫЕ ---
                msg_duration = 0
                if msg.voice:
                    msg_duration = msg.voice.duration
                elif msg.video_note:
                    msg_duration = msg.video_note.duration

                if msg_duration > 0:
                    total_voice_seconds += msg_duration
                    if msg.from_user: users_voice_counter[user_name] += msg_duration

                # --- 3. ТЕКСТ ---
                if not msg.text and not msg.caption: continue
                text = (msg.text or msg.caption).lower()

                # --- 4. ДЕТЕКТОР СМЕХА (НОВОЕ) ---
                # Проверяем "сырой" текст перед очисткой (чтобы сохранить скобочки)
                if len(text) >= 3 and laugh_pattern.match(text):
                    if msg.from_user:
                        users_laugh_counter[user_name] += 1
                    # Если это смех, можно не считать слова внутри, чтобы не засорять топ слов "хахаха"
                    # continue # Раскомментируй, если не хочешь видеть "хаха" в топе слов

                # Очистка для слов
                clean_text = re.sub(r'[^\w\s-]', ' ', text)
                words = clean_text.split()

                for word in words:
                    if len(word) < 3 or word in STOP_WORDS: continue
                    words_counter[word] += 1

                    # Проверка на мат
                    is_bad = False
                    if word in BAD_EXACT: is_bad = True
                    if not is_bad:
                        for root in BAD_STARTS:
                            if word.startswith(root): is_bad = True; break
                    if not is_bad:
                        for root in BAD_CONTAINS:
                            if root in word: is_bad = True; break
                    if is_bad: bad_words_counter[word] += 1

            except FloodWait as e:
                print(f"FW: {e.value}s");
                await asyncio.sleep(e.value + 1)
            except Exception:
                continue

        # --- ОТЧЕТ ---
        date_str = f"{start_date.strftime('%d.%m')} - {datetime.now().strftime('%d.%m')}"
        voice_str = format_duration(total_voice_seconds)

        report = f"📊 **Статистика чата**\n"
        report += f"📅 Период: {date_str} ({period_days} дн.)\n"
        report += f"✉️ Сообщений: {total_messages}\n"
        report += f"🎙 Общее ГС: {voice_str}\n\n"

        # Топ слов
        report += "🗣 **Топ-15 слов:**\n"
        if words_counter:
            for i, (w, c) in enumerate(words_counter.most_common(15), 1):
                if w in bad_words_counter: w = f"||{w}||"
                report += f"{i}. {w} — {c}\n"
        else:
            report += "_Пусто_\n"

        # Топ мата
        report += "\n🤬 **Топ-10 ругательств:**\n"
        if bad_words_counter:
            for i, (w, c) in enumerate(bad_words_counter.most_common(10), 1):
                report += f"{i}. ||{w}|| — {c}\n"
        else:
            report += "✨ _Культурный чат_ ✨\n"

        # Топ смеха (НОВОЕ)
        report += "\n😂 **Топ-5 хохотунов:**\n"
        if users_laugh_counter:
            for i, (u, c) in enumerate(users_laugh_counter.most_common(5), 1):
                report += f"{i}. **{u}** — {c} раз\n"
        else:
            report += "_Слишком серьезные_ 🗿\n"

        # Топ людей
        report += "\n🏆 **Топ-10 активных:**\n"
        if users_msg_counter:
            for i, (u, c) in enumerate(users_msg_counter.most_common(10), 1):
                v_sec = users_voice_counter.get(u, 0)
                v_str = f" | 🎙 {format_duration(v_sec)}" if v_sec > 0 else ""
                report += f"{i}. **{u}** — {c} смс{v_str}\n"
        else:
            report += "_Пусто_\n"

        chat_title = message.chat.title or "Chat"
        await smart_reply(status_msg, report, title=f"Stats: {chat_title}")

    except Exception as e:
        await status_msg.edit(f"❌ Ошибка анализа: {e}")