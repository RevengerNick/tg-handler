import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import web_server


class WebArticleTest(unittest.TestCase):
    def test_saved_article_renders_with_current_starlette_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "database.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "CREATE TABLE articles (id TEXT PRIMARY KEY, title TEXT, content TEXT, date TEXT)"
                )
                connection.execute(
                    "INSERT INTO articles VALUES (?, ?, ?, ?)",
                    ("article-1", "Test article", "Hello **world**", "2026-09-13"),
                )

            with patch.object(web_server, "DB_PATH", str(database_path)):
                with TestClient(web_server.app) as client:
                    response = client.get("/view/article-1")

        self.assertEqual(200, response.status_code)
        self.assertEqual("article.html", response.template.name)
        self.assertEqual("Test article", response.context["title"])
        self.assertIn("Hello <strong>world</strong>", response.text)


if __name__ == "__main__":
    unittest.main()
