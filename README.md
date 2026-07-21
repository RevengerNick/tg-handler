# tg-handler

Пользовательский Telegram-клиент на Pyrogram с Gemini, генерацией изображений
и озвучки, скачиванием медиа, парсером OLX, статистикой чатов и небольшим
веб-сервером для публикации статей.

> Это userbot: он работает от имени Telegram-аккаунта, указанного в `PHONES`.
> Используйте его с учётом правил Telegram и чатов, в которых он включён.

## Что умеет

- ответы Gemini в обычном и диалоговом режиме;
- TTS, диалоги и подкасты;
- распознавание голосовых и видео;
- изображения через Imagen и Flux;
- скачивание видео, аудио и треков Яндекс.Музыки;
- отчёты OLX в Excel, в том числе с фильтрами;
- статистика чата, курсы валют и локальные web-статьи.

## Быстрый запуск локально

Нужен Python 3.12 или 3.13 и `ffmpeg` в `PATH` (для голосовых сообщений и
скачивания медиа).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Заполните `.env`:

```dotenv
API_ID=123456
API_HASH=telegram_api_hash
PHONES=998901234567
GEMINI_API_KEYS=key_one,key_two
MY_DOMAIN=http://localhost:8112
WEB_PORT=8112
```

Затем запустите:

```powershell
python -m src.main
```

При первом запуске клиент предложит вход по QR-коду или номеру. Не добавляйте
`.env`, `data/` или файлы сессий в Git.

## Docker

Docker-образ содержит Chromium/ChromeDriver и ffmpeg. Все изменяемые данные
монтируются в `./data`, поэтому не теряются при пересоздании контейнера.

```powershell
Copy-Item .env.example .env
# заполните .env
docker compose up --build
```

Первый запуск оставьте в интерактивном режиме, чтобы пройти авторизацию. После
успешного входа можно запустить сервис в фоне:

```powershell
docker compose up -d
docker compose logs -f userbot
```

Веб-сервер доступен на `http://localhost:8112` по умолчанию. Если внешний
домен отличается от локального адреса, задайте `MY_DOMAIN` как публичный URL,
а `WEB_PORT` оставьте портом, на котором должен слушать контейнер.

## Raspberry Pi и запуск без браузера

Основной образ подходит для ПК и сохраняет изображения в OLX-отчётах. На
Raspberry Pi рекомендуется облегчённый профиль: в нём нет Chromium,
ChromeDriver и `TgCrypto`, поэтому сборка и запуск не зависят от браузерного
драйвера или нативного крипто-модуля.

```bash
cp .env.example .env
# заполните .env
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.pi.yml logs -f userbot
```

Первую авторизацию Telegram выполните в интерактивном режиме, убрав `-d`.
Профиль Raspberry Pi задаёт `OLX_SEARCH_MODE=http`: поиск создаёт тот же Excel,
но без встроенных фотографий. Это экономит память и не требует Selenium,
Playwright, Chromium или драйвера браузера.

`TgCrypto` ускоряет криптографию Pyrogram, но не обязателен для его работы.
Если на конкретном компьютере или Pi он устанавливается без ошибок, его можно
добавить отдельно: `pip install -r requirements-accelerated.txt`.

### Режимы поиска OLX

- `OLX_SEARCH_MODE=auto` — значение по умолчанию на ПК: сначала Selenium с
  фото, а при сбое браузера или пустом браузерном отчёте — HTTP-поиск без фото.
- `OLX_SEARCH_MODE=browser` — только Selenium; полезно, если HTTP-запросы к
  OLX ограничены и нужен отчёт с фотографиями.
- `OLX_SEARCH_MODE=http` — только лёгкий HTTP-поиск без браузера и без фото;
  рекомендован для Raspberry Pi.

OLX может ограничить HTTP-запросы или изменить разметку сайта. В таком случае
бот не упадёт, а вернёт обычное сообщение, что объявлений не найдено; логи
покажут причину. Переключите режим на `browser`, если на устройстве есть
исправный Chromium и ChromeDriver.

## Данные и результаты

```text
data/
├── sessions/        Telegram-сессии
├── settings.json    настройки модели, голосов и Telegraph
├── database.db      статьи локального веб-сервера
├── files/           сохранённые результаты команд
│   ├── audio/
│   ├── downloads/
│   ├── history/
│   ├── images/
│   └── olx/
└── tmp/             краткоживущие рабочие файлы
```

По умолчанию файлы из `data/files/` остаются на диске после отправки в
Telegram. Чтобы сделать запуск одноразовым и удалять их после отправки,
укажите в `.env`:

```dotenv
KEEP_GENERATED_FILES=false
```

Старые `settings.json`, `database.db` и папка `sessions/` в корне проекта
безопасно копируются в `data/` при первом запуске новой версии. После проверки
можно удалить старые копии из корня.

## Обслуживание и диагностика

- Проверить зависимости: `python -m pip check`.
- Проверить конфигурацию Docker: `docker compose config`.
- Посмотреть логи: `docker compose logs -f userbot`.
- OLX в `auto` использует headless Chromium и автоматически переключается на
  HTTP при сбое браузера. Если сайт изменит разметку или ограничит запросы,
  отчёт может оказаться пустым — это не ошибка Excel.
- `MY_DOMAIN` должен быть доступен Telegram, если используются ссылки
  Instant View; `localhost` подходит только для локального просмотра.

## Обновление зависимостей

Версии в `requirements.txt` намеренно закреплены, чтобы локальный запуск и
Docker использовали один набор библиотек. Обновляйте их осознанно, затем
проверьте `python -m pip check`, `python -m compileall src` и пересоберите
образ командой `docker compose build --no-cache`.
