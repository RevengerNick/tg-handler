import asyncio
import socket
import logging
from typing import Optional
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyDuplicated, AuthKeyInvalid, SessionRevoked, UserDeactivated, FloodWait
)

logger = logging.getLogger(__name__)

async def check_internet(host: str = "8.8.8.8", port: int = 53, timeout: float = 3.0) -> bool:
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, _sync_check_socket, host, port, timeout),
            timeout=timeout + 1
        )
        return True
    except Exception:
        return False

def _sync_check_socket(host: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    finally:
        sock.close()

async def wait_for_internet(max_wait: int = 300, check_interval: int = 5) -> bool:
    hosts = ["8.8.8.8", "1.1.1.1", "149.154.167.50"]
    elapsed = 0
    current_interval = check_interval
    
    while elapsed < max_wait:
        for host in hosts:
            if await check_internet(host):
                return True
        await asyncio.sleep(current_interval)
        elapsed += current_interval
        current_interval = min(current_interval * 2, 60)
    return False

async def reconnect_client(client: Client, max_attempts: int = 5, base_delay: int = 5) -> bool:
    client_name = getattr(client, 'name', 'unknown')
    for attempt in range(1, max_attempts + 1):
        try:
            if not await check_internet():
                if not await wait_for_internet():
                    return False

            if client.is_connected:
                try:
                    await asyncio.wait_for(client.stop(), timeout=15)
                except Exception:
                    pass

            await asyncio.sleep(2)
            await client.start()
            logger.info(f"[{client_name}] переподключен (попытка {attempt})")
            return True
        except FloodWait as e:
            logger.warning(f"[{client_name}] FloodWait {e.value}s")
            await asyncio.sleep(e.value)
        except (AuthKeyDuplicated, AuthKeyInvalid, SessionRevoked, UserDeactivated) as e:
            logger.error(f"[{client_name}] фатальная ошибка сессии: {e}")
            return False
        except Exception as e:
            delay = base_delay * attempt
            logger.warning(f"[{client_name}] попытка {attempt}/{max_attempts} неудачна: {e}, ждем {delay}s")
            await asyncio.sleep(delay)
    return False

async def check_client_health(client: Client) -> bool:
    """
    Проверяет реальное здоровье соединения.
    Сначала смотрит на флаг is_connected, затем делает лёгкий RPC-запрос get_me().
    get_me() выявляет "зомби"-соединения, где сокет мёртв, но флаг ещё True.
    """
    try:
        if not client.is_connected:
            return False
        # Пинг реального сервера — выявляет мёртвые сокеты
        await asyncio.wait_for(client.get_me(), timeout=10)
        return True
    except asyncio.TimeoutError:
        return False
    except Exception:
        return False