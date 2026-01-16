import asyncio
import os
import sys  # Нужно для exit(1)
from threading import Thread

import uvicorn
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import API_ID, API_HASH, PHONES
from src.services.auth_qr import login_via_qr
from src.web_server import app as web_app

def run_web_server():
    """Запуск сервера на 0.0.0.0 для доступа из Docker-сети Cloudflare"""
    uvicorn.run(web_app, host="0.0.0.0", port=8111, log_level="error")

async def interactive_auth(app: Client):
    """
    Интерактивная проверка авторизации (QR или СМС).
    """
    print(f"\n🔄 Проверка сессии для: {app.name}")

    try:
        await app.connect()
    except Exception as e:
        # Иногда connect падает, если файл сессии битый, пробуем удалить
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
    # ВНИМАНИЕ: Если запуск идет через Systemd (фоном), input() вызовет ошибку EOFError.
    # Мы её поймаем в main и перезапустим скрипт, но авторизоваться можно только руками в консоли.
    print("-----------------------------------")
    print("Выберите метод входа:")
    print("[Enter] - QR Код (Рекомендуется, надежно)")
    print("[2]     - Номер телефона (СМС/Код)")

    try:
        choice = input("Ваш выбор: ").strip()
    except EOFError:
        print("❌ Ошибка: Нет доступа к консоли (видимо, запуск через Systemd).")
        print("   Запустите скрипт вручную один раз для авторизации: python -m src.main")
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
                    await app.check_password(pw)
                    break
                except PasswordHashInvalid:
                    print("❌ Неверный пароль.")
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                await app.disconnect()
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


async def main():
    if not os.path.exists("sessions"):
        os.makedirs("sessions")

    Thread(target=run_web_server, daemon=True).start()
    print("🌐 Локальный веб-сервер запущен на порту 8000")
    # Инициализация клиентов
    apps = [
        Client(
            name=f"sessions/{p.strip().replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=p.strip(),
            plugins=dict(root="src.handlers"),
            ipv6=False,  # <--- ВАЖНО: Лечит зависания сети на Raspberry Pi
            workdir="."
        ) for p in PHONES if p.strip()
    ]

    if not apps:
        print("❌ Номера телефонов не найдены в .env")
        sys.exit(1)  # Выход с ошибкой

    # ЭТАП 1: АВТОРИЗАЦИЯ
    print("\n=== ЭТАП 1: АВТОРИЗАЦИЯ ===")
    valid_apps = []
    for app in apps:
        # Пытаемся авторизоваться. Если это автозапуск (systemd) и сессии нет,
        # input() упадет, вернет False, и мы просто не добавим этот app в valid_apps.
        if await interactive_auth(app):
            valid_apps.append(app)
        else:
            print(f"⚠️ Скипаем {app.name} (не удалось войти или нет консоли)")

    if not valid_apps:
        print("❌ Нет активных сессий. Бот не может быть запущен.")
        # Завершаем с кодом 1, чтобы Systemd увидел ошибку, но не спамил рестартами,
        # если проблема в отсутствии сессии, лучше запустить руками.
        sys.exit(1)

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

        # Если здесь произойдет разрыв соединения, idle() выбросит исключение
        await idle()

        for app in started_apps:
            await app.stop()
    else:
        print("❌ Ни один клиент не запустился.")
        sys.exit(1)  # Перезапуск


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Остановка пользователем")
    except Exception as e:
        print(f"\n🔥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
        # Самое важное: выходим с кодом 1.
        # Systemd увидит это и выполнит Restart=always
        sys.exit(1)