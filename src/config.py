import os
import shutil
import sys
from dotenv import load_dotenv


def _configure_text_output() -> None:
    """Не даёт Windows-консоли с CP1251 падать на сообщениях с emoji."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


_configure_text_output()
load_dotenv()
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Все изменяемые во время работы данные лежат в одном месте. Путь можно
# переопределить переменной DATA_DIR, что удобно для Docker и бэкапов.
DATA_DIR = os.path.abspath(os.getenv("DATA_DIR", os.path.join(ROOT_DIR, "data")))
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
OUTPUT_DIR = os.path.join(DATA_DIR, "files")
TEMP_DIR = os.path.join(DATA_DIR, "tmp")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
DATABASE_PATH = os.path.join(DATA_DIR, "database.db")


def _migrate_legacy_data() -> None:
    """Один раз копирует старые данные из корня проекта в data/."""
    legacy_files = {
        os.path.join(ROOT_DIR, "settings.json"): SETTINGS_FILE,
        os.path.join(ROOT_DIR, "database.db"): DATABASE_PATH,
    }
    for source, destination in legacy_files.items():
        if os.path.isfile(source) and not os.path.exists(destination):
            shutil.copy2(source, destination)

    legacy_sessions = os.path.join(ROOT_DIR, "sessions")
    if os.path.isdir(legacy_sessions) and not os.path.exists(SESSIONS_DIR):
        shutil.copytree(legacy_sessions, SESSIONS_DIR)


def ensure_runtime_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    _migrate_legacy_data()
    for directory in (SESSIONS_DIR, OUTPUT_DIR, TEMP_DIR):
        os.makedirs(directory, exist_ok=True)


ensure_runtime_dirs()


def _get_int_env(name: str, default: int) -> int:
    """Читает целое число из окружения, не ломая запуск пустым .env."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        print(f"Invalid {name!s} value; using {default}.")
        return default


API_ID = _get_int_env("API_ID", 0)
API_HASH = os.getenv("API_HASH", "")
PHONES = os.getenv("PHONES", "").split(",")

# API Keys processing
keys_str = os.getenv("GEMINI_API_KEYS", "")
if not keys_str:
    single_key = os.getenv("GEMINI_API_KEY")
    GEMINI_KEYS = [single_key] if single_key else []
else:
    GEMINI_KEYS = [k.strip() for k in keys_str.split(",") if k.strip()]

YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
EXCHANGE_KEY = os.getenv("EXCHANGE_API_KEY")

# Web Server & Connection Settings
MY_DOMAIN = os.getenv("MY_DOMAIN", "http://localhost:8112")
WEB_PORT = _get_int_env("WEB_PORT", 8112)
INSTANT_VIEW_RHASH = os.getenv("RHASH", "fdaa3d91fdb6eb") # Хеш для IV, если есть
HEALTH_CHECK_INTERVAL = _get_int_env("HEALTH_CHECK_INTERVAL", 30)
MAX_RECONNECT_ATTEMPTS = _get_int_env("MAX_RECONNECT_ATTEMPTS", 10)
RECONNECT_DELAY = _get_int_env("RECONNECT_DELAY", 5)

# По умолчанию результаты команд хранятся в data/files. Для одноразовых
# запусков это можно отключить: KEEP_GENERATED_FILES=false.
KEEP_GENERATED_FILES = os.getenv("KEEP_GENERATED_FILES", "true").strip().lower() in {
    "1", "true", "yes", "on"
}

# Режим получения объявлений OLX. ``auto`` сперва использует браузер с
# изображениями и автоматически переключается на HTTP, если драйвер недоступен.
# На Raspberry Pi удобно задать ``http`` и вовсе не устанавливать Chromium.
OLX_SEARCH_MODE = os.getenv("OLX_SEARCH_MODE", "auto").strip().lower()
if OLX_SEARCH_MODE not in {"auto", "browser", "http"}:
    print("Invalid OLX_SEARCH_MODE value; using auto.")
    OLX_SEARCH_MODE = "auto"

IMAGEN_MODEL = "imagen-3.0-generate-001"

STOP_WORDS = {
    'и', 'в', 'во', 'не', 'на', 'я', 'с', 'со', 'он', 'она', 'оно', 'они', 'а', 'но',
    'да', 'нет', 'к', 'у', 'по', 'за', 'от', 'о', 'из', 'ну', 'ты', 'мы', 'вы',
    'же', 'то', 'бы', 'для', 'до', 'где', 'как', 'так', 'что', 'или', 'это', 'эти',
    'тот', 'те', 'там', 'тут', 'все', 'всё', 'уже', 'еще', 'ещё', 'раз', 'два',
    'мой', 'твой', 'наш', 'ваш', 'кто', 'тут', 'мне', 'меня', 'тебя', 'тебе',
    'был', 'была', 'были', 'есть', 'будет', 'если', 'через', 'при', 'над',
    'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'is', 'are'
}

BAD_EXACT = {
    'хуй', 'хер', 'бля', 'сука', 'еб', 'ёб', 'лох', 'чмо', 'епт', 'мля', 'нах', "заебись", "мудак", "манда", "ебень"
}

BAD_STARTS = [
    'хуе', 'хуё', 'хуя', "аху",
    'еба', 'ебё', 'ебу', 'еби', 'ёба', 'ёбн', 'ебл',
    'заеб', 'доеб', 'поеб', 'наеб', 'выеб', 'уеб', 'перееб',
    'суч', 'хрено'
]

BAD_CONTAINS = [
    'пизд', 'пизж', 'бляд', 'бляц',
    'говно', 'гавно', 'шлюх', 'пидор', 'гандон'
]

AVAILABLE_VOICES = {
    "1": {"name": "Puck", "gender": "M", "desc": "Бодрый, средний тон"},
    "2": {"name": "Charon", "gender": "M", "desc": "Глубокий, низкий"},
    "3": {"name": "Fenrir", "gender": "M", "desc": "Басистый, энергичный"},
    "4": {"name": "Orus", "gender": "M", "desc": "Твердый, ниже среднего"},
    "5": {"name": "Enceladus", "gender": "M", "desc": "С придыханием, низкий"},
    "6": {"name": "Iapetus", "gender": "M", "desc": "Чистый, ниже среднего"},
    "7": {"name": "Umbriel", "gender": "M", "desc": "Спокойный, ниже среднего"},
    "8": {"name": "Algieba", "gender": "M", "desc": "Гладкий, низкий"},
    "9": {"name": "Algenib", "gender": "M", "desc": "Хриплый, низкий"},
    "10": {"name": "Achernar", "gender": "M", "desc": "Мягкий, высокий"},
    "11": {"name": "Alnilam", "gender": "M", "desc": "Твердый, ниже среднего"},
    "12": {"name": "Schedar", "gender": "M", "desc": "Ровный, ниже среднего"},
    "13": {"name": "Zubenelgenubi", "gender": "M", "desc": "Небрежный, ниже среднего"},
    "14": {"name": "Zephyr", "gender": "F", "desc": "Светлый, высокий"},
    "15": {"name": "Kore", "gender": "F", "desc": "Твердый, средний"},
    "16": {"name": "Leda", "gender": "F", "desc": "Молодой, высокий"},
    "17": {"name": "Aoede", "gender": "F", "desc": "Легкий, средний"},
    "18": {"name": "Callirrhoe", "gender": "F", "desc": "Беззаботный, средний"},
    "19": {"name": "Autonoe", "gender": "F", "desc": "Яркий, средний"},
    "20": {"name": "Despina", "gender": "F", "desc": "Гладкий, средний"},
    "21": {"name": "Erinome", "gender": "F", "desc": "Чистый, средний"},
    "22": {"name": "Rasalgethi", "gender": "F", "desc": "Информативный, средний"},
    "23": {"name": "Laomedeia", "gender": "F", "desc": "Бодрый, высокий"},
    "24": {"name": "Gacrux", "gender": "F", "desc": "Зрелый, средний"},
    "25": {"name": "Pulcherrima", "gender": "F", "desc": "Прямолинейный, средний"},
    "26": {"name": "Achird", "gender": "F", "desc": "Дружелюбный, ниже среднего"},
    "27": {"name": "Vindemiatrix", "gender": "F", "desc": "Нежный, средний"},
    "28": {"name": "Sadachbia", "gender": "F", "desc": "Живой, низкий"},
    "29": {"name": "Sadaltager", "gender": "F", "desc": "Знающий, средний"},
    "30": {"name": "Sulafat", "gender": "F", "desc": "Теплый, средний"}
}

AVAILABLE_MODELS = {
    "1": {"id": "gemini-2.5-flash", "name": "⚡️ 2.5 Flash (Google Search)", "search": True},
    "2": {"id": "gemini-3-flash-preview", "name": "⚡️ 3 Flash (Google Search)", "search": True},
    "3": {"id": "gemini-2.5-pro", "name": "🧠 2.5 Pro (Thinking)", "search": False},
    "4": {"id": "gemini-2.0-flash", "name": "🚀 2.0 Flash (Fast)", "search": False},
}

AVAILABLE_TTS_MODELS = {
    "1": "gemini-2.5-pro-preview-tts",
    "2": "gemini-2.5-flash-preview-tts",
}

VOICE_NAMES_LIST = [
    "Puck", "Zephyr", "Fenrir", "Leda", "Charon", "Aoede",
    "Orus", "Autonoe", "Algenib", "Erinome", "Enceladus", "Kore"
]

HELP_DICT = {
    "🧠 **Нейросети (AI):**": {
        "`.ai` / `.аи` _[запрос]_": "Разовый вопрос к Gemini.",
        "`.chat` / `.чат` _[текст]_": "Диалог с памятью контекста.",
        "`.text` / `.stt` _(Reply)_": "Распознать ГС/Видео в текст.",
        "`.ait` _[тема]_": "Статья на вашем Web-сервере.",
        "`.chatt` _[текст]_": "Ответ чата в виде Web-статьи.",
        "`.model` / `.модель`": "Выбор модели.",
        "`.history`": "Показать последние сообщения.",
        "`.reset`": "Сброс памяти диалога."
    },
    "🔊 **Звук (Voice):**": {
        "`.say` / `.скажи` _[текст]_": "Озвучить текст (ГС).",
        "`.saywav` _[текст]_": "Озвучить текст (WAV файл).",
        "`.voice` / `.голос`": "Выбор голоса.",
        "`.ttsmodel`": "Выбор движка TTS.",
        "`.dialog` / `.t`": "Озвучить диалог по ролям.",
        "`.podcast`": "Создать и озвучить подкаст."
    },
    "🎨 **Генерация:**": {
        "`.img` [промпт]": "Google Imagen 3.",
        "`.flux` [промпт]": "Flux.1 (Pollinations)."
    },
    "🛠 **Инструменты:**": {
        "`.stat`": "Аналитика чата.",
        "`.cal`": "Калькулятор.",
        "`.cur`": "Конвертер валют.",
        "`.dl`": "Скачать медиа.",
        "`.olx`": "Парсинг OLX (см. раздел ниже).",
        "`.sys`": "Статус сервера.",
        "`.s`": "Удалить пробелы."
    },
    "📦 **OLX Парсер (Подробно):**": {
        "`.olx [запрос]`": "Базовый поиск (1 стр, с фото)",
        "`.olx [запрос] p=N`": "N страниц результатов",
        "`.olx [запрос] noimg`": "Без фото (быстрее)",
        "`.olx [запрос] from=100000`": "Минимальная цена (сум)",
        "`.olx [запрос] to=500000`": "Максимальная цена (сум)",
        "`.olx [запрос] state=new`": "Только новые товары",
        "`.olx [запрос] state=used`": "Только б/у товары",
        "`.olx A, B, C`": "Несколько запросов в 1 файл (через , или ;)",
        "_Пример:_": "`.olx iphone p=5 from=100000 to=500000 state=new`",
        "_Пример multi:_": "`.olx Phillips, Braun p=3 from=50000`"
    },
    "🎭 **Настройки:**": {
        "`.sysglobal`": "Глобальная роль AI.",
        "`.syschat`": "Роль для чата.",
        "`.bl` / `.unbl`": "Черный список."
    }
}
