import asyncio
import re
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static, DataTable, Label
from textual.containers import Horizontal, Vertical
from textual import on
from pyrogram import Client
from src.config import API_ID, API_HASH, PHONES

# --- ЖЕСТКИЙ CSS (Fix Layout) ---
CSS = """
Screen { 
    background: #121212; 
    color: #e0e0e0;
}

/* ЛЕВАЯ ПАНЕЛЬ (Фиксированная ширина) */
#sidebar { 
    width: 30;  /* Фиксируем в символах, не в % */
    min-width: 20;
    max-width: 40;
    height: 100%; 
    dock: left; 
    border-right: vkey $success; 
    background: #1e1e1e; 
}

#search-box { 
    dock: top; 
    height: 3; 
    border-bottom: vkey $success;
    background: #252526;
    color: white;
}

#chat-table { 
    height: 1fr; 
    width: 100%;
}

/* ПРАВАЯ ПАНЕЛЬ */
#chat-area { 
    width: 1fr; /* Занимает все остальное место */
    height: 100%; 
    layout: vertical; 
}

#chat-header { 
    height: 3; 
    border-bottom: vkey $success; 
    content-align: center middle; 
    background: #252526; 
    text-style: bold;
    color: $success;
}

#message-log { 
    height: 1fr; 
    border-bottom: vkey $success; 
    background: #121212; 
    scrollbar-size: 1 2;
}

#msg-input { 
    dock: bottom; 
    height: 3; 
    border: vkey $success;
    background: #1e1e1e;
}
"""


def clean_chat_title(title):
    """Удаляет эмодзи и спецсимволы из названия чата для стабильности"""
    if not title: return "Unknown"
    # Оставляем только буквы, цифры и базовую пунктуацию
    # Это "злой" фильтр, но он гарантирует ровный интерфейс
    clean = re.sub(r'[^\w\s\-\.\(\)\[\]]', '', title)
    return clean.strip() or "Chat"


class TelegramTui(App):
    CSS = CSS
    BINDINGS = [("q", "quit", "Выход"), ("r", "refresh", "Обновить")]

    def __init__(self):
        super().__init__()
        phone = PHONES[0].strip()
        clean_phone = phone.replace("+", "")
        # Используем ту же сессию, что создали через tui_auth.py
        self.client = Client(f"sessions/{clean_phone}", api_id=API_ID, api_hash=API_HASH)
        self.current_chat_id = None
        self.all_dialogs = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            # Сайдбар
            with Vertical(id="sidebar"):
                yield Input(placeholder="Поиск...", id="search-box")
                # cursor_type="row" важен для выделения всей строки
                yield DataTable(id="chat-table", cursor_type="row", zebra_stripes=True)

            # Чат
            with Vertical(id="chat-area"):
                yield Label("Выберите чат (Enter)", id="chat-header")
                yield RichLog(id="message-log", markup=True, wrap=True)
                yield Input(placeholder="Сообщение...", id="msg-input")
        yield Footer()

    async def on_mount(self):
        self.title = "TG Console"

        # Настройка таблицы
        table = self.query_one("#chat-table", DataTable)
        table.add_column("Chats", width=30)  # Фикс ширины колонки
        table.show_header = False

        # Запуск клиента в фоне
        asyncio.create_task(self.start_client())

    async def start_client(self):
        try:
            # Пытаемся подключиться. Если файл сессии (tui_auth) есть - зайдет сразу
            is_auth = await self.client.connect()

            if not is_auth:
                # Если авторизации нет - паникуем (так как input тут не сработает)
                self.notify("❌ ОШИБКА: Запустите src/tui_auth.py сначала!", severity="error", timeout=10)
                return

            await self.client.start()  # Start запускает хендлеры
            self.notify("✅ Подключено")
            await self.load_dialogs()

            # Real-time listener
            @self.client.on_message()
            async def handler(c, m):
                # Если сообщение в текущем чате - рисуем
                if m.chat.id == self.current_chat_id:
                    self.append_message(m)

        except Exception as e:
            self.notify(f"Connection Error: {e}", severity="error")

    async def load_dialogs(self):
        self.all_dialogs = []
        try:
            async for d in self.client.get_dialogs(limit=40):
                if d.is_archived: continue

                raw_name = d.chat.first_name or d.chat.title or "Unknown"
                if d.chat.last_name: raw_name += f" {d.chat.last_name}"

                # Чистим имя от эмодзи для списка
                clean_name = clean_chat_title(raw_name)

                # Обрезаем длинные имена
                if len(clean_name) > 20: clean_name = clean_name[:18] + ".."

                self.all_dialogs.append((clean_name, d.chat.id))

            self.update_chat_list()
        except Exception as e:
            self.notify(f"Load Error: {e}", severity="error")

    def update_chat_list(self, query=""):
        table = self.query_one("#chat-table", DataTable)
        table.clear()

        query = query.lower()
        for name, chat_id in self.all_dialogs:
            if query in name.lower():
                # Добавляем строку. Ключ строки = ID чата (важно для клика)
                table.add_row(name, key=str(chat_id))

    @on(Input.Changed, "#search-box")
    def on_search(self, event):
        self.update_chat_list(event.value)

    @on(DataTable.RowSelected)
    async def on_chat_click(self, event):
        # Получаем ID чата из ключа строки
        chat_id = int(event.row_key.value)
        self.current_chat_id = chat_id

        # Ищем имя (оригинальное, или очищенное)
        name = next((n for n, i in self.all_dialogs if i == chat_id), "Chat")
        self.query_one("#chat-header", Label).update(f"💬 {name}")

        # Фокус на поле ввода
        self.query_one("#msg-input", Input).focus()

        await self.load_history(chat_id)

    async def load_history(self, chat_id):
        log = self.query_one("#message-log", RichLog)
        log.clear()
        log.write("[yellow]Загрузка истории...[/]")

        try:
            msgs = []
            async for m in self.client.get_chat_history(chat_id, limit=30):
                msgs.append(m)

            log.clear()
            for m in reversed(msgs):
                self.append_message(m)
        except Exception as e:
            log.write(f"[red]Ошибка истории: {e}[/]")

    def append_message(self, m):
        log = self.query_one("#message-log", RichLog)
        time_s = m.date.strftime("%H:%M")

        name = "Unknown"
        color = "white"

        if m.from_user:
            name = m.from_user.first_name
            if m.from_user.is_self:
                color = "green"
                name = "Я"
            else:
                color = "cyan"
        elif m.chat:
            name = m.chat.title
            color = "magenta"

        # Контент
        text = m.text or m.caption or ""
        if m.photo:
            text = f"[📸 Фото] {text}"
        elif m.voice:
            text = f"[🎙 Голос] {text}"
        elif m.sticker:
            text = f"[🤡 Стикер {m.sticker.emoji or ''}]"
        elif m.video:
            text = f"[📹 Видео] {text}"

        # Эмодзи в тексте сообщения ОСТАВЛЯЕМ, RichLog их переварит нормально
        log.write(f"[dim]{time_s}[/] [bold {color}]{name}:[/] {text}")

    @on(Input.Submitted, "#msg-input")
    async def send(self, event):
        text = event.value
        if not text or not self.current_chat_id: return

        try:
            await self.client.send_message(self.current_chat_id, text)
            event.input.value = ""
        except Exception as e:
            self.notify(f"Send Err: {e}", severity="error")

    async def on_unmount(self):
        if self.client and self.client.is_connected:
            await self.client.stop()


if __name__ == "__main__":
    app = TelegramTui()
    app.run()