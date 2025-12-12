import asyncio
import base64
import qrcode
from pyrogram.raw import functions, types
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid


async def login_via_qr(app):
    """
    Выполняет вход в аккаунт через QR-код.
    Возвращает True, если вход успешен.
    """
    print("🔄 Генерация QR-кода... Пожалуйста, подождите.")

    try:
        if not app.is_connected:
            await app.connect()

        while True:
            # 1. Запрашиваем токен экспорта у Telegram
            # Используем app.invoke (низкоуровневый запрос)
            login_token = await app.invoke(
                functions.auth.ExportLoginToken(
                    api_id=app.api_id,
                    api_hash=app.api_hash,
                    except_ids=[]
                )
            )

            # 2. Если токен пришел и требует сканирования
            if isinstance(login_token, types.auth.LoginToken):
                # Кодируем токен для ссылки
                b64_token = base64.urlsafe_b64encode(login_token.token).decode().rstrip("=")
                url = f"tg://login?token={b64_token}"

                # Рисуем QR в терминале
                qr = qrcode.QRCode(border=2)
                qr.add_data(url)
                # invert=True часто лучше видно в темных терминалах, но можно убрать
                try:
                    qr.print_ascii(invert=True)
                except:
                    qr.print_ascii()

                print("\n📱 Откройте Telegram на телефоне:")
                print("   Настройки -> Устройства -> Подключить устройство -> Сканировать QR")
                print("⏳ Ожидание сканирования (обновление через 5 сек)...")

                # Ждем, пока пользователь отсканирует.
                # API само держит соединение, но нам нужно периодически проверять статус
                try:
                    await asyncio.sleep(5)
                    continue
                except Exception:
                    pass

            # 3. УСПЕХ (LoginTokenSuccess)
            elif isinstance(login_token, types.auth.LoginTokenSuccess):
                user = login_token.authorization.user
                print(f"\n✅ QR успешно отсканирован! Вы вошли как: {user.first_name}")
                return True

            # 4. Миграция DC (редко, но бывает)
            elif isinstance(login_token, types.auth.LoginTokenMigrateTo):
                print(f"🔄 Переключение на DC {login_token.dc_id}...")
                await app.session.stop()
                app.session.dc_id = login_token.dc_id
                await app.session.start()
                continue

    except SessionPasswordNeeded:
        # Если стоит облачный пароль (2FA)
        print("\n🔐 Требуется облачный пароль (2FA).")
        while True:
            pw = input("🔑 Введите пароль: ").strip()
            try:
                await app.check_password(pw)
                print("✅ Пароль принят!")
                return True
            except PasswordHashInvalid:
                print("❌ Неверный пароль.")
            except Exception as e:
                print(f"❌ Ошибка 2FA: {e}")
                return False

    except Exception as e:
        print(f"\n❌ Ошибка QR авторизации: {e}")
        return False