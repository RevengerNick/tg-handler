import asyncio
import os
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from src.config import API_ID, API_HASH, PHONES
# Импортируем нашу новую функцию
from src.services.auth_qr import login_via_qr


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
    print("-----------------------------------")
    print("Выберите метод входа:")
    print("[Enter] - QR Код (Рекомендуется, надежно)")
    print("[2]     - Номер телефона (СМС/Код)")
    choice = input("Ваш выбор: ").strip()

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
        # Вызываем функцию из сервиса
        success = await login_via_qr(app)

        # Важно: login_via_qr оставляет соединение открытым или закрывает?
        # В нашей реализации мы не делаем disconnect внутри login_via_qr в случае успеха,
        # чтобы main.py мог корректно завершить этап.

        if app.is_connected:
            await app.disconnect()

        return success


async def main():
    if not os.path.exists("sessions"):
        os.makedirs("sessions")

    # Инициализация клиентов
    apps = [
        Client(
            name=f"sessions/{p.strip().replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=p.strip(),
            plugins=dict(root="src.handlers")
        ) for p in PHONES if p.strip()
    ]

    if not apps:
        print("❌ Номера телефонов не найдены в .env")
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
        await idle()

        for app in started_apps:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())