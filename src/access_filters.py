from pyrogram import filters
from src.state import SETTINGS


async def check_access_func(_, client, message):
    """
    Фильтр доступа.
    Возвращает True, если пользователю разрешено использовать бота.
    """
    if message.outgoing:
        return True

    if message.from_user:
        sender_id = message.from_user.id
    else:
        sender_id = message.chat.id

    blacklist = SETTINGS.get("blacklist", [])

    if sender_id in blacklist:
        print(f"🛡 Access DENIED for user: {sender_id} (in Blacklist)")
        return False

    return True


AccessFilter = filters.create(check_access_func)