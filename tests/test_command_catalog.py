import ast
import re
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLERS_DIR = ROOT / "src" / "handlers"
CONFIG_FILE = ROOT / "src" / "config.py"


def command_groups():
    groups = []
    for path in HANDLERS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "command"):
                continue
            if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)):
                continue
            aliases = [
                item.value
                for item in node.args[0].elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if aliases:
                groups.append((path.name, node.lineno, aliases))
    return groups


def documented_commands():
    tree = ast.parse(CONFIG_FILE.read_text(encoding="utf-8"), filename=str(CONFIG_FILE))
    help_dict = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "HELP_DICT"
            for target in node.targets
        ):
            help_dict = ast.literal_eval(node.value)
            break
    if help_dict is None:
        raise AssertionError("HELP_DICT not found")
    text = "\n".join(command for section in help_dict.values() for command in section)
    return set(re.findall(r"\.([\wа-яё]+)", text, flags=re.IGNORECASE))


class CommandCatalogTest(unittest.TestCase):
    def test_no_alias_is_registered_by_multiple_handlers(self):
        owners = defaultdict(list)
        for filename, line, aliases in command_groups():
            for alias in aliases:
                owners[alias.casefold()].append(f"{filename}:{line}")
        duplicates = {alias: places for alias, places in owners.items() if len(places) > 1}
        self.assertEqual({}, duplicates, f"Conflicting command aliases: {duplicates}")

    def test_every_handler_has_a_command_in_help(self):
        documented = documented_commands()
        missing = []
        for filename, line, aliases in command_groups():
            if not any(alias.casefold() in documented for alias in aliases):
                missing.append(f"{filename}:{line} ({', '.join(aliases)})")
        self.assertEqual([], missing, f"Commands missing from HELP_DICT: {missing}")


if __name__ == "__main__":
    unittest.main()
