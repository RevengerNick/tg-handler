from __future__ import annotations

import asyncio
from typing import Any


class ClientRegistry:
    """Holds already-started clients; it never opens a Telegram session itself."""

    def __init__(self) -> None:
        self._clients: list[Any] = []
        self._lock = asyncio.Lock()

    async def add(self, client: Any) -> None:
        async with self._lock:
            if client not in self._clients:
                self._clients.append(client)

    async def remove(self, client: Any) -> None:
        async with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def primary(self) -> Any:
        if not self._clients:
            raise RuntimeError("Telegram client is not connected")
        return self._clients[0]

    @property
    def ready(self) -> bool:
        return bool(self._clients)

    @property
    def count(self) -> int:
        return len(self._clients)
