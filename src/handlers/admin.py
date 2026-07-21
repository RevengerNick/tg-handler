import time
import json
from pyrogram import Client, filters
from src.services import edit_or_reply, get_sys_info, update_help_page
from src.state import SETTINGS, save_settings, ASYNC_CHAT_SESSIONS
from src.config import AVAILABLE_MODELS, AVAILABLE_VOICES, AVAILABLE_TTS_MODELS, HELP_DICT
from src.access_filters import AccessFilter
from src.services.files import output_path


@Client.on_message(filters.command(["help", "помощь"], prefixes=".") & AccessFilter)
async def help_cmd(client, message):
    try:
        status = await edit_or_reply(message, "🤖 Актуализирую мануал...")

        # Убрали H1 (#), так как он есть в названии страницы
        md_text = ""
        md_text += "Полный список команд и возможностей вашего бота.\n\n"

        for category, commands in HELP_DICT.items():
            md_text += f"## {category}\n"
            for cmd, desc in commands.items():
                md_text += f"**{cmd}** — {desc}\n"
            md_text += "\n"

        md_text +=f"**Актуально на:** {time.strftime('%Y-%m-%d %H:%M')}\n"
        md_text += "Полный список команд и возможностей вашего бота.\n"
        md_text += "---\n*Generated automatically by Revenger Userbot*"

        link = await update_help_page("Revenger Bot Commands", md_text)

        await status.edit(
            f"🤖 **Справка по командам:**\n\n"
            f"👉 **[ЧИТАТЬ МАНУАЛ]({link})**",
            disable_web_page_preview=False
        )

    except Exception as e:
        await edit_or_reply(message, f"❌ Ошибка генерации справки: {e}")


@Client.on_message(filters.me & filters.command(["model", "модель"], prefixes="."))
async def model_handler(client, message):
    args = message.text.split()
    curr = SETTINGS.get("model_key", "1")
    if len(args) < 2:
        t = "🧠 **Models:**\n\n"
        for k, v in AVAILABLE_MODELS.items():
            mark = "✅" if k == curr else ""
            icon = "🔎" if v["search"] else ""
            t += f"`{k}` — {v['name']} {icon} {mark}\n"
        return await message.edit(t + "\nEx: `.model 2`")

    if args[1] in AVAILABLE_MODELS:
        SETTINGS["model_key"] = args[1];
        save_settings();
        ASYNC_CHAT_SESSIONS.clear()
        await message.edit(f"✅ Set: {AVAILABLE_MODELS[args[1]]['name']}")
    else:
        await message.edit("❌ Invalid model number.")


@Client.on_message(filters.me & filters.command(["voice", "голос"], prefixes="."))
async def voice_handler(client, message):
    args = message.text.split()
    curr = SETTINGS.get("voice_key", "1")
    if len(args) < 2:
        # Формируем списки
        male_list = []
        female_list = []
        for k, v in AVAILABLE_VOICES.items():
            mark = "✅" if k == curr else ""
            line = f"`{k}` — **{v['name']}** ({v['desc']}) {mark}"
            if v["gender"] == "M":
                male_list.append(line)
            else:
                female_list.append(line)

        text = "🗣 **Голоса (Gemini):**\n\n"
        text += "👨 **МУЖСКИЕ:**\n" + "\n".join(male_list) + "\n\n"
        text += "👩 **ЖЕНСКИЕ:**\n" + "\n".join(female_list)
        text += "\n\nВыбор: `.voice 5`"
        return await message.edit(text)

    if args[1] in AVAILABLE_VOICES:
        SETTINGS["voice_key"] = args[1];
        save_settings()
        info = AVAILABLE_VOICES[args[1]]
        await message.edit(f"✅ Голос установлен: `{info['name']}`\n({info['desc']})")
    else:
        await message.edit("❌ Неверный номер.")


@Client.on_message(filters.me & filters.command(["ttsmodel", "модельозвучки"], prefixes="."))
async def tts_model_handler(client, message):
    args = message.text.split()
    curr = SETTINGS.get("tts_model_key", "1")
    if len(args) < 2:
        text = "🎛 **Модель озвучки:**\n\n"
        for k, v in AVAILABLE_TTS_MODELS.items():
            mark = "✅" if k == curr else ""
            text += f"`{k}` — {v} {mark}\n"
        return await message.edit(text)

    if args[1] in AVAILABLE_TTS_MODELS:
        SETTINGS["tts_model_key"] = args[1];
        save_settings()
        await message.edit(f"✅ Модель TTS: `{AVAILABLE_TTS_MODELS[args[1]]}`")
    else:
        await message.edit("❌ Неверно.")


@Client.on_message(filters.me & filters.command(["bl", "block", "чс"], prefixes="."))
async def block_handler(client, message):
    try:
        reply = message.reply_to_message
        target_id = None
        name = "User"

        if reply and reply.from_user:
            target_id = reply.from_user.id
            name = reply.from_user.first_name
        elif len(message.command) > 1 and message.command[1].isdigit():
            target_id = int(message.command[1])
            name = str(target_id)

        if target_id:
            if target_id not in SETTINGS["blacklist"]:
                SETTINGS["blacklist"].append(target_id);
                save_settings()
                await message.edit(f"🚫 {name} (`{target_id}`) добавлен в ЧС.")
            else:
                await message.edit(f"🤷‍♂️ {name} уже в ЧС.")
        else:
            await message.edit("❌ Ответьте на сообщение или укажите ID.")
    except Exception as e:
        await message.edit(f"Err: {e}")


@Client.on_message(filters.me & filters.command(["unbl", "unblock", "разблок"], prefixes="."))
async def unblock_handler(client, message):
    try:
        reply = message.reply_to_message
        target_id = None
        if reply and reply.from_user:
            target_id = reply.from_user.id
        elif len(message.command) > 1 and message.command[1].isdigit():
            target_id = int(message.command[1])

        if target_id and target_id in SETTINGS["blacklist"]:
            SETTINGS["blacklist"].remove(target_id);
            save_settings()
            await message.edit(f"✅ `{target_id}` удален из ЧС.")
        else:
            await message.edit("🤷‍♂️ Не найден в ЧС.")
    except Exception as e:
        await message.edit(f"Err: {e}")


@Client.on_message(filters.me & filters.command(["sysglobal", "сисглоб"], prefixes="."))
async def sysg_handler(client, message):
    if len(message.text.split()) == 1:
        return await message.edit(f"🌐 Global:\n`{SETTINGS.get('sys_global', '-')}`")
    SETTINGS["sys_global"] = message.text.split(maxsplit=1)[1];
    save_settings();
    ASYNC_CHAT_SESSIONS.clear()
    await message.edit(f"🌐 Updated:\n`{SETTINGS['sys_global']}`")


@Client.on_message(filters.me & filters.command(["syschat", "сисчат"], prefixes="."))
async def sysc_handler(client, message):
    cid = str(message.chat.id)
    if len(message.text.split()) == 1:
        return await message.edit(f"💬 Chat:\n`{SETTINGS.get('sys_chats', {}).get(cid, '-')}`")

    instr = message.text.split(maxsplit=1)[1]
    if "sys_chats" not in SETTINGS: SETTINGS["sys_chats"] = {}

    if instr == "-":
        if cid in SETTINGS["sys_chats"]: del SETTINGS["sys_chats"][cid]
        msg = "🗑 Removed."
    else:
        SETTINGS["sys_chats"][cid] = instr
        msg = f"💬 Set:\n`{instr}`"

    save_settings()
    if message.chat.id in ASYNC_CHAT_SESSIONS: del ASYNC_CHAT_SESSIONS[message.chat.id]
    await message.edit(msg)


@Client.on_message(filters.me & filters.command(["reset", "сброс"], prefixes="."))
async def reset_handler(client, message):
    chat_id = message.chat.id
    if chat_id in ASYNC_CHAT_SESSIONS:
        try:
            chat = ASYNC_CHAT_SESSIONS[chat_id]
            hist = await chat.get_history()
            msgs = [{'role': m.role, 'txt': m.parts[0].text if m.parts else ""} for m in hist]
            fname = output_path("history", f"history_{chat_id}.json")
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(msgs, f, ensure_ascii=False)
            del ASYNC_CHAT_SESSIONS[chat_id]
            await message.edit(f"🧹 Done. Backup: `{fname}`")
        except:
            del ASYNC_CHAT_SESSIONS[chat_id]
            await message.edit("🧹 Done")
    else:
        await message.edit("Already empty")


@Client.on_message(filters.me & filters.command(["sys", "сис"], prefixes="."))
async def sys_handler(client, message):
    await message.edit(await get_sys_info())
