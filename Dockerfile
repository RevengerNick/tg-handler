# Используем легкий образ Python
FROM python:3.13-slim

# Переменные окружения для Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Устанавливаем системные зависимости
# chromium + driver: для Selenium
# ffmpeg: для yt-dlp
# gcc: запасной вариант, если pip не найдёт готовое колесо для psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Указываем рабочую папку
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Создаем папку сессий, если её нет
RUN mkdir -p /app/data/sessions /app/data/files /app/data/tmp

# Команда запуска
CMD ["python", "-m", "src.main"]
