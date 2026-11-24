FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    TGBOT_CONFIG=/app/config/config.json \
    TGBOT_ADMIN_HOST=0.0.0.0 \
    TGBOT_ADMIN_PORT=8088

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    fontconfig \
    fonts-wqy-microhei \
    fonts-noto-color-emoji \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY telegram_bot /app/telegram_bot
COPY config.example.json /app/config.example.json

RUN mkdir -p /app/config /app/sessions /app/runtime/data /app/runtime/logs /app/runtime/tmp

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"TGBOT_ADMIN_PORT\", \"8088\")}/api/auth', timeout=3)" || exit 1

CMD ["python", "-m", "telegram_bot"]
