import logging
from collections.abc import Iterator
from contextlib import suppress

from pyrogram import Client, enums, filters, types
from pyrogram.errors import ChatAdminRequired, FloodWait, RPCError, SlowmodeWait

logger = logging.getLogger(__name__)
_TEXT_LIMIT = 4096
_MENTIONS_PER_MESSAGE = 100


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def build_mention_messages(
    users: list[types.User],
    note: str,
) -> Iterator[tuple[str, list[types.MessageEntity]]]:
    parts: list[str] = []
    entities: list[types.MessageEntity] = []
    length = offset = 0
    suffix = f" - {note}" if note else ""

    for index, user in enumerate(users):
        if user.username:
            label = f"@{user.username}"
        else:
            name = f"{user.first_name or ''} {user.last_name or ''}"
            label = " ".join(name.split()) or "Участник"
        # Keep the note with the final mention when Telegram's limit allows it.
        tail = (
            suffix
            if index == len(users) - 1 and len(label) + len(suffix) <= _TEXT_LIMIT
            else ""
        )
        if parts and (
            len(parts) >= _MENTIONS_PER_MESSAGE
            or length + 2 + len(label) + len(tail) > _TEXT_LIMIT
        ):
            yield ", ".join(parts), entities
            parts, entities = [], []
            length = offset = 0

        if parts:
            length += 2
            offset += 2
        label_units = _utf16_length(label)
        if not user.username:
            entities.append(
                types.MessageEntity(
                    type=enums.MessageEntityType.TEXT_MENTION,
                    offset=offset,
                    length=label_units,
                    user=user,
                )
            )
        parts.append(label)
        length += len(label)
        offset += label_units

    if parts:
        text = ", ".join(parts)
        if len(text) + len(suffix) <= _TEXT_LIMIT:
            yield text + suffix, entities
        else:
            yield text, entities
            yield note, []


@Client.on_message(
    filters.me
    & filters.group
    & filters.text
    & filters.command(["tag", "tagall"], prefixes=".")
)
async def tag_all_handler(client: Client, message: types.Message) -> None:
    arguments = message.text.split(maxsplit=1)
    note = arguments[1].strip() if len(arguments) > 1 else ""
    chat_id = message.chat.id
    seen: set[int] = set()
    users: list[types.User] = []
    sent = 0

    try:
        async for member in client.get_chat_members(chat_id):
            user = member.user if member else None
            if not user or user.id in seen:
                continue
            if member.status in {
                enums.ChatMemberStatus.LEFT,
                enums.ChatMemberStatus.BANNED,
            }:
                continue
            if (
                member.status == enums.ChatMemberStatus.RESTRICTED
                and not member.is_member
            ):
                continue
            seen.add(user.id)
            if not (user.is_bot or user.is_deleted):
                users.append(user)

        if not users:
            await message.edit_text(
                "Не удалось найти участников, которых можно упомянуть."
            )
            return

        # Telegram can return only a subset of the members in some supergroups.
        expected = message.chat.members_count
        if not expected and message.chat.type == enums.ChatType.SUPERGROUP:
            with suppress(RPCError):
                expected = await client.get_chat_members_count(chat_id)

        for text, entities in build_mention_messages(users, note):
            await client.send_message(
                chat_id,
                text,
                entities=entities,
                parse_mode=enums.ParseMode.DISABLED,
                disable_web_page_preview=True,
                message_thread_id=message.message_thread_id,
                reply_to_message_id=message.reply_to_message_id,
            )
            sent += 1
    except ChatAdminRequired:
        status = "Telegram ограничил доступ. Проверьте права аккаунта в группе."
    except (FloodWait, SlowmodeWait) as error:
        status = f"Telegram ограничил отправку. Подождите {error.value} сек."
    except RPCError as error:
        logger.warning("Group mentions failed: %s", type(error).__name__)
        status = "Не удалось получить список участников или отправить упоминания."
    else:
        if expected and len(seen) < expected:
            status = f"Telegram показал {len(seen)} из {expected} участников. Упоминания отправлены по доступному списку."
            with suppress(RPCError):
                await message.edit_text(status)
        else:
            with suppress(RPCError):
                await message.delete()
        return

    if sent:
        status += f" Уже отправлено сообщений: {sent}."
    with suppress(RPCError):
        await message.edit_text(status)
