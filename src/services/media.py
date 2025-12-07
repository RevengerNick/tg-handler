import asyncio
import os
import re
import logging
import yt_dlp
from yandex_music import Client as YMClient
from src.config import YANDEX_TOKEN

# Инициализация Yandex Music
ym_client = YMClient(YANDEX_TOKEN).init() if YANDEX_TOKEN else None
logger = logging.getLogger(__name__)


async def download_video(link: str, quality_mode: int):
    """
    Скачивание видео/аудио через yt-dlp.
    quality_mode:
    0 - Лучшее качество (видео + аудио) -> MP4
    1 - Низкое качество (для экономии трафика) -> MP4
    2 - Только аудио -> MP3
    """

    def _sync_dl():
        options = {
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            # ВАЖНО: Пакуем в MP4, чтобы Telegram нормально отображал превью
            'merge_output_format': 'mp4',
            'geo_bypass': True,
        }

        if quality_mode == 2:
            # --- AUDIO (MP3) ---
            options.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                # Для аудио mp4 контейнер не нужен
                'merge_output_format': None
            })
        elif quality_mode == 1:
            # --- LOW QUALITY (480p) ---
            # Ищем формат mp4 высотой <= 480
            options.update({'format': 'bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]/best'})
        else:
            # --- BEST QUALITY ---
            options.update({'format': 'bestvideo+bestaudio/best'})

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(link, download=True)

                if quality_mode == 2:
                    title = info['title']
                    # yt-dlp чистит имя файла, но мы перестрахуемся
                    sanitized_title = re.sub(r'[\\/*?:"<>|]', "", title)
                    # Ищем файл с расширением mp3 (так как постпроцессор его конвертировал)
                    # Иногда yt-dlp меняет имя, поэтому лучше вернуть ожидаемое имя
                    # Но самый надежный способ - найти файл в папке, который начинается так же

                    # Простой вариант возврата (обычно работает корректно с outtmpl)
                    return f"{sanitized_title}.mp3"

                # Для видео возвращаем имя, которое подготовил yt-dlp
                # prepare_filename может вернуть расширение webm, но merge_output_format сделает mp4
                # Поэтому мы подменяем расширение в пути
                filename = ydl.prepare_filename(info)
                base_name = filename.rsplit('.', 1)[0]
                return f"{base_name}.mp4"

        except Exception as e:
            print(f"yt-dlp Error: {e}")
            return None

    return await asyncio.to_thread(_sync_dl)


async def download_yandex_track(url: str):
    """
    Скачивание треков с Яндекс.Музыки.
    Возвращает список путей к скачанным файлам.
    """

    def _sync_download():
        tracks_paths = []
        try:
            if not ym_client:
                print("Yandex Token missing")
                return []

            tracks = []
            if "track" in url:
                # Извлекаем ID трека
                match = re.search(r'track/(\d+)', url)
                if match:
                    track_id = match.group(1)
                    tracks = [ym_client.tracks([track_id])[0]]
            elif "album" in url:
                # Извлекаем ID альбома
                match = re.search(r'album/(\d+)', url)
                if match:
                    album_id = match.group(1)
                    album = ym_client.albums_with_tracks(album_id)
                    if album and album.volumes:
                        tracks = album.volumes[0]

            if not tracks:
                return []

            for track in tracks:
                # Получаем инфо для скачивания
                info = track.get_download_info(get_direct_links=True)
                if not info: continue

                # Скачиваем байты
                direct_link = info[0].get_direct_link()
                # Импортируем requests локально, чтобы не засорять глобальную область
                import requests
                track_data = requests.get(direct_link).content

                # Формируем имя: "Название - Артист.mp3"
                safe_title = re.sub(r'[\\/*?:"<>|]', "", track.title)
                safe_artist = re.sub(r'[\\/*?:"<>|]', "", track.artists[0].name if track.artists else "Unknown")
                filename = f"{safe_title} - {safe_artist}.mp3"

                with open(filename, 'wb') as f:
                    f.write(track_data)

                tracks_paths.append(filename)

            return tracks_paths
        except Exception as e:
            print(f"Yandex Music Error: {e}")
            return []

    return await asyncio.to_thread(_sync_download)