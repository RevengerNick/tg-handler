from __future__ import annotations

import re

_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{6,16}$")
_CHOICE = re.compile(r"^(best|audio|cancel|\d{3,4})$")


class CallbackCodec:
    prefix = "dl"

    @classmethod
    def encode(cls, job_id: str, choice: str) -> str:
        if not _JOB_ID.fullmatch(job_id) or not _CHOICE.fullmatch(choice):
            raise ValueError("Invalid download callback")
        value = f"{cls.prefix}:{job_id}:{choice}"
        if len(value.encode("utf-8")) > 64:
            raise ValueError("Callback data exceeds Telegram limit")
        return value

    @classmethod
    def decode(cls, value: str | None) -> tuple[str, str]:
        if not value:
            raise ValueError("Invalid download callback")
        parts = value.split(":")
        if len(parts) != 3 or parts[0] != cls.prefix:
            raise ValueError("Invalid download callback")
        job_id, choice = parts[1:]
        if not _JOB_ID.fullmatch(job_id) or not _CHOICE.fullmatch(choice):
            raise ValueError("Invalid download callback")
        return job_id, choice
