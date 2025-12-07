from pyrogram import filters
from src.state import SETTINGS


async def check_access_func(_, client, message):
    """
    Фильтр доступа.
    Возвращает True, если пользователю разрешено использовать бота.
    """
    # 1. Исходящие (свои) сообщения всегда разрешены
    # Это значит, что ТЫ сам себя никогда не заблокируешь
    if message.outgoing:
        return True

    # 2. Получаем ID отправителя
    # Если это ЛС, берем from_user.id. Если группа, тоже берем from_user.id
    if message.from_user:
        sender_id = message.from_user.id
    else:
        # Если from_user нет (например, анонимный админ или канал), берем ID чата
        sender_id = message.chat.id

    # 3. Проверка Черного Списка
    # Гарантируем, что сравниваем int с int
    blacklist = SETTINGS.get("blacklist", [])

    if sender_id in blacklist:
        # Пишем в лог, что заблокировали попытку (для отладки)
        print(f"🛡 Access DENIED for user: {sender_id} (in Blacklist)")
        return False

    return True


# Создаем объект фильтра
AccessFilter = filters.create(check_access_func)