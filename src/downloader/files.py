from __future__ import annotations

import shutil
from pathlib import Path

_MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".mp3",
    ".m4a",
    ".ogg",
    ".opus",
    ".wav",
    ".flac",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def find_downloaded_paths(directory: Path) -> list[Path]:
    root = directory.resolve()
    if not root.is_dir():
        return []
    results: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if (
            resolved.is_relative_to(root)
            and resolved.suffix.lower() in _MEDIA_EXTENSIONS
        ):
            results.append(resolved)
    return sorted(results, key=lambda value: (value.parent.as_posix(), value.name))


def cleanup_job_directory(directory: Path, temporary_root: Path) -> None:
    root = temporary_root.resolve()
    target = directory.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Refusing to clean a path outside the download root")
    if target.exists():
        shutil.rmtree(target)
