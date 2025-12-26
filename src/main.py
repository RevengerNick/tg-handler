import asyncio
import os
import logging
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import API_ID, API_HASH, PHONES
from src.services.auth_qr import login_via_qr

# Логирование в консоль (чтобы видеть в journalctl)
logging.basicConfig(level=logging.WARNING)


async def interactive_auth(app: Client):
    """
    Интерактивная проверка авторизации (QR или СМС).
    """
    print(f"\n🔄 Проверка сессии для: {app.name}")

    try:
        await app.connect()
    except Exception as e:
        print(f"⚠️ Ошибка подключения (возможно, битая сессия): {e}")
        return False

    try:
        me = await app.get_me()
        print(f"✅ Сессия активна: {me.first_name}")
        await app.disconnect()
        return True
    except Exception:
        print("👤 Требуется вход.")

    print("-----------------------------------")
    print("Выберите метод входа:")
    print("[Enter] - QR Код (Рекомендуется)")
    print("[2]     - Номер телефона (СМС)")
    choice = input("Ваш выбор: ").strip()

    if choice == "2":
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
        success = await login_via_qr(app)
        if app.is_connected:
            await app.disconnect()
        return success


async def main():
    if not os.path.exists("sessions"):
        os.makedirs("sessions")

    # 1. Инициализация
    # УБРАЛИ несуществующие connection_retries и retry_delay
    # ОСТАВИЛИ ipv6=False (это важно для RPi)
    apps = [
        Client(
            name=f"sessions/{p.strip().replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=p.strip(),
            plugins=dict(root="src.handlers"),
            ipv6=False,  # Отключаем IPv6 (лечит зависания)
            workdir="."
        ) for p in PHONES if p.strip()
    ]

    if not apps:
        print("❌ Номера телефонов не найдены в .env")
        return

    # ЭТАП 1: АВТОРИЗАЦИЯ
    # (В режиме демона этот этап просто проверит файлы и пройдет дальше)
    valid_apps = []
    print("\n=== ПРОВЕРКА СЕССИЙ ===")
    for app in apps:
        if os.path.exists(f"{app.name}.session"):
            valid_apps.append(app)
        else:
            # Если запускаем руками - предложит вход.
            # Если запускает systemd - здесь упадет ошибка ввода (EOF), скрипт перезагрузится,
            # но это нормально, так как без сессии бот все равно не может работать.
            try:
                if await interactive_auth(app):
                    valid_apps.append(app)
            except (EOFError, OSError):
                print(f"⚠️ {app.name}: Нет сессии и нет консоли для ввода. Пропуск.")

    if not valid_apps:
        print("❌ Нет активных сессий. Запустите вручную для входа.")
        exit(1)

    # ЭТАП 2: ЗАПУСК
    print(f"\n=== ЗАПУСК БОТА ({len(valid_apps)} акк) ===")
    started_apps = []

    for app in valid_apps:
        try:
            await app.start()
            me = await app.get_me()
            print(f"🟢 {me.first_name} онлайн!")
            started_apps.append(app)
        except Exception as e:
            print(f"❌ Ошибка старта {app.name}: {e}")

    if started_apps:
        print("\n🤖 Бот работает. Нажмите Ctrl+C для остановки.")

        # idle() держит соединение.
        # Если интернет пропадет, Pyrogram сам будет пытаться переподключиться.
        # Если он не сможет и выбросит ошибку -> скрипт упадет -> Systemd его поднимет.
        await idle()

        for app in started_apps:
            await app.stop()
    else:
        print("❌ Не удалось запустить ни одного клиента.")
        exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Остановка пользователем (Ctrl+C)")
    except Exception as e:
        print(f"\n🔥 CRITICAL ERROR: {e}")
        # Завершаем с кодом ошибки, чтобы Systemd перезапустил службу
        exit(1)