import asyncio
import socket
import logging
import time
from typing import Optional
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyDuplicated, AuthKeyInvalid, SessionRevoked, UserDeactivated, FloodWait
)

logger = logging.getLogger(__name__)

# Проверяем разные сети и порты: часть провайдеров/Raspberry Pi-сетей режет
# публичный DNS, хотя HTTPS и Telegram при этом доступны.
INTERNET_ENDPOINTS = (
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
    ("149.154.167.50", 443),
)

async def check_internet(
    host: Optional[str] = None,
    port: Optional[int] = None,
    timeout: float = 3.0,
) -> bool:
    endpoints = ((host, port or 53),) if host else INTERNET_ENDPOINTS
    loop = asyncio.get_running_loop()
    for endpoint_host, endpoint_port in endpoints:
        try:
            connected = await asyncio.wait_for(
                loop.run_in_executor(
                    None, _sync_check_socket, endpoint_host, endpoint_port, timeout
                ),
                timeout=timeout + 1,
            )
            if connected:
                return True
        except (OSError, asyncio.TimeoutError):
            continue
    return False

def _sync_check_socket(host: str, port: int, timeout: float) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    finally:
        sock.close()

async def wait_for_internet(
    max_wait: Optional[float] = None,
    check_interval: float = 5,
    max_interval: float = 600,
) -> bool:
    """Ждёт сеть с backoff; ``max_wait=None`` означает ждать бесконечно."""
    started = time.monotonic()
    current_interval = max(1.0, check_interval)
    max_interval = max(current_interval, max_interval)

    while True:
        if await check_internet():
            return True

        elapsed = time.monotonic() - started
        if max_wait is not None and elapsed >= max_wait:
            return False

        sleep_for = current_interval
        if max_wait is not None:
            sleep_for = min(sleep_for, max_wait - elapsed)
        logger.warning("Интернет недоступен; следующая проверка через %.0f с", sleep_for)
        await asyncio.sleep(max(0, sleep_for))
        current_interval = min(current_interval * 2, max_interval)

async def _force_disconnect(client: Client) -> None:
    """
    Принудительно разрывает соединение, обходя проверки флагов Pyrogram.

    Проблема: stop() = terminate() + disconnect().
    Если is_initialized уже False (watchdog упал сам) — terminate() бросает
    ConnectionError и stop() прерывается, НЕ вызывая disconnect().
    В итоге is_connected остаётся True и start() падает с "Client is already connected".

    Решение: вызываем terminate() и disconnect() раздельно, каждый в своём try/except.
    """
    # 1. Останавливаем диспетчер/воркеры (если ещё живы)
    if client.is_initialized:
        try:
            await asyncio.wait_for(client.terminate(), timeout=10)
        except Exception as e:
            logger.debug(f"terminate() skipped: {e}")

    # 2. Закрываем TCP-сокет и сессию (если ещё подключены)
    if client.is_connected:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
        except Exception as e:
            logger.debug(f"disconnect() skipped: {e}")

    # 3. Форсированно сбрасываем флаги — на случай если выше всё равно упало
    if client.is_connected:
        logger.warning(f"[{getattr(client, 'name', '?')}] Принудительный сброс is_connected=False")
        client.is_connected = False
    if client.is_initialized:
        client.is_initialized = False


async def reconnect_client(
    client: Client,
    max_attempts: int = 5,
    base_delay: int = 5,
    offline_max_interval: int = 600,
) -> bool:
    client_name = getattr(client, 'name', 'unknown')
    for attempt in range(1, max_attempts + 1):
        try:
            if not await check_internet():
                await wait_for_internet(
                    max_wait=None,
                    check_interval=base_delay,
                    max_interval=offline_max_interval,
                )

            await _force_disconnect(client)
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
    Проверяет реальное здоровье соединения лёгким MTProto ping.

    ``get_me()`` здесь использовать нельзя: Pyrogram отправляет
    ``users.GetFullUser``, а периодический healthcheck быстро упирается в
    FloodWait. Сам FloodWait также подтверждает, что соединение с Telegram
    живо, и не должен запускать переподключение.
    """
    try:
        if not client.is_connected:
            return False
        from pyrogram.raw import functions

        ping_id = time.time_ns() & ((1 << 63) - 1)
        await asyncio.wait_for(client.invoke(functions.Ping(ping_id=ping_id)), timeout=10)
        return True
    except FloodWait:
        return True
    except asyncio.TimeoutError:
        return False
    except Exception:
        return False
