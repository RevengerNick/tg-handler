import asyncio
import os
import re
import time
import struct
from google.genai import types
from src.services.ai_core import get_ai_client, rotate_key_and_retry
from src.config import AVAILABLE_VOICES, AVAILABLE_TTS_MODELS, VOICE_NAMES_LIST
from src.state import SETTINGS


def parse_audio_mime_type(mime_type: str):
    """Парсит параметры аудио (частоту и битность) из MIME-типа."""
    bits = 16
    rate = 24000
    for param in mime_type.split(";"):
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except:
                pass
        elif param.startswith("audio/L"):
            try:
                bits = int(param.split("L", 1)[1])
            except:
                pass
    return {"bits": bits, "rate": rate}


def convert_to_wav(data: bytes, mime_type: str) -> bytes:
    """Добавляет WAV заголовок к сырым PCM данным."""
    p = parse_audio_mime_type(mime_type)
    data_size = len(data)

    # WAV Header (44 bytes)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,
        1,  # AudioFormat (1=PCM)
        1,  # NumChannels (Gemini TTS is mono)
        p['rate'],
        p['rate'] * p['bits'] // 8,  # ByteRate
        p['bits'] // 8,  # BlockAlign
        p['bits'],  # BitsPerSample
        b'data',
        data_size
    )
    return header + data


async def convert_wav_to_ogg(wav_path):
    """
    Конвертирует WAV в OGG Opus (формат голосовых Telegram).
    """
    ogg_path = wav_path.replace(".wav", ".ogg")

    cmd = [
        "ffmpeg", "-i", wav_path,
        "-c:a", "libopus", "-b:a", "32k", "-vn", "-y",
        ogg_path
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.communicate()

        return ogg_path if os.path.exists(ogg_path) else None
    except Exception as e:
        print(f"FFmpeg Error: {e}")
        return None


async def generate_gemini_tts(text):
    """
    Одиночная генерация голоса (Single Speaker).
    """

    async def _worker():
        client = get_ai_client()
        if not client: raise Exception("No Gemini Client available")

        t_key = SETTINGS.get("tts_model_key", "1")
        model_id = AVAILABLE_TTS_MODELS.get(t_key, AVAILABLE_TTS_MODELS["1"])

        v_key = SETTINGS.get("voice_key", "1")
        v_data = AVAILABLE_VOICES.get(v_key, AVAILABLE_VOICES["1"])
        v_name = v_data["name"]

        config = types.GenerateContentConfig(
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=v_name)
                )
            )
        )

        accumulated_data = bytearray()
        mime_type = "audio/wav"

        async for chunk in await client.aio.models.generate_content_stream(
                model=model_id,
                contents=text,
                config=config
        ):
            # ВАЖНОЕ ИСПРАВЛЕНИЕ: Проверяем content перед обращением к parts
            if (chunk.candidates and
                    chunk.candidates[0].content and
                    chunk.candidates[0].content.parts):

                part = chunk.candidates[0].content.parts[0]
                if part.inline_data:
                    accumulated_data.extend(part.inline_data.data)
                    mime_type = part.inline_data.mime_type

        if not accumulated_data:
            raise Exception("Gemini returned empty audio data")

        return accumulated_data, mime_type

    try:
        result = await rotate_key_and_retry(_worker)

        if result and isinstance(result, tuple):
            acc_data, mime = result
            wav_data = convert_to_wav(bytes(acc_data), mime)

            filename = f"gemini_voice_{int(time.time())}.wav"
            with open(filename, "wb") as f:
                f.write(wav_data)
            return filename

        return None
    except Exception as e:
        print(f"TTS Generation Error: {e}")
        return None


async def generate_multispeaker_tts(script_text, custom_cast=None):
    """
    Мультиспикерная генерация (Диалоги).
    """

    async def _worker():
        client = get_ai_client()
        if not client: raise Exception("No Gemini Client available")

        # 1. Поиск спикеров
        import re
        speaker_pattern = re.compile(r"^([A-Za-zА-Яа-я0-9_ ]+):", re.MULTILINE)
        found_speakers = sorted(list(set(speaker_pattern.findall(script_text))))

        actual_script = script_text
        if not found_speakers:
            found_speakers = ["Narrator"]
            actual_script = f"Narrator: {script_text}"

        # 2. Кастинг
        speaker_configs = []
        for i, speaker_name in enumerate(found_speakers):
            if custom_cast and speaker_name in custom_cast:
                voice_name = custom_cast[speaker_name]
            else:
                voice_name = VOICE_NAMES_LIST[i % len(VOICE_NAMES_LIST)]

            speaker_configs.append(
                types.SpeakerVoiceConfig(
                    speaker=speaker_name,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                    )
                )
            )

        # 3. Конфиг
        model_id = "gemini-2.5-flash-preview-tts"

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=speaker_configs
                )
            )
        )

        accumulated_data = bytearray()
        mime_type = "audio/wav"

        full_prompt = f"TTS the following conversation:\n{actual_script}"

        async for chunk in await client.aio.models.generate_content_stream(
                model=model_id,
                contents=full_prompt,
                config=config
        ):
            # ВАЖНОЕ ИСПРАВЛЕНИЕ: Проверяем content
            if (chunk.candidates and
                    chunk.candidates[0].content and
                    chunk.candidates[0].content.parts):

                part = chunk.candidates[0].content.parts[0]
                if part.inline_data:
                    accumulated_data.extend(part.inline_data.data)
                    mime_type = part.inline_data.mime_type

        if not accumulated_data:
            raise Exception("Gemini returned empty multispeaker data")

        return accumulated_data, mime_type

    try:
        result = await rotate_key_and_retry(_worker)

        if result and isinstance(result, tuple):
            acc_data, mime = result
            wav_data = convert_to_wav(bytes(acc_data), mime)

            filename = f"dialog_{int(time.time())}.wav"
            with open(filename, "wb") as f:
                f.write(wav_data)
            return filename

        return None
    except Exception as e:
        print(f"MultiSpeaker Error: {e}")
        return None