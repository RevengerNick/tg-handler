# Используем легкий образ Python
FROM python:3.13-slim

ARG TARGETARCH
ARG OMNIGET_VERSION=0.9.2
ARG OMNIGET_SHA256=d166ffe9461b35190813cd710250a22aeaa15abef6148aad7d954c2d09ce6f65

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
    ca-certificates \
    curl \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# OmniGet ships a native Linux CLI only for amd64. ARM images remain fully
# functional with yt-dlp and report OmniGet as an optional unavailable fallback.
RUN runtime_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    if [ "$runtime_arch" = "amd64" ]; then \
      curl -fsSL -o /tmp/omniget.tar.gz \
        "https://github.com/tonhowtf/omniget/releases/download/v${OMNIGET_VERSION}/omniget-cli-${OMNIGET_VERSION}-x86_64-unknown-linux-gnu.tar.gz"; \
      echo "${OMNIGET_SHA256}  /tmp/omniget.tar.gz" | sha256sum -c -; \
      tar -xzf /tmp/omniget.tar.gz -C /usr/local/bin; \
      chmod 0755 /usr/local/bin/omniget-cli; \
      mv /usr/local/bin/omniget-cli /usr/local/bin/omniget; \
      rm /tmp/omniget.tar.gz; \
    fi

# Указываем рабочую папку
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код
COPY . .

# Создаем папку сессий, если её нет
RUN mkdir -p /app/data/sessions /app/data/files /app/data/tmp/downloads /app/data/cookies

# Команда запуска
CMD ["python", "-m", "src.main"]
