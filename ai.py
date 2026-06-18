"""
AI-модуль для анализа новостей.
Использует OpenRouter API для:
1. Определения "горячих" новостей
2. Семантической дедупликации
"""
import os
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _call_ai(messages: list, max_tokens: int = 500) -> str:
    """Вызов OpenRouter API"""
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set, AI features disabled")
        return ""

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return ""


def is_hot_news(title: str, description: str = "") -> bool:
    """
    Определить, является ли новость "горячей" (главной за час).
    Горячая новость — это событие, которое важно для жителей Екатеринбурга:
    ЧП, аварии, важные решения властей, крупные события в городе.
    """
    if not OPENROUTER_API_KEY:
        # Если нет API-ключа, считаем все новости горячими
        return True

    text = f"{title}\n{description}"[:500]

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — редактор новостного бота Екатеринбурга. "
                "Определи, является ли новость ГЛАВНОЙ (горячей) для жителей города. "
                "Главная новость — это: ЧП, аварии, важные решения властей, "
                "крупные события в Екатеринбурге, что-то что затрагивает многих людей. "
                "НЕ главная: реклама, развлечения, спорт (если не очень важный), "
                "новости из других регионов/стран, рутина. "
                "Ответь только JSON: {\"is_hot\": true/false, \"reason\": \"краткое объяснение\"}"
            ),
        },
        {
            "role": "user",
            "content": f"Новость: {text}",
        },
    ]

    result = _call_ai(messages, max_tokens=100)
    if not result:
        return True  # По умолчанию считаем горячей

    try:
        data = json.loads(result)
        is_hot = data.get("is_hot", True)
        reason = data.get("reason", "")
        logger.info(f"AI hot news check: {is_hot} ({reason}) — {title[:60]}")
        return is_hot
    except json.JSONDecodeError:
        return True


def are_duplicates(title1: str, title2: str) -> bool:
    """
    Проверить, являются ли две новости дубликатами (об одном и том же событии).
    Использует AI для семантического сравнения.
    """
    if not OPENROUTER_API_KEY:
        # Без AI — простое сравнение
        return title1.strip().lower() == title2.strip().lower()

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — редактор новостного бота. "
                "Определи, являются ли два заголовка новостями ОБ ОДНОМ И ТОМ ЖЕ событии. "
                "Ответь только JSON: {\"duplicate\": true/false}"
            ),
        },
        {
            "role": "user",
            "content": f"Заголовок 1: {title1}\nЗаголовок 2: {title2}",
        },
    ]

    result = _call_ai(messages, max_tokens=50)
    if not result:
        return title1.strip().lower() == title2.strip().lower()

    try:
        data = json.loads(result)
        return data.get("duplicate", False)
    except json.JSONDecodeError:
        return False


def select_best_news(news_list: list) -> list:
    """
    Из списка новостей выбрать лучшие (главные) для отправки.
    Использует AI для определения горячих новостей.
    Дедупликация — по ключевым словам (быстро) + AI для семантики (опционально).
    """
    if not news_list:
        return []

    # Шаг 1: Убираем точные дубликаты по заголовку
    seen_titles = set()
    unique = []
    for news in news_list:
        t = news['title'].strip().lower()
        if t not in seen_titles and len(t) > 5:
            seen_titles.add(t)
            unique.append(news)

    # Шаг 2: Дедупликация по ключевым словам (быстро, без AI)
    import re
    filtered = []
    for news in unique:
        title_words = set(re.findall(r'\w{3,}', news['title'].lower()))
        is_dup = False
        for existing in filtered:
            existing_words = set(re.findall(r'\w{3,}', existing['title'].lower()))
            if title_words and existing_words:
                overlap = len(title_words & existing_words) / min(len(title_words), len(existing_words))
                if overlap > 0.6:  # 60% совпадения
                    is_dup = True
                    break
        if not is_dup:
            filtered.append(news)

    # Шаг 3: AI-отбор горячих новостей (если есть ключ)
    if OPENROUTER_API_KEY and len(filtered) > 1:
        hot_news = []
        for news in filtered[:15]:  # Ограничиваем для скорости
            try:
                if is_hot_news(news['title'], news.get('description', '')):
                    hot_news.append(news)
            except Exception as e:
                logger.error(f"AI error: {e}")
                hot_news.append(news)  # При ошибке включаем
        if hot_news:
            return hot_news[:10]

    return filtered[:10]


def generate_summary(title: str, description: str = "") -> str:
    """Генерировать краткое описание новости, если его нет"""
    if not OPENROUTER_API_KEY:
        return description

    if description and len(description) > 50:
        return description

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — редактор новостного бота. "
                "Напиши краткое описание новости (1-2 предложения) на основе заголовка. "
                "Пиши на русском языке, нейтральным тоном."
            ),
        },
        {
            "role": "user",
            "content": f"Заголовок: {title}",
        },
    ]

    result = _call_ai(messages, max_tokens=150)
    return result if result else description


if __name__ == "__main__":
    # Тест
    print("Testing AI module...")

    test_news = [
        {"title": "В Екатеринбурге произошло ДТП с участием автобуса", "description": ""},
        {"title": "ДТП с автобусом в Екатеринбурге: есть пострадавшие", "description": ""},
        {"title": "Крупный пожар на складе в центре Екатеринбурга", "description": ""},
        {"title": "Новый торговый центр открылся в Екатеринбурге", "description": ""},
        {"title": "Цены на бензин выросли на 5% в Свердловской области", "description": ""},
    ]

    print("\n=== Дедупликация ===")
    best = select_best_news(test_news)
    for n in best:
        print(f"  ✅ {n['title']}")

    print("\n=== Проверка на горячесть ===")
    for n in test_news:
        hot = is_hot_news(n['title'])
        print(f"  {'🔥' if hot else '❄️'} {n['title']}")
