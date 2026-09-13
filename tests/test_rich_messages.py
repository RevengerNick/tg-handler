import unittest

from src.services.rich_messages import RICH_MESSAGE_LIMIT, markdown_to_rich_blocks


class RichMessageTests(unittest.TestCase):
    def test_markdown_tables_lists_and_code_become_native_blocks(self):
        blocks = markdown_to_rich_blocks(
            "# Report\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('ok')\n```"
        )
        names = [type(block).__name__ for block in blocks]
        self.assertIn("PageBlockTitle", names)
        self.assertIn("PageBlockList", names)
        self.assertIn("PageBlockTable", names)
        self.assertIn("PageBlockPreformatted", names)
        for block in blocks:
            block.write()

    def test_documented_rich_message_limit(self):
        self.assertEqual(32_768, RICH_MESSAGE_LIMIT)


if __name__ == "__main__":
    unittest.main()
