import base64
import random
import aiohttp
from src.services.ai_core import get_ai_client, rotate_key_and_retry
from src.config import GEMINI_IMAGE_MODEL
from src.services.files import output_path


async def generate_imagen(prompt):
    """
    Генерация через актуальную Gemini Flash Image (Nano Banana).
    Использует ротацию ключей.
    """

    async def _worker():
        client = get_ai_client()
        if not client: return None, "No Client"

        try:
            response = await client.aio.interactions.create(
                model=GEMINI_IMAGE_MODEL,
                input=prompt,
                response_format={
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "aspect_ratio": "1:1",
                    "image_size": "1K",
                },
            )

            image = response.output_image
            if image and image.data:
                image_data = base64.b64decode(image.data)
                filename = output_path("images", "gemini_image.jpg")

                with open(filename, "wb") as f:
                    f.write(image_data)
                return filename, None
            return None, "No images returned (Safety filter?)"

        except Exception as e:
            # Часто бывает ошибка 400 из-за Safety Filters (NSFW и т.д.)
            if "Safety" in str(e) or "400" in str(e):
                return None, f"Safety Filter Blocked: {e}"
            raise e  # Пробрасываем для ротации, если это ошибка сети/лимитов

    try:
        # Лимиты медиа-моделей строже, поэтому ротация ключей остаётся.
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

    filename = output_path("images", "flux.jpg")

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
