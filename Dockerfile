FROM python:3.12-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Переменные окружения (переопределяются при запуске через --env-file)
ENV CHECK_INTERVAL="60"
ENV WORK_START_HOUR="11"
ENV WORK_END_HOUR="23"

# Запуск
CMD ["python", "bot.py"]
