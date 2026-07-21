"""Безопасные пути для создаваемых ботом файлов."""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from src.config import KEEP_GENERATED_FILES, OUTPUT_DIR, TEMP_DIR

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_component(value: str, fallback: str) -> str:
    value = _INVALID_FILENAME_CHARS.sub("_", value).strip(" .")
    return value[:120] or fallback


def output_directory(category: str) -> str:
    """Возвращает каталог постоянных результатов одной команды."""
    directory = Path(OUTPUT_DIR, _safe_component(category, "other"))
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def output_path(category: str, filename: str) -> str:
    """Создаёт уникальный путь результата, не зависящий от текущего cwd."""
    source = Path(filename)
    stem = _safe_component(source.stem, "file")
    suffix = _INVALID_FILENAME_CHARS.sub("", source.suffix)[:20]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:8]
    return str(Path(output_directory(category), f"{stem}_{stamp}_{unique}{suffix}"))


def temporary_directory(category: str) -> str:
    """Создаёт изолированный временный каталог для одной операции."""
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    prefix = f"{_safe_component(category, 'job')}-"
    return tempfile.mkdtemp(prefix=prefix, dir=TEMP_DIR)


def temporary_path(category: str, filename: str) -> str:
    directory = temporary_directory(category)
    return str(Path(directory, _safe_component(Path(filename).name, "input.bin")))


def remove_generated_file(path: str | os.PathLike[str]) -> None:
    """Удаляет результат только если его архивирование отключено."""
    if KEEP_GENERATED_FILES:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def remove_temporary_file(path: str | os.PathLike[str]) -> None:
    """Удаляет временный файл и его пустой каталог операции."""
    file_path = Path(path)
    try:
        file_path.unlink(missing_ok=True)
        file_path.parent.rmdir()
    except OSError:
        pass
