from __future__ import annotations

import html

from .models import MediaMetadata


def format_duration(value: float | None) -> str | None:
    if value is None:
        return None
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    )


def control_card(metadata: MediaMetadata) -> str:
    lines = [f"🎬 <b>{html.escape(metadata.title)}</b>"]
    if metadata.author:
        lines.append(f"👤 {html.escape(metadata.author)}")
    if duration := format_duration(metadata.duration):
        lines.append(f"⏱ {duration}")
    lines.append(f"🌐 {html.escape(metadata.platform)}")
    if metadata.entry_count > 1:
        lines.append(f"🗂 Элементов: {metadata.entry_count}")
    lines.append("\nВыберите качество:")
    return "\n".join(lines)


def source_status(
    state: str, *, quality: str | None = None, percent: float | None = None
) -> str:
    if state == "analyzing":
        return "🔎 Анализирую ссылку…"
    if state == "waiting":
        return "🎛 Варианты качества отправлены в служебный бот."
    if state == "queued":
        return "⏳ Загрузка поставлена в очередь…"
    if state == "downloading":
        suffix = f" {quality}" if quality else ""
        return f"📥 Скачиваю{suffix}…"
    if state == "fallback":
        return "⚠️ yt-dlp не справился, пробую резервный downloader…"
    if state == "processing":
        return "📦 Обрабатываю файл…"
    if state == "uploading":
        suffix = f" {percent:.0f}%" if percent is not None else ""
        return f"📤 Загружаю в Telegram…{suffix}"
    if state == "done":
        return "✅ Готово"
    return state
