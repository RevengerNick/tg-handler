import json
import asyncio
import os
from google.genai import types
from src.services.ai_core import get_ai_client, rotate_key_and_retry


async def transcribe_via_gemini(file_path):
    """
    Транскрибация аудио/видео через Gemini File API.
    Использует ротацию ключей для стабильности.
    """

    # Внутренняя функция-воркер, которую мы будем перезапускать при смене ключа
    async def _worker():
        client = get_ai_client()
        if not client: return {"error": "No Gemini Keys available"}

        # 1. Загрузка файла (Upload)
        file_ref = await client.aio.files.upload(file=file_path)

        # 2. Ожидание обработки (Processing)
        # Ждем максимум 60 сек, чтобы не зависнуть навечно
        for _ in range(30):
            if file_ref.state.name == "ACTIVE":
                break
            if file_ref.state.name == "FAILED":
                return {"error": "Google File Processing Failed"}

            await asyncio.sleep(2)
            file_ref = await client.aio.files.get(name=file_ref.name)

        if file_ref.state.name != "ACTIVE":
            return {"error": "File processing timeout"}

        # 3. Промпт и Схема
        prompt = """
        Analyze this audio/video file. 
        Generate a detailed transcription in Russian.
        Requirements:
        - Identify speakers (Speaker 1, Speaker 2...)
        - Provide timestamps (MM:SS)
        - Detect emotions for each segment
        - Provide a summary
        """

        schema = {
            "type": "OBJECT",
            "properties": {
                "summary": {"type": "STRING"},
                "segments": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "time": {"type": "STRING"},
                            "speaker": {"type": "STRING"},
                            "text": {"type": "STRING"},
                            "emotion": {"type": "STRING"}
                        }
                    }
                }
            },
            "required": ["summary", "segments"]
        }

        # 4. Генерация
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_uri(file_uri=file_ref.uri, mime_type=file_ref.mime_type),
                        types.Part.from_text(text=prompt)
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema
            )
        )

        # 5. Удаление файла из облака (Cleanup)
        # Делаем это в finally блоке внутри worker было бы сложно,
        # поэтому делаем сразу после генерации
        try:
            await client.aio.files.delete(name=file_ref.name)
        except:
            pass

        # 6. Парсинг ответа
        try:
            return json.loads(response.text)
        except:
            return response.parsed

    # Запускаем через механизм ротации
    try:
        return await rotate_key_and_retry(_worker)
    except Exception as e:
        return {"error": str(e)}


async def generate_freetts(text):
    # (Этот код у тебя уже есть, оставляем без изменений, он не зависит от Gemini)
    # ... скопируй функцию generate_freetts из прошлых ответов ...
    import aiohttp
    import time

    url_synth = "https://freetts.ru/api/synthesis"
    url_history = "https://freetts.ru/api/history"
    current_uid = "710a7bacbccdad2f8207f2b3a7f921d0"
    voice_id = "NG6FIoMMe4L1"

    headers = {
        "Host": "freetts.ru",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/145.0",
        "Accept": "*/*",
        "Referer": "https://freetts.ru/",
        "Origin": "https://freetts.ru",
        "Connection": "keep-alive"
    }
    cookies = {"uid": current_uid}

    try:
        async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
            payload = {"text": text, "voiceid": voice_id, "ext": "mp3"}
            async with session.post(url_synth, json=payload) as resp:
                if resp.status != 200: return None, f"HTTP {resp.status}"

            for i in range(15):
                await asyncio.sleep(2)
                async with session.get(url_history) as hist_resp:
                    if hist_resp.status != 200: continue
                    hist_data = await hist_resp.json()

                    if hist_data.get("status") == "success" and isinstance(hist_data.get("data"), list):
                        for task in hist_data["data"][:5]:
                            if text[:10] in task.get("text", ""):
                                if task["status"] == "done":
                                    async with session.get(task["url"]) as audio_resp:
                                        if audio_resp.status == 200:
                                            content = await audio_resp.read()
                                            filename = f"freetts_{int(time.time())}.mp3"
                                            with open(filename, "wb") as f: f.write(content)
                                            return filename, None
                                elif task["status"] == "error":
                                    return None, "Server Error"
            return None, "Timeout"
    except Exception as e:
        return None, str(e)