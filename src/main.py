import asyncio
import os
from pyrogram import Client, idle
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from config import API_ID, API_HASH, PHONES


# Функция интерактивного входа (оставили здесь, т.к. она нужна только при старте)
async def interactive_auth(app: Client):
    print(f"🔄 Check: {app.name}")
    try:
        await app.connect()
    except:
        return False
    try:
        await app.get_me(); await app.disconnect(); return True
    except:
        pass

    try:
        sent = await app.send_code(app.phone_number)
    except Exception as e:
        print(e); await app.disconnect(); return False

    while True:
        code = input(f"📩 Code {app.phone_number}: ").strip()
        try:
            await app.sign_in(app.phone_number, sent.phone_code_hash, code); break
        except SessionPasswordNeeded:
            pw = input("🔑 2FA Password: ").strip()
            try:
                await app.check_password(pw); break
            except PasswordHashInvalid:
                print("❌ Wrong.")
        except Exception as e:
            print(e); await app.disconnect(); return False
    await app.disconnect();
    return True


async def main():
    if not os.path.exists("sessions"): os.makedirs("sessions")

    # ВАЖНО: plugins=dict(root="handlers") подключает нашу папку handlers
    apps = [
        Client(
            name=f"sessions/{p.strip().replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=p.strip(),
            plugins=dict(root="handlers")
        ) for p in PHONES if p.strip()
    ]

    if not apps: print("❌ No phones in .env"); return

    print("\n--- AUTH ---")
    valid_apps = [app for app in apps if await interactive_auth(app)]
    if not valid_apps: print("❌ No valid sessions."); return

    print("\n--- START ---")
    started = []
    for app in valid_apps:
        try:
            await app.start()
            me = await app.get_me()
            print(f"🟢 Started: {me.first_name}")
            started.append(app)
        except Exception as e:
            print(f"❌ Fail {app.name}: {e}")

    if started:
        print("🤖 Bot Running. Ctrl+C to stop.")
        await idle()
        for app in started: await app.stop()


if __name__ == "__main__":
    asyncio.run(main())