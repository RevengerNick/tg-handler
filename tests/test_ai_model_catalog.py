import importlib
import os
import unittest
from unittest.mock import patch


class AiModelCatalogTests(unittest.TestCase):
    def test_default_catalog_avoids_retired_models(self):
        import src.config as config

        model_ids = {item["id"] for item in config.AVAILABLE_MODELS.values()}
        self.assertIn("gemini-flash-latest", model_ids)
        self.assertIn("gemini-pro-latest", model_ids)
        self.assertIn("gemini-flash-lite-latest", model_ids)
        self.assertNotIn("gemini-2.0-flash", model_ids)
        self.assertEqual(
            config.AVAILABLE_MODELS["1"]["id"],
            "gemini-flash-lite-latest",
        )
        self.assertEqual(config.GEMINI_IMAGE_MODEL, "gemini-3.1-flash-image")
        self.assertEqual(
            config.GEMINI_TTS_FLASH_MODEL,
            "gemini-3.1-flash-tts-preview",
        )

    def test_model_alias_can_be_pinned_from_environment(self):
        import src.config as config

        with patch.dict(os.environ, {"GEMINI_FLASH_MODEL": "gemini-3.8-flash"}):
            reloaded = importlib.reload(config)
            self.assertEqual(reloaded.AVAILABLE_MODELS["2"]["id"], "gemini-3.8-flash")

        importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
