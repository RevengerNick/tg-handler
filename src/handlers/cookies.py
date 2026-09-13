from __future__ import annotations

from pyrogram import Client, filters

from src.downloader import get_downloader_runtime
from src.downloader.cookies import CookieStore
from src.downloader.errors import DownloaderError
from src.downloader.platforms import detect_platform, extract_url, validate_url


@Client.on_message(filters.me & filters.command(["cookies", "куки"], prefixes="."))
async def cookies_handler(client, message):
    runtime = get_downloader_runtime()
    store = CookieStore(runtime.settings.cookies_dir)
    arguments = (message.text or "").split()
    if len(arguments) == 1:
        lines = ["🍪 **Cookies**"]
        for status in store.inspect_all():
            if not status.exists:
                lines.append(f"❌ `{status.path.name}` — отсутствует")
                continue
            modified = (
                status.modified_at.strftime("%Y-%m-%d %H:%M")
                if status.modified_at
                else "?"
            )
            lines.append(
                f"✅ `{status.path.name}` — изменён {modified}; "
                f"активных записей: {status.valid_rows}"
            )
        lines.append("\nПроверка: `.cookies test instagram [URL]`")
        return await message.edit("\n".join(lines))

    if len(arguments) < 3 or arguments[1].lower() != "test":
        return await message.edit(
            "Использование: `.cookies test instagram|youtube|x [URL]`"
        )
    platform_name = arguments[2].lower()
    try:
        ok, detail = store.validate_for(platform_name)
    except ValueError as error:
        return await message.edit(f"❌ {error}")
    if not ok:
        return await message.edit(f"🔐 {platform_name.title()}: {detail}")

    url = extract_url(message.text)
    if not url:
        return await message.edit(f"✅ {platform_name.title()}: {detail}")
    try:
        url = validate_url(url)
        detected = detect_platform(url)
        await message.edit(f"🔎 Проверяю {detected} cookies без скачивания…")
        metadata = await runtime.service.analyze(url, detected)
        await message.edit(
            f"✅ {detected}: авторизация принята, доступно «{metadata.title[:100]}»"
        )
    except DownloaderError as error:
        await message.edit(error.user_message)
