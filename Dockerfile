# Используем легкий образ Python
FROM python:3.13-slim

# Переменные окружения для Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Устанавливаем системные зависимости
# chromium + driver: для Selenium на ARM
# ffmpeg: для yt-dlp
# gcc, g++: для сборки tgcrypto и psutil
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    ffmpeg \
    gcc \
    g++ \
    libffi-dev \
    python3-dev \
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
RUN mkdir -p sessions

# Команда запуска
CMD ["python", "main.py"]