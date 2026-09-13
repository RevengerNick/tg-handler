# Third-party notices

This project depends on third-party software. Those components remain subject
to their own copyright and license terms; the project's MIT license does not
replace them.

| Component | Use | License / source |
|---|---|---|
| PyrogramMod 2.4.1 | Telegram MTProto client and Rich Messages | LGPL-3.0-or-later — https://github.com/PyrogramMod/PyrogramMod |
| aiogram 3.31.0 | Companion Bot API control plane | MIT — https://github.com/aiogram/aiogram |
| google-genai 2.23.0 | Gemini API SDK | Apache-2.0 — https://github.com/googleapis/python-genai |
| yt-dlp 2026.08.19 | Primary media downloader | Unlicense — https://github.com/yt-dlp/yt-dlp/tree/2026.08.19 |
| OmniGet 0.9.2 | Optional native/fallback downloader | GPL-3.0 — https://github.com/tonhowtf/omniget/tree/v0.9.2 |
| FFmpeg | Media merge and conversion | LGPL/GPL depending on build — https://ffmpeg.org/legal.html |
| Deno 2.9.5 | JavaScript runtime used by yt-dlp | MIT — https://github.com/denoland/deno |
| FastAPI / Uvicorn | HTTP API and local articles | MIT / BSD-3-Clause |

The Docker build downloads the unmodified OmniGet v0.9.2 Linux x86_64 CLI
release artifact and verifies SHA-256
`d166ffe9461b35190813cd710250a22aeaa15abef6148aad7d954c2d09ce6f65`.
Corresponding source and the complete GPL-3.0 license are available at the
upstream v0.9.2 tag linked above.

See `requirements.txt` and the container package manager metadata for the full
transitive dependency set.
