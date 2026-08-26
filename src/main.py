import asyncio
import os
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import (
    API_ID, API_HASH, PHONES, SESSIONS_DIR, WEB_PORT, WEB_BIND_HOST, ensure_runtime_dirs,
    HEALTH_CHECK_INTERVAL, MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY,
    OFFLINE_RETRY_MAX_INTERVAL, RECONNECT_COOLDOWN,
)
from src.services.auth_qr import login_via_qr
from src.services.connection import (
    check_internet, wait_for_internet, reconnect_client, check_client_health,
)
from src.telegram_reader import get_runtime as get_reader_runtime
import uvicorn


# ============== МОНИТОРИНГ СОЕДИНЕНИЯ ==============

async def keep_alive_monitor(apps: list[Client], interval: int = 30, on_reconnect=None):
    """
    Фоновый мониторинг соединения.
    НЕ БЛОКИРУЕТ обработку сообщений - работает параллельно с idle().
    Проверяет реальное здоровье соединения через get_me(), а не только флаг is_connected.
    """
    print(f"🔁 Keep-alive monitor запущен (интервал: {interval}с)")
    retry_after: dict[str, float] = {}

    while True:
        try:
            await asyncio.sleep(interval)

            # Проверяем интернет через TCP-сокет (быстро, без HTTP)
            if not await check_internet():
                print("🔌 Потеряно соединение с интернетом")
                await wait_for_internet(
                    max_wait=None,
                    check_interval=RECONNECT_DELAY,
                    max_interval=OFFLINE_RETRY_MAX_INTERVAL,
                )
                print("✅ Интернет восстановлен!")

            # Проверяем реальное состояние каждого клиента (get_me(), не is_connected)
            for app in apps:
                healthy = await check_client_health(app)
                if healthy:
                    retry_after.pop(app.name, None)
                    continue

                now = asyncio.get_running_loop().time()
                if now < retry_after.get(app.name, 0):
                    continue

                print("⚠️ Telegram client: соединение мёртвое, переподключаю...")
                ok = await reconnect_client(
                    app,
                    max_attempts=MAX_RECONNECT_ATTEMPTS,
                    base_delay=RECONNECT_DELAY,
                    offline_max_interval=OFFLINE_RETRY_MAX_INTERVAL,
                )
                if ok:
                    retry_after.pop(app.name, None)
                    print("✅ Telegram client переподключен!")
                    if on_reconnect is not None:
                        try:
                            await on_reconnect(app)
                        except Exception as error:
                            print(f"⚠️ Telegram Reader catch-up не выполнен: {type(error).__name__}")
                else:
                    retry_after[app.name] = (
                        asyncio.get_running_loop().time() + RECONNECT_COOLDOWN
                    )
                    print(
                        "❌ Telegram client: пока не удалось; "
                        f"новая серия попыток через {RECONNECT_COOLDOWN} с"
                    )

        except asyncio.CancelledError:
            print("🛑 Keep-alive monitor остановлен")
            break
        except Exception as e:
            print(f"⚠️ Ошибка в мониторе: {type(e).__name__}")
            await asyncio.sleep(10)


# ============== АВТОРИЗАЦИЯ ==============

async def interactive_auth(app: Client):
    """
    Интерактивная проверка авторизации (QR или СМС).
    """
    print("\n🔄 Проверка настроенной Telegram-сессии")

    while True:
        for attempt in range(1, 4):
            try:
                await app.connect()
                break
            except Exception as e:
                print(f"⚠️ Ошибка подключения ({attempt}/3): {type(e).__name__}")
                # Сетевой сбой не означает, что файл сессии повреждён. Никогда
                # не удаляем его автоматически: ждём сеть и повторяем.
                if not await check_internet():
                    print("⏳ Нет сети; продолжаю ждать восстановления...")
                    await wait_for_internet(
                        max_wait=None,
                        check_interval=RECONNECT_DELAY,
                        max_interval=OFFLINE_RETRY_MAX_INTERVAL,
                    )
                elif attempt < 3:
                    await asyncio.sleep(RECONNECT_DELAY * attempt)
        else:
            print("❌ Не удалось подключить сессию; файл сессии сохранён.")
            return False

        # Проверяем, залогинены ли мы уже. Если сеть пропала ровно во время
        # get_me(), это не должно ошибочно запускать повторную авторизацию.
        try:
            me = await app.get_me()
            print(f"✅ Сессия активна: {me.first_name}")
            await app.disconnect()
            return True
        except Exception:
            if await check_internet():
                print("👤 Требуется вход.")
                break
            print("⏳ Сеть пропала при проверке сессии; жду и повторяю.")
            if app.is_connected:
                await app.disconnect()
            await wait_for_internet(
                max_wait=None,
                check_interval=RECONNECT_DELAY,
                max_interval=OFFLINE_RETRY_MAX_INTERVAL,
            )

    # 2. Выбор метода входа
    print("-----------------------------------")
    print("Выберите метод входа:")
    print("[Enter] - QR Код (Рекомендуется, надежно)")
    print("[2]     - Номер телефона (СМС/Код)")
    try:
        choice = input("Ваш выбор: ").strip()
    except EOFError:
        print("⚠️ Нужен интерактивный терминал для первого входа.")
        await app.disconnect()
        return False

    if choice == "2":
        # --- СТАРЫЙ МЕТОД (СМС) ---
        try:
            print("📤 Отправляю код на настроенный номер...")
            sent = await app.send_code(app.phone_number)
        except Exception as e:
            print(f"❌ Ошибка отправки кода: {type(e).__name__}")
            await app.disconnect()
            return False

        while True:
            code = input(f"📩 Введите код: ").strip()
            try:
                await app.sign_in(app.phone_number, sent.phone_code_hash, code)
                break
            except SessionPasswordNeeded:
                pw = input("🔑 2FA Пароль: ").strip()
                try:
                    await app.check_password(pw); break
                except PasswordHashInvalid:
                    print("❌ Неверный пароль.")
            except Exception as e:
                print(f"❌ Ошибка: {type(e).__name__}");
                await app.disconnect();
                return False

        print("✅ Вход по СМС успешен!")
        await app.disconnect()
        return True

    else:
        # --- НОВЫЙ МЕТОД (QR) ---
        success = await login_via_qr(app)

        if app.is_connected:
            await app.disconnect()

        return success


# ============== WEB SERVER ==============

async def start_web_server(server_holder: dict):
    """Запуск FastAPI сервера в фоне."""
    from src.web_server import app
    
    # Внешний адрес MY_DOMAIN и локальный порт WEB_PORT настраиваются отдельно.
    port = WEB_PORT

    print(f"🌐 Запуск веб-сервера на порту {port}...")
    config = uvicorn.Config(app, host=WEB_BIND_HOST, port=port, log_level="error")
    server = uvicorn.Server(config)
    server_holder["server"] = server
    await server.serve()


# ============== MAIN ==============

async def main():
    # ЭТАП 0: ЗАПУСК ВЕБ-СЕРВЕРА
    web_task = None
    web_server = {}

    reader_runtime = get_reader_runtime()

    try:
        ensure_runtime_dirs()

        if API_ID <= 0 or not API_HASH:
            print("❌ Заполните API_ID и API_HASH в .env перед запуском.")
            return

        web_task = asyncio.create_task(start_web_server(web_server))

        # Инициализация клиентов
        apps = [
            Client(
                name=os.path.join(SESSIONS_DIR, p.strip().replace('+', '')),
                api_id=API_ID,
                api_hash=API_HASH,
                phone_number=p.strip(),
                plugins=dict(root="src.handlers")
            ) for p in PHONES if p.strip()
        ]

        if not apps:
            print("❌ Номера телефонов не найдены в .env")
            return

        # Проверяем интернет перед стартом
        if not await check_internet():
            print("⚠️ Нет интернета при старте; программа продолжит ждать.")
            await wait_for_internet(
                max_wait=None,
                check_interval=RECONNECT_DELAY,
                max_interval=OFFLINE_RETRY_MAX_INTERVAL,
            )
            print("✅ Интернет восстановлен!")

        # ЭТАП 1: АВТОРИЗАЦИЯ
        print("\n=== ЭТАП 1: АВТОРИЗАЦИЯ ===")
        valid_apps = []
        for app in apps:
            if await interactive_auth(app):
                valid_apps.append(app)
            else:
                print("⚠️ Пропускаю Telegram client (не удалось войти)")

        if not valid_apps:
            print("❌ Нет активных сессий. Бот не может быть запущен.")
            return

        # ЭТАП 2: ЗАПУСК
        print("\n=== ЭТАП 2: ЗАПУСК БОТА ===")
        started_apps = []
        for app in valid_apps:
            try:
                await app.start()
                me = await app.get_me()
                print(f"🟢 {me.first_name} онлайн и готов к работе!")
                started_apps.append(app)
                if reader_runtime.settings.enabled:
                    await reader_runtime.register_client(app)
            except Exception as e:
                print(f"❌ Ошибка при старте Telegram client: {type(e).__name__}")

        if not started_apps:
            print("⚠️ Клиенты пока не запустились; монитор продолжит попытки.")

        print("\n🤖 Бот запущен. Нажмите Ctrl+C для остановки.")
            
        # Мониторим все авторизованные клиенты, включая не запустившиеся из-за
        # временной сетевой ошибки на старте.
        monitor_task = asyncio.create_task(
            keep_alive_monitor(
                valid_apps,
                interval=HEALTH_CHECK_INTERVAL,
                on_reconnect=reader_runtime.register_client if reader_runtime.settings.enabled else None,
            )
        )
            
        try:
            await idle()  # Это главный цикл Pyrogram для сообщений
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            for app in valid_apps:
                try:
                    await reader_runtime.unregister_client(app)
                    if app.is_initialized:
                        await app.stop()
                    elif app.is_connected:
                        await app.disconnect()
                except Exception as e:
                    print(f"⚠️ Ошибка остановки Telegram client: {type(e).__name__}")

    finally:
        # Останавливаем веб-сервер при выходе из main
        if web_task:
            server = web_server.get("server")
            if server:
                server.should_exit = True
            else:
                web_task.cancel()
            try:
                await asyncio.wait_for(web_task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass


if __name__ == "__main__":
    asyncio.run(main())
