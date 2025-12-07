import json
import asyncio
import os
from google.genai import types
from src.services.ai_core import ai_client


async def transcribe_via_gemini(file_path):
    """
    Транскрибация аудио/видео файла через Gemini File API.
    """
    if not ai_client: return {"error": "No Gemini Key"}

    try:
        # 1. Upload
        file_ref = await ai_client.aio.files.upload(file=file_path)

        # 2. Wait for processing
        while file_ref.state.name == "PROCESSING":
            await asyncio.sleep(2)
            file_ref = await ai_client.aio.files.get(name=file_ref.name)

        if file_ref.state.name == "FAILED":
            return {"error": "File processing failed"}

        # 3. Prompt & Schema
        prompt = """
        Process the audio/video and generate a detailed transcription.
        Output MUST be in Russian.
        Identify speakers, timestamps, and emotions.
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

        # 4. Generate
        response = await ai_client.aio.models.generate_content(
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

        # 5. Cleanup
        await ai_client.aio.files.delete(name=file_ref.name)

        # 6. Parse
        try:
            return json.loads(response.text)
        except:
            return response.parsed

    except Exception as e:
        return {"error": str(e)}