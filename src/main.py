import asyncio
import os
import aiohttp
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import API_ID, API_HASH, PHONES, SESSIONS_DIR, WEB_PORT, ensure_runtime_dirs
from src.services.auth_qr import login_via_qr
from src.services.connection import check_internet as conn_check_internet, reconnect_client, check_client_health
import uvicorn


# ============== МОНИТОРИНГ СОЕДИНЕНИЯ ==============

async def check_internet() -> bool:
    """Быстрая проверка интернета через несколько DNS."""
    urls = ["https://www.google.com", "https://telegram.org", "https://1.1.1.1"]
    for url in urls:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return True
        except:
            continue
    return False


async def wait_for_internet(max_wait: int = 300) -> bool:
    """Ждёт восстановления интернета."""
    print("⏳ Ожидание интернета...")
    waited = 0
    while waited < max_wait:
        if await check_internet():
            return True
        await asyncio.sleep(5)
        waited += 5
    return False


async def keep_alive_monitor(apps: list[Client], interval: int = 30):
    """
    Фоновый мониторинг соединения.
    НЕ БЛОКИРУЕТ обработку сообщений - работает параллельно с idle().
    Проверяет реальное здоровье соединения через get_me(), а не только флаг is_connected.
    """
    print(f"🔁 Keep-alive monitor запущен (интервал: {interval}с)")

    while True:
        try:
            await asyncio.sleep(interval)

            # Проверяем интернет через TCP-сокет (быстро, без HTTP)
            if not await conn_check_internet():
                print("🔌 Потеряно соединение с интернетом")

                if await wait_for_internet(max_wait=300):
                    print("✅ Интернет восстановлен!")
                else:
                    print("❌ Не удалось дождаться интернета (5 мин)")
                    continue

            # Проверяем реальное состояние каждого клиента (get_me(), не is_connected)
            for app in apps:
                healthy = await check_client_health(app)
                if not healthy:
                    print(f"⚠️ {app.name}: соединение мёртвое, переподключаю...")
                    ok = await reconnect_client(app, max_attempts=5)
                    if ok:
                        print(f"✅ {app.name} переподключен!")
                    else:
                        print(f"❌ {app.name}: не удалось переподключиться")

        except asyncio.CancelledError:
            print("🛑 Keep-alive monitor остановлен")
            break
        except Exception as e:
            print(f"⚠️ Ошибка в мониторе: {e}")
            await asyncio.sleep(10)


# ============== АВТОРИЗАЦИЯ ==============

async def interactive_auth(app: Client):
    """
    Интерактивная проверка авторизации (QR или СМС).
    """
    print(f"\n🔄 Проверка сессии для: {app.name}")

    try:
        await app.connect()
    except Exception as e:
        print(f"⚠️ Ошибка подключения: {e}")
        try:
            if os.path.exists(f"{app.name}.session"):
                os.remove(f"{app.name}.session")
                print("🗑 Битый файл сессии удален. Попробуйте снова.")
            return False
        except:
            return False

    # 1. Проверяем, залогинены ли мы уже
    try:
        me = await app.get_me()
        print(f"✅ Сессия активна: {me.first_name}")
        await app.disconnect()
        return True
    except Exception:
        print("👤 Требуется вход.")

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
            print(f"📤 Отправляю код на {app.phone_number}...")
            sent = await app.send_code(app.phone_number)
        except Exception as e:
            print(f"❌ Ошибка отправки кода: {e}")
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
                print(f"❌ Ошибка: {e}");
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
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_holder["server"] = server
    await server.serve()


# ============== MAIN ==============

async def main():
    # ЭТАП 0: ЗАПУСК ВЕБ-СЕРВЕРА
    web_task = None
    web_server = {}

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
            print("⚠️ Нет интернета при старте!")
            if not await wait_for_internet(max_wait=60):
                print("❌ Нет интернета. Запустите скрипт позже.")
                return

        # ЭТАП 1: АВТОРИЗАЦИЯ
        print("\n=== ЭТАП 1: АВТОРИЗАЦИЯ ===")
        valid_apps = []
        for app in apps:
            if await interactive_auth(app):
                valid_apps.append(app)
            else:
                print(f"⚠️ Скипаем {app.name} (не удалось войти)")

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
            except Exception as e:
                print(f"❌ Ошибка при старте {app.name}: {e}")

        if started_apps:
            print("\n🤖 Бот запущен. Нажмите Ctrl+C для остановки.")
            
            # Запускаем мониторинг как ФОНОВУЮ задачу
            monitor_task = asyncio.create_task(keep_alive_monitor(started_apps, interval=30))
            
            try:
                await idle()  # Это главный цикл Pyrogram для сообщений
            finally:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass
                
                for app in started_apps:
                    await app.stop()

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
