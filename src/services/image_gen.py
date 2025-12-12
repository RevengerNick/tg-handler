import asyncio
import os
import time
import random
import aiohttp
from src.services.ai_core import get_ai_client, rotate_key_and_retry
from src.config import IMAGEN_MODEL
from google.genai import types


async def generate_imagen(prompt):
    """
    Генерация через Google Imagen 3.
    Использует ротацию ключей.
    """

    async def _worker():
        client = get_ai_client()
        if not client: return None, "No Client"

        # Конфиг для генерации
        config = types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",  # Можно менять на 16:9
            output_mime_type="image/jpeg"
        )

        try:
            response = await client.aio.models.generate_images(
                model=IMAGEN_MODEL,
                prompt=prompt,
                config=config
            )

            # Сохраняем результат
            if response.generated_images:
                image_data = response.generated_images[0].image.image_bytes
                filename = f"img_imagen_{int(time.time())}.jpg"

                with open(filename, "wb") as f:
                    f.write(image_data)
                return filename, None
            else:
                return None, "No images returned (Safety filter?)"

        except Exception as e:
            # Часто бывает ошибка 400 из-за Safety Filters (NSFW и т.д.)
            if "Safety" in str(e) or "400" in str(e):
                return None, f"Safety Filter Blocked: {e}"
            raise e  # Пробрасываем для ротации, если это ошибка сети/лимитов

    try:
        # Используем ротацию ключей, так как лимиты на Imagen строгие
        return await rotate_key_and_retry(_worker)
    except Exception as e:
        return None, str(e)


async def generate_flux(prompt):
    """
    Генерация через Pollinations (Flux).
    Полностью бесплатно, без ключей.
    """
    # Добавляем seed для вариативности
    seed = random.randint(0, 100000)
    # URL encoded prompt
    import urllib.parse
    safe_prompt = urllib.parse.quote(prompt)

    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&seed={seed}&model=flux"

    filename = f"img_flux_{int(time.time())}.jpg"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(filename, "wb") as f:
                        f.write(data)
                    return filename, None
                else:
                    return None, f"HTTP Error: {resp.status}"
    except Exception as e:
        return None, str(e)