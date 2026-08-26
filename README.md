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

На Raspberry Pi Docker не обязателен. Для обычного запуска установите Python,
`ffmpeg` и системные библиотеки, затем используйте основной список зависимостей
без `TgCrypto` и принудительно включите лёгкий OLX-поиск:

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# заполните .env и установите OLX_SEARCH_MODE=http
python -m src.main
```

`requirements.txt` не требует `TgCrypto`: Pyrogram работает без ускорителя,
поэтому ошибка сборки нативного модуля больше не блокирует запуск на ARM.
Основной Docker-образ подходит для ПК и сохраняет изображения в OLX-отчётах.
Если Docker всё же нужен на Raspberry Pi, используйте облегчённый профиль без
Chromium, ChromeDriver и `TgCrypto`:

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

### Восстановление после пропадания сети

Клиент больше не завершает работу и не удаляет Telegram-сессию из-за временной
ошибки сети. Он ждёт интернет без конечного таймаута, проверяя несколько
доступных адресов. Интервал проверок постепенно растёт от 5 секунд максимум до
10 минут, а после восстановления сети Pyrogram запускается заново.

Параметры можно изменить в `.env`:

```dotenv
HEALTH_CHECK_INTERVAL=30
MAX_RECONNECT_ATTEMPTS=10
RECONNECT_DELAY=5
OFFLINE_RETRY_MAX_INTERVAL=600
RECONNECT_COOLDOWN=600
```

`OFFLINE_RETRY_MAX_INTERVAL` — максимальная пауза между проверками интернета,
а `RECONNECT_COOLDOWN` — пауза между сериями попыток подключения к Telegram.
Даже после неудачной серии монитор остаётся запущен и пробует снова.

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

## Telegram Reader API для Vex

Reader встроен в тот же процесс Pyrogram и использует уже запущенный клиент — второй процесс session-файл не открывает. При старте и после переподключения он сверяет текущие личные диалоги, а перед каждым запросом непрочитанных заново получает точную Telegram-границу `read_inbox_max_id`.

Основные endpoint'ы:

- `GET /v1/status`;
- `POST /v1/telegram/unread`;
- `POST /v1/telegram/search/private`;
- `POST /v1/telegram/search/channels`;
- `POST /v1/telegram/context`;
- `POST /v1/telegram/read/prepare`;
- `POST /v1/telegram/read/confirm`.

`new_only` показывает только реальные непрочитанные личные сообщения от пользователей, которые Vex ещё не доставил. Сначала создаётся временная reservation; `surfaced_at` устанавливается только после подтверждения успешной доставки OpenClaw. Это не изменяет Telegram read state. `all_unread` повторно показывает всё, что по-прежнему непрочитано в Telegram.

Каналы никогда не попадают в непрочитанные и не индексируются фоном. Они читаются только явным поиском; рабочая область v1 ограничена уже подключёнными каналами. Установленный Pyrogram 2.0.106 ищет глобально только по чатам аккаунта и не предоставляет безопасный бесплатный поиск по всем публичным постам, поэтому `public_global` закрыт явной ошибкой `501` вместо ложного результата или расходования Stars. Семантическое ранжирование выполняет OpenClaw через настраиваемый embedding endpoint, а при его отсутствии сохраняется обычный lexical/fuzzy результат.

Отметка прочитанным выполняется только в два шага: preview с короткоживущим токеном, затем отдельное подтверждение. Telegram отмечает прочитанными все сообщения диалога до подготовленного `max_message_id`.

API закрыт приложенческим Bearer-токеном и, в production, Cloudflare Access service token. Значения задаются только через окружение. CORS не включён; размер запросов, лимиты выдачи и частота вызовов ограничены. Инструкция для вашего будущего ручного переноса находится в `deploy/README.md`.
