# tg-handler

Персональный Telegram userbot на PyrogramMod: Gemini AI, Rich Messages,
универсальное скачивание медиа, Telegram Reader API, голосовые инструменты,
локальные статьи, OLX-отчёты и бытовые команды.

> Приложение работает от имени аккаунтов из `PHONES`. Используйте его только
> для своих аккаунтов и контента, к которому у них есть законный доступ.

## Возможности

- `.ai` — разовый ответ Gemini как нативный Telegram RichMessage;
- `.chat` — диалог с памятью, тоже как RichMessage;
- `.ait` и `.chatt` — длинный ответ сразу в виде локальной web-статьи;
- актуальные aliases `gemini-flash-latest`, `gemini-flash-lite-latest` и
  `gemini-pro-latest`, а также закреплённая стабильная Flash-модель;
- TTS, многоголосые диалоги, подкасты и распознавание аудио/видео;
- изображения через Gemini и Flux;
- интерактивный `.dl` с реальными вариантами качества;
- быстрый `.dlo`/`.dl0` с качеством не выше 480p;
- YouTube, Instagram Posts/Reels/Stories/Highlights, TikTok, X, Reddit и
  другие сайты, поддерживаемые yt-dlp; Yandex Music сохранён;
- yt-dlp как основной backend, OmniGet CLI как native fallback, ffmpeg для
  merge/postprocessing;
- cookies для авторизованного доступа без сохранения секретов в Git;
- Excel-отчёты OLX, статистика чатов, валюты и Telegram Reader HTTP API.

## Как устроен downloader

```text
.dl URL (Pyrogram userbot)
        │
        ├── metadata: yt-dlp → при допустимой ошибке OmniGet
        ├── DownloadJob в data/download_jobs.db, TTL 20 минут
        └── личное сообщение companion-бота с inline-кнопками
                            │
                            ▼
                 выбор качества / cancel
                            │
                            ▼
              yt-dlp → OmniGet fallback → ffmpeg/ffprobe
                            │
                            ▼
       файл(ы) отправляет Pyrogram userbot в исходный чат
```

Companion-бот — только control plane. Он не отправляет скачанные файлы и
обрабатывает callbacks только от `DOWNLOAD_CONTROL_USER_ID`. Каждая job имеет
отдельный каталог `data/tmp/downloads/<job_id>/`; каталог удаляется после
успеха, ошибки или отмены. Одновременно по умолчанию выполняется одна загрузка,
максимум разрешено две — это рассчитано на небольшой VPS.

### Команды скачивания

```text
.dl URL            интерактивный выбор доступного качества
.dl best URL       лучшее качество без кнопок
.dl 1080 URL       качество до 1080p
.dl 720 URL        качество до 720p
.dl 480 URL        качество до 480p
.dl audio URL      только аудио
.dlo URL           автоматически до 480p
.dl0 URL           то же самое
```

Старые aliases сохранены: `0 = best`, `1 = 480`, `2 = audio`. Ссылку можно
взять из текста/caption сообщения, ответив на него командой `.dl`. Если reply
содержит Telegram-видео, audio или document, он не трактуется как web URL.

Кнопки строятся только по реально найденным форматам. Для Instagram и
коллекций интерфейс намеренно проще: «Скачать», «Audio», «Cancel». Carousel и
Stories могут вернуть несколько файлов — userbot отправит их последовательно.

## Rich Messages для AI

`.ai` и `.chat` собирают ответ модели и отправляют его от того же user-аккаунта
как нативный RichMessage. Markdown преобразуется в Telegram blocks: заголовки,
абзацы, списки, таблицы, цитаты, ссылки и fenced code blocks.

Rich Messages у user-аккаунтов требуют Telegram Premium и свежий Telegram
клиент. Если сервер Telegram отклоняет этот тип сообщения либо ответ превышает
лимит 32 768 символов, создаётся локальная статья. `.ait`/`.chatt` всегда
создают статью напрямую. Для поддержки нового MTProto layer используется
PyrogramMod 2.4.1 вместо архивного Pyrogram 2.0.106.

## Установка

Нужны Python 3.12/3.13 и `ffmpeg`/`ffprobe` в `PATH`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

Минимальные обязательные параметры:

```dotenv
API_ID=123456
API_HASH=telegram_api_hash
PHONES=998901234567
GEMINI_API_KEYS=key_one,key_two
MY_DOMAIN=https://example.com
WEB_PORT=8112
```

При первом запуске Pyrogram предложит вход по QR или коду. Не добавляйте
`.env`, `data/`, `*.session`, cookies или API keys в Git.

## Companion-бот через BotFather

1. Откройте `@BotFather`, выполните `/newbot` и сохраните token только в `.env`.
2. Напишите новому боту `/start`, иначе он не сможет первым отправить личное
   сообщение.
3. Узнайте свой numeric Telegram user ID и задайте его как control user.
4. Перезапустите контейнер/процесс.

```dotenv
DOWNLOAD_BOT_TOKEN=123456:secret
DOWNLOAD_CONTROL_USER_ID=123456789
DOWNLOAD_MAX_CONCURRENT=1
DOWNLOAD_JOB_TTL_SECONDS=1200
DOWNLOAD_MAX_FILES=10
```

Без companion-бота быстрые команды `.dlo` и `.dl QUALITY URL` продолжают
работать, а интерактивный `.dl URL` покажет понятную подсказку о настройке.

## Cookies и авторизация

Создайте каталог `data/cookies/` и положите туда Netscape `cookies.txt`:

```text
data/cookies/
├── instagram.txt
├── youtube.txt
└── x.txt
```

Экспортируйте cookies только из своего браузера и только для аккаунта, который
имеет доступ к материалу. Рекомендуемые права на Linux:

```bash
chmod 700 data/cookies
chmod 600 data/cookies/*.txt
```

Диагностика:

```text
.cookies
.cookies test instagram
.cookies test instagram https://www.instagram.com/.../
.cookies test youtube https://www.youtube.com/watch?v=...
```

Команда без URL проверяет наличие, Netscape-формат и сроки записей. Вариант с
URL делает metadata-запрос без скачивания большого файла. Значения cookies не
выводятся в Telegram и логи. При `login required` пользователь получает
отдельное сообщение об истёкшей авторизации вместо общей ошибки.

Instagram Stories, Highlights и Close Friends доступны только тогда, когда
экспортированная сессия действительно видит этот контент. Проект не обходит
ограничения доступа.

## Docker и VPS

Полный образ включает Chromium для OLX, ffmpeg, Deno для yt-dlp EJS и OmniGet
CLI на `amd64`:

```bash
cp .env.example .env
docker compose up --build
# после первой авторизации
docker compose up -d
docker compose logs -f userbot
```

Для небольшого VPS используется лёгкий override:

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs -f userbot
```

На ARM/Raspberry Pi OmniGet CLI не устанавливается, потому что upstream не
публикует Linux ARM artifact. Downloader продолжает работать через yt-dlp.
Профиль `docker-compose.pi.yml` также отключает браузерный режим OLX.

OmniGet 0.9.2 скачивается на этапе сборки с закреплённого release URL и
проверяется по SHA-256; бинарный файл в репозитории не хранится.

## Данные

```text
data/
├── sessions/                 Telegram session files
├── cookies/                  cookies.txt, только локально
├── files/                    сохраняемые результаты других команд
├── tmp/downloads/<job_id>/   временные загрузки `.dl`
├── download_jobs.db          registry downloader jobs
├── database.db               локальные статьи
├── telegram_reader.db        индекс Reader API
└── settings.json             выбранные модели и настройки
```

Все данные монтируются как `./data:/app/data`. Незавершённые интерактивные jobs
живут до TTL. Начатые jobs после рестарта помечаются failed; временные каталоги
очищаются при завершении каждой попытки.

## Telegram Reader API

Reader использует уже запущенный Pyrogram client, не открывая session вторым
процессом. Endpoint'ы: `/v1/status`, `/v1/telegram/unread`, private/channel
search, context и двухфазные read prepare/confirm. API защищается Bearer token и
опционально Cloudflare Access; параметры перечислены в `.env.example`, детали
деплоя — в `deploy/README.md`.

## Проверка и обслуживание

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip check
docker compose config
docker compose -f docker-compose.yml -f docker-compose.vps.yml config
```

Статья открывается по `${MY_DOMAIN}/view/<id>`. `MY_DOMAIN` должен быть доступен
из интернета, а reverse proxy — направлять запросы на локальный `WEB_PORT`.

## Использованные технологии

- PyrogramMod / MTProto — userbot и нативные Rich Messages;
- aiogram 3 — companion Bot API polling и callbacks;
- Google Gen AI SDK — Gemini text, image, transcription и TTS;
- yt-dlp + Deno + curl_cffi — metadata и основной downloader;
- OmniGet CLI — дополнительный downloader/fallback;
- ffmpeg/ffprobe — merge, audio conversion и media metadata;
- FastAPI, Uvicorn, SQLite, Jinja2 и Python-Markdown — Reader API и статьи;
- Yandex Music SDK, Selenium, BeautifulSoup, openpyxl и Pillow — остальные
  существующие функции проекта.

Полный список внешних компонентов и лицензий находится в
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Лицензия

Собственный код проекта распространяется по MIT License — см. [`LICENSE`](LICENSE).
Внешние программы и библиотеки сохраняют собственные лицензии. OmniGet
распространяется по GPL-3.0; Docker-образ получает неизменённый официальный
release artifact, а исходный код закреплённой версии доступен у upstream.
