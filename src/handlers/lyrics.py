import aiohttp
from pyrogram import Client, filters
from src.services import edit_or_reply, save_to_local_web
from src.access_filters import AccessFilter


LRCLIB_API_BASE = "https://lrclib.net/api"


async def search_lyrics(query: str):
    """Поиск песни через LRCLIB API"""
    async with aiohttp.ClientSession() as session:
        params = {"q": query}
        async with session.get(f"{LRCLIB_API_BASE}/search", params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data if data else None
            return None


async def get_lyrics_by_id(track_id: int):
    """Получение текста песни по ID"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{LRCLIB_API_BASE}/get/{track_id}") as resp:
            if resp.status == 200:
                return await resp.json()
            return None


def format_lyrics_text(track_data: dict) -> str:
    """Форматирует данные песни в текст для отправки в Telegram"""
    title = track_data.get("trackName", "Unknown")
    artist = track_data.get("artistName", "Unknown")
    album = track_data.get("albumName", "Unknown")
    duration = track_data.get("duration", 0)
    instrumental = track_data.get("instrumental", False)
    plain_lyrics = track_data.get("plainLyrics", "")
    synced_lyrics = track_data.get("syncedLyrics", "")
    
    # Форматируем длительность
    minutes = duration // 60
    seconds = duration % 60
    duration_str = f"{minutes}:{seconds:02d}"
    
    result = f"🎵 **{title}**\n"
    result += f"👤 **{artist}**\n"
    result += f"💿 {album}\n"
    result += f"⏱️ {duration_str}\n"
    
    if instrumental:
        result += "\n🎹 *Instrumental*\n"
    elif plain_lyrics:
        result += f"\n📜 **Текст:**\n```{plain_lyrics[:3500]}```"
        if len(plain_lyrics) > 3500:
            result += "\n\n*...текст обрезан, используйте `.текстт` для полной версии*"
    elif synced_lyrics:
        result += f"\n📜 **Текст (с таймкодами):**\n```{synced_lyrics[:3500]}```"
        if len(synced_lyrics) > 3500:
            result += "\n\n*...текст обрезан, используйте `.текстт` для полной версии*"
    else:
        result += "\n❌ Текст не найден"
    
    return result


def create_lyrics_webpage(track_data: dict) -> str:
    """Создает HTML страницу с данными песни"""
    title = track_data.get("trackName", "Unknown")
    artist = track_data.get("artistName", "Unknown")
    album = track_data.get("albumName", "Unknown")
    duration = track_data.get("duration", 0)
    instrumental = track_data.get("instrumental", False)
    plain_lyrics = track_data.get("plainLyrics", "")
    synced_lyrics = track_data.get("syncedLyrics", "")
    
    # Форматируем длительность
    minutes = duration // 60
    seconds = duration % 60
    duration_str = f"{minutes}:{seconds:02d}"
    
    # Форматируем текст с таймкодами если есть
    lyrics_content = ""
    if instrumental:
        lyrics_content = "<div class='instrumental'>🎹 Instrumental (нет текста)</div>"
    elif synced_lyrics:
        # Преобразуем synced lyrics в HTML
        lines = synced_lyrics.strip().split('\n')
        lyrics_content = "<div class='synced-lyrics'>"
        for line in lines:
            if line.strip():
                # Выделяем таймкоды
                if '[' in line and ']' in line:
                    parts = line.split(']', 1)
                    timecode = parts[0] + ']'
                    text = parts[1] if len(parts) > 1 else ''
                    lyrics_content += f'<div class="lyric-line"><span class="timecode">{timecode}</span><span class="text">{text}</span></div>'
                else:
                    lyrics_content += f'<div class="lyric-line">{line}</div>'
        lyrics_content += "</div>"
    elif plain_lyrics:
        lyrics_content = f"<pre class='plain-lyrics'>{plain_lyrics}</pre>"
    else:
        lyrics_content = "<div class='no-lyrics'>Текст не найден</div>"
    
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {artist}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #fff;
            min-height: 100vh;
        }}
        .track-header {{
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }}
        .track-title {{
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 10px;
            color: #fff;
        }}
        .track-artist {{
            font-size: 1.3em;
            color: #e0e0e0;
            margin-bottom: 10px;
        }}
        .track-album {{
            font-size: 1em;
            color: #b0b0b0;
            margin-bottom: 5px;
        }}
        .track-duration {{
            font-size: 0.9em;
            color: #909090;
        }}
        .lyrics-container {{
            background: rgba(255,255,255,0.95);
            border-radius: 20px;
            padding: 30px;
            color: #333;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }}
        .lyrics-title {{
            font-size: 1.5em;
            margin-bottom: 20px;
            color: #1e3c72;
            border-bottom: 2px solid #1e3c72;
            padding-bottom: 10px;
        }}
        .synced-lyrics {{
            line-height: 2;
        }}
        .lyric-line {{
            margin: 10px 0;
            padding: 5px 10px;
            border-radius: 5px;
            transition: background 0.3s;
        }}
        .lyric-line:hover {{
            background: rgba(30,60,114,0.1);
        }}
        .timecode {{
            color: #1e3c72;
            font-weight: bold;
            font-family: monospace;
            margin-right: 15px;
            font-size: 0.9em;
        }}
        .plain-lyrics {{
            white-space: pre-wrap;
            line-height: 1.8;
            font-size: 1.1em;
        }}
        .instrumental {{
            text-align: center;
            font-size: 1.2em;
            color: #666;
            padding: 40px;
        }}
        .no-lyrics {{
            text-align: center;
            color: #999;
            padding: 40px;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            color: rgba(255,255,255,0.6);
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="track-header">
        <div class="track-title">{title}</div>
        <div class="track-artist">{artist}</div>
        <div class="track-album">💿 {album}</div>
        <div class="track-duration">⏱️ {duration_str}</div>
    </div>
    
    <div class="lyrics-container">
        <div class="lyrics-title">🎵 Текст песни</div>
        {lyrics_content}
    </div>
    
    <div class="footer">
        via LRCLIB API
    </div>
</body>
</html>"""
    
    return html_content


@Client.on_message(filters.command(["текст", "text", "lyric"], prefixes=".") & AccessFilter)
async def lyrics_handler(client, message):
    """Поиск текста песни и отправка в чат"""
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            return await edit_or_reply(message, "🎵 Укажите название песни: `.текст Bohemian Rhapsody`")
        
        query = args[1].strip()
        await edit_or_reply(message, f"🔍 Ищу: *{query}*...")
        
        # Ищем песню
        results = await search_lyrics(query)
        
        if not results:
            return await edit_or_reply(message, f"❌ Ничего не найдено по запросу: `{query}`")
        
        # Берем первый результат
        track = results[0]
        
        # Если есть ID, получаем полные данные
        track_id = track.get("id")
        if track_id:
            track_data = await get_lyrics_by_id(track_id)
            if track_data:
                track = track_data
        
        # Форматируем и отправляем
        text = format_lyrics_text(track)
        await edit_or_reply(message, text)
        
    except Exception as e:
        await edit_or_reply(message, f"❌ Ошибка: {e}")


@Client.on_message(filters.command(["текстт", "textt", "lyrics"], prefixes=".") & AccessFilter)
async def lyrics_web_handler(client, message):
    """Поиск текста песни и создание веб-страницы"""
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            return await edit_or_reply(message, "🎵 Укажите название песни: `.текстт Bohemian Rhapsody`")
        
        query = args[1].strip()
        await edit_or_reply(message, f"🔍 Ищу и создаю страницу: *{query}*...")
        
        # Ищем песню
        results = await search_lyrics(query)
        
        if not results:
            return await edit_or_reply(message, f"❌ Ничего не найдено по запросу: `{query}`")
        
        # Берем первый результат
        track = results[0]
        
        # Если есть ID, получаем полные данные
        track_id = track.get("id")
        if track_id:
            track_data = await get_lyrics_by_id(track_id)
            if track_data:
                track = track_data
        
        # Создаем HTML страницу
        title = f"{track.get('trackName', 'Unknown')} - {track.get('artistName', 'Unknown')}"
        html_content = create_lyrics_webpage(track)
        
        # Сохраняем в локальный веб
        url = await save_to_local_web(title, html_content)
        
        if url == "error_db":
            return await edit_or_reply(message, "❌ Ошибка сохранения в базу данных")
        
        # Отправляем ссылку
        await edit_or_reply(message, f"🎵 **{title}**\n\n📄 [Открыть текст песни]({url})")
        
    except Exception as e:
        await edit_or_reply(message, f"❌ Ошибка: {e}")
