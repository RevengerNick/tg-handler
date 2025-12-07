import asyncio
import os
import re
import time
import struct
from google.genai import types
from src.services.ai_core import ai_client
from src.config import AVAILABLE_VOICES, AVAILABLE_TTS_MODELS, VOICE_NAMES_LIST
from src.state import SETTINGS


def parse_audio_mime_type(mime_type: str):
    """Парсит параметры аудио из MIME"""
    bits = 16
    rate = 24000
    for param in mime_type.split(";"):
        if "rate=" in param:
            try:
                rate = int(param.split("=")[1])
            except:
                pass
        if "audio/L" in param:
            try:
                bits = int(param.split("L")[1])
            except:
                pass
    return {"bits": bits, "rate": rate}


def convert_to_wav(data, mime):
    """Добавляет WAV заголовок"""
    p = parse_audio_mime_type(mime)
    data_size = len(data)
    # WAV Header
    head = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE', b'fmt ', 16, 1, 1,
        p['rate'], p['rate'] * p['bits'] // 8, p['bits'] // 8, p['bits'],
        b'data', data_size
    )
    return head + data


async def convert_wav_to_ogg(wav_path):
    """Конвертирует WAV -> OGG Opus через ffmpeg"""
    ogg_path = wav_path.replace(".wav", ".ogg")
    cmd = [
        "ffmpeg", "-i", wav_path,
        "-c:a", "libopus", "-b:a", "32k", "-vn", "-y",
        ogg_path
    ]
    try:
        p = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await p.communicate()
        return ogg_path if os.path.exists(ogg_path) else None
    except:
        return None


async def generate_gemini_tts(text):
    """Одиночная генерация голоса"""
    if not ai_client: return None

    t_key = SETTINGS.get("tts_model_key", "1")
    model = AVAILABLE_TTS_MODELS.get(t_key, AVAILABLE_TTS_MODELS["1"])

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

    accumulated = bytearray()
    mime = "audio/wav"
    try:
        async for chunk in await ai_client.aio.models.generate_content_stream(
                model=model, contents=text, config=config
        ):
            if chunk.candidates and chunk.candidates[0].content.parts:
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data:
                    accumulated.extend(part.inline_data.data)
                    mime = part.inline_data.mime_type

        if not accumulated: return None

        wav_data = convert_to_wav(bytes(accumulated), mime)
        filename = f"gemini_voice_{int(time.time())}.wav"
        with open(filename, "wb") as f:
            f.write(wav_data)
        return filename
    except Exception as e:
        print(f"TTS Err: {e}")
        return None


async def generate_multispeaker_tts(script_text, custom_cast=None):
    """Мультиспикерная генерация (Диалоги)"""
    if not ai_client: return None

    # Поиск спикеров (Regex)
    speaker_pattern = re.compile(r"^([A-Za-zА-Яа-я0-9_ ]+):", re.MULTILINE)
    found_speakers = sorted(list(set(speaker_pattern.findall(script_text))))

    if not found_speakers:
        found_speakers = ["Narrator"]
        script_text = f"Narrator: {script_text}"

    # Кастинг ролей
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

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=speaker_configs
            )
        )
    )

    # Генерация (используем Flash Preview для мультиспикера)
    model_id = "gemini-2.5-flash-preview-tts"
    accumulated = bytearray()
    mime = "audio/wav"

    try:
        async for chunk in await ai_client.aio.models.generate_content_stream(
                model=model_id, contents=script_text, config=config
        ):
            if chunk.candidates and chunk.candidates[0].content.parts:
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data:
                    accumulated.extend(part.inline_data.data)
                    mime = part.inline_data.mime_type

        if not accumulated: return None

        wav_data = convert_to_wav(bytes(accumulated), mime)
        filename = f"dialog_{int(time.time())}.wav"
        with open(filename, "wb") as f:
            f.write(wav_data)
        return filename
    except Exception as e:
        print(f"MultiSpeaker Err: {e}")
        return None