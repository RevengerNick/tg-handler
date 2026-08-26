from __future__ import annotations

import asyncio
from typing import Any


class ClientRegistry:
    """Holds already-started clients; it never opens a Telegram session itself."""

    def __init__(self) -> None:
        self._clients: list[Any] = []
        self._self_ids: dict[Any, int] = {}
        self._lock = asyncio.Lock()
        self._identity_lock = asyncio.Lock()

    async def add(self, client: Any, self_id: int | None = None) -> bool:
        async with self._lock:
            added = client not in self._clients
            if client not in self._clients:
                self._clients.append(client)
            if self_id is not None:
                self._self_ids[client] = int(self_id)
            return added

    async def remove(self, client: Any) -> None:
        async with self._lock:
            if client in self._clients:
                self._clients.remove(client)
            self._self_ids.pop(client, None)

    def primary(self) -> Any:
        if not self._clients:
            raise RuntimeError("Telegram client is not connected")
        return self._clients[0]

    async def self_id(self, client: Any | None = None) -> int:
        """Return the cached account id without an RPC on every Reader event."""
        selected = client or self.primary()
        cached = self._self_ids.get(selected)
        if cached is not None:
            return cached

        # A fallback is needed for tests and older callers, but a burst of
        # updates must still perform at most one users.GetFullUser request.
        async with self._identity_lock:
            cached = self._self_ids.get(selected)
            if cached is not None:
                return cached
            me = await selected.get_me()
            value = int(me.id)
            self._self_ids[selected] = value
            return value

    @property
    def ready(self) -> bool:
        return bool(self._clients)

    @property
    def count(self) -> int:
        return len(self._clients)
