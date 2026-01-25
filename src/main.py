import asyncio
import os
import sys
from threading import Thread
import uvicorn
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import API_ID, API_HASH, PHONES
from src.services.auth_qr import login_via_qr
from src.web_server import app as web_app


def run_web_server():
    """Запуск сервера на 0.0.0.0 для доступа из Docker-сети Cloudflare"""
    uvicorn.run(web_app, host="0.0.0.0", port=8112, log_level="error")


async def interactive_auth(app: Client):
    """
    Интерактивная проверка авторизации (QR или СМС).
    """
    session_path = f"{app.workdir}/{app.name}.session"

    print(f"\n🔄 Проверка сессии для: {app.name}")
    print(f"📂 Путь к сессии: {session_path}")

    # Проверяем существует ли файл сессии
    if os.path.exists(session_path):
        print(f"✅ Файл сессии найден")
        try:
            await app.connect()
            me = await app.get_me()
            print(f"✅ Сессия активна: {me.first_name}")
            await app.disconnect()
            return True
        except Exception as e:
            print(f"⚠️ Сессия невалидна ({e}), требуется повторный вход")
            try:
                os.remove(session_path)
                print("🗑 Битый файл сессии удален")
            except:
                pass
    else:
        print(f"❌ Файл сессии не найден")

    # Нужен новый вход
    print("👤 Требуется авторизация.")
    print("-----------------------------------")
    print("Выберите метод входа:")
    print("[Enter] - QR Код (Рекомендуется, надежно)")
    print("[2]     - Номер телефона (СМС/Код)")

    try:
        choice = input("Ваш выбор: ").strip()
    except EOFError:
        print("❌ Ошибка: Нет доступа к консоли (видимо, запуск через Systemd).")
        print("   Запустите скрипт вручную один раз для авторизации: python -m src.main")
        return False

    if choice == "2":
        # Вход по СМС
        try:
            if not app.is_connected:
                await app.connect()

            print(f"📤 Отправляю код на {app.phone_number}...")
            sent = await app.send_code(app.phone_number)
        except Exception as e:
            print(f"❌ Ошибка отправки кода: {e}")
            if app.is_connected:
                await app.disconnect()
            return False

        while True:
            code = input(f"📩 Введите код: ").strip()
            try:
                await app.sign_in(app.phone_number, sent.phone_code_hash, code)
                print("✅ Вход по СМС успешен!")
                break
            except SessionPasswordNeeded:
                pw = input("🔑 2FA Пароль: ").strip()
                try:
                    await app.check_password(pw)
                    print("✅ 2FA пройдена!")
                    break
                except PasswordHashInvalid:
                    print("❌ Неверный пароль. Попробуйте снова.")
            except Exception as e:
                print(f"❌ Ошибка входа: {e}")
                if app.is_connected:
                    await app.disconnect()
                return False

        # Отключаемся после успешного входа
        if app.is_connected:
            await app.disconnect()
        return True
    else:
        # Вход по QR
        success = await login_via_qr(app)
        # login_via_qr уже отключает клиент
        return success


async def main():
    if not os.path.exists("sessions"):
        os.makedirs("sessions")

    Thread(target=run_web_server, daemon=True).start()
    print("🌐 Локальный веб-сервер запущен на порту 8111")

    apps = [
        Client(
            name=f"sessions/{p.strip().replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=p.strip(),
            plugins=dict(root="src.handlers"),
            ipv6=False,
            workdir="."
        ) for p in PHONES if p.strip()
    ]

    if not apps:
        print("❌ Номера телефонов не найдены в .env")
        sys.exit(1)

    print("\n=== ЭТАП 1: АВТОРИЗАЦИЯ ===")
    valid_apps = []
    for app in apps:
        if await interactive_auth(app):
            valid_apps.append(app)
            print(f"✅ {app.name} готов к запуску\n")
        else:
            print(f"⚠️ Скипаем {app.name} (не удалось войти)\n")

    if not valid_apps:
        print("❌ Нет активных сессий. Бот не может быть запущен.")
        sys.exit(1)

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
        await idle()
        for app in started_apps:
            await app.stop()
    else:
        print("❌ Ни один клиент не запустился.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Остановка пользователем")
    except Exception as e:
        print(f"\n🔥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
        sys.exit(1)