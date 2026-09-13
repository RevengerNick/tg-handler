import asyncio
import os
import re

from yandex_music import Client as YMClient

from src.config import YANDEX_TOKEN
from src.services.files import output_path

# Инициализация Yandex Music
ym_client = YMClient(YANDEX_TOKEN).init() if YANDEX_TOKEN else None


async def download_yandex_track(url: str, destination_dir: str | None = None):
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
                match = re.search(r"track/(\d+)", url)
                if match:
                    track_id = match.group(1)
                    tracks = [ym_client.tracks([track_id])[0]]
            elif "album" in url:
                # Извлекаем ID альбома
                match = re.search(r"album/(\d+)", url)
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
                if not info:
                    continue

                # Скачиваем байты
                direct_link = info[0].get_direct_link()
                # Импортируем requests локально, чтобы не засорять глобальную область
                import requests

                response = requests.get(direct_link, timeout=(5, 60))
                response.raise_for_status()
                track_data = response.content

                # Формируем имя: "Название - Артист.mp3"
                safe_title = re.sub(r'[\\/*?:"<>|]', "", track.title)
                safe_artist = re.sub(
                    r'[\\/*?:"<>|]',
                    "",
                    track.artists[0].name if track.artists else "Unknown",
                )
                if destination_dir:
                    os.makedirs(destination_dir, exist_ok=True)
                    filename = os.path.join(
                        destination_dir, f"{safe_title} - {safe_artist}.mp3"
                    )
                else:
                    filename = output_path(
                        "downloads", f"{safe_title} - {safe_artist}.mp3"
                    )

                with open(filename, "wb") as f:
                    f.write(track_data)

                tracks_paths.append(filename)

            return tracks_paths
        except Exception as e:
            print(f"Yandex Music Error: {e}")
            return []

    return await asyncio.to_thread(_sync_download)
