from __future__ import annotations

from typing import Any, Iterable

async def fetch_read_boundaries(client: Any, peer_ids: Iterable[int]) -> dict[int, dict[str, int]]:
    """Read exact Telegram inbox boundaries through messages.getPeerDialogs."""
    from pyrogram.raw import functions, types
    from pyrogram.utils import get_peer_id

    unique = list(dict.fromkeys(int(item) for item in peer_ids))
    result: dict[int, dict[str, int]] = {}
    for offset in range(0, len(unique), 100):
        chunk = unique[offset:offset + 100]
        input_peers = [
            types.InputDialogPeer(peer=await client.resolve_peer(peer_id))
            for peer_id in chunk
        ]
        response = await client.invoke(functions.messages.GetPeerDialogs(peers=input_peers))
        for dialog in getattr(response, "dialogs", []) or []:
            peer_id = int(get_peer_id(dialog.peer))
            result[peer_id] = {
                "read_inbox_max_id": int(getattr(dialog, "read_inbox_max_id", 0) or 0),
                "unread_count": int(getattr(dialog, "unread_count", 0) or 0),
                "last_message_id": int(getattr(dialog, "top_message", 0) or 0),
            }
    return result


def read_update(update: Any) -> tuple[int, int, int] | None:
    from pyrogram.raw import types
    from pyrogram.utils import get_peer_id

    if isinstance(update, types.UpdateReadHistoryInbox):
        return (
            int(get_peer_id(update.peer)),
            int(update.max_id or 0),
            int(update.still_unread_count or 0),
        )
    return None
