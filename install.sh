#!/bin/bash
# Установка и запуск Новостного бота Екатеринбурга

set -e

echo "📰 Установка Новостного бота Екатеринбурга..."

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установите Python 3.10+"
    exit 1
fi

# Создание виртуального окружения
if [ ! -d "venv" ]; then
    echo "📦 Создание виртуального окружения..."
    python3 -m venv venv
fi

# Активация
source venv/bin/activate

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install -r requirements.txt

# Проверка .env
if [ ! -f ".env" ]; then
    echo "⚠️  Файл .env не найден!"
    echo "Создайте .env на основе .env.example и добавьте TELEGRAM_TOKEN"
    cp .env.example .env
    echo "📝 Отредактируйте файл .env и добавьте токен бота"
    exit 1
fi

echo "✅ Установка завершена!"
echo ""
echo "Для запуска:"
echo "  source venv/bin/activate"
echo "  python bot.py"
echo ""
echo "Или в фоне:"
echo "  nohup python bot.py > bot.log 2>&1 &"
