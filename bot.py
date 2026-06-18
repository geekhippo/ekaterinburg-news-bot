"""
Новостной бот Екатеринбурга.
Собирает новости из 5 источников, выбирает главные с помощью AI,
отправляет подписчикам каждый час (11:00-23:00).
"""
import asyncio
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

sys.path.insert(0, str(Path(__file__).parent))

from parser import UraParser, E1Parser, RU66Parser, ObltvParser, JustMediaParser
from database import (
    init_db, add_news, get_unsent_news, mark_as_sent,
    get_active_subscribers, add_subscriber, deactivate_subscriber,
    cleanup_old_news, get_stats, find_similar_news
)
from ai import select_best_news, generate_summary

load_dotenv(Path(__file__).parent / ".env", override=False)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL", "60"))
WORK_START_HOUR = int(os.getenv("WORK_START_HOUR", "11"))
WORK_END_HOUR = int(os.getenv("WORK_END_HOUR", "23"))

PARSERS = [
    UraParser(),
    E1Parser(),
    RU66Parser(),
    ObltvParser(),
    JustMediaParser(),
]


async def collect_news():
    """Сбор новостей из всех источников с дедупликацией"""
    logger.info("=== collect_news() started ===")
    all_news = []
    new_count = 0
    duplicate_count = 0

    for parser in PARSERS:
        try:
            news_list = parser.get_news()
            logger.info(f"{parser.__class__.__name__}: {len(news_list)} новостей")

            for news in news_list:
                is_new = add_news(
                    title=news['title'],
                    link=news['link'],
                    description=news.get('description', ''),
                    image_url=news.get('image', ''),
                    source=news.get('source', 'Unknown')
                )
                if is_new:
                    all_news.append(news)
                    new_count += 1
                else:
                    duplicate_count += 1

        except Exception as e:
            logger.error(f"Error with {parser.__class__.__name__}: {e}")

    # AI-дедупликация и отбор главных
    if OPENROUTER_API_KEY and len(all_news) > 1:
        filtered = select_best_news(all_news)
        logger.info(f"AI дедупликация: {len(all_news)} -> {len(filtered)} новостей")
    else:
        # Простая дедупликация по ключевым словам
        filtered = []
        for news in all_news:
            similar = find_similar_news(news['title'], hours=6)
            if not similar:
                filtered.append(news)

    # Генерируем описания для новостей без них
    for news in filtered:
        if not news.get('description') and OPENROUTER_API_KEY:
            news['description'] = generate_summary(news['title'])

    logger.info(f"Сбор завершён: {new_count} новых, {duplicate_count} дублей, {len(filtered)} после фильтра")
    return filtered


async def send_news_to_subscribers(context: ContextTypes.DEFAULT_TYPE):
    """Отправка новостей подписчикам"""
    now = datetime.now()
    hour = now.hour

    if hour < WORK_START_HOUR or hour >= WORK_END_HOUR:
        logger.info(f"Вне рабочего времени ({hour}:00)")
        return

    news_list = get_unsent_news(limit=50)
    if not news_list:
        return

    subscribers = get_active_subscribers()
    if not subscribers:
        return

    # AI-отбор лучших
    if OPENROUTER_API_KEY and len(news_list) > 5:
        best_news = select_best_news(news_list)
    else:
        best_news = news_list[:10]

    logger.info(f"Отправка {len(best_news)} новостей {len(subscribers)} подписчикам")

    sent_ids = []
    for news in best_news:
        source_emoji = {
            "URA.RU": "🔴", "E1.RU": "🟡", "66.RU": "🔵",
            "OBLTV.RU": "🟢", "JustMedia": "🟣"
        }.get(news['source'], "📰")

        desc = news.get('description', '') or ''
        text = (
            f"{source_emoji} <b>{news['title']}</b>\n\n"
            f"{desc[:300]}\n\n"
            f"📎 <a href=\"{news['link']}\">Читать полностью</a>\n"
            f"📌 {news['source']}"
        )

        sent_count = 0
        for chat_id in subscribers:
            try:
                if news.get('image_url'):
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=news['image_url'],
                        caption=text[:1024],
                        parse_mode="HTML"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=False
                    )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка {chat_id}: {e}")
                err = str(e).lower()
                if "blocked" in err or "deactivated" in err or "not found" in err:
                    deactivate_subscriber(chat_id)

        sent_ids.append(news['id'])

    mark_as_sent(sent_ids)
    cleanup_old_news(days=7)


async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    """Ежечасная задача"""
    try:
        now = datetime.now()
        logger.info(f"hourly_job triggered at {now.strftime('%H:%M %d.%m.%Y')}, work hours: {WORK_START_HOUR}-{WORK_END_HOUR}")
        if now.hour < WORK_START_HOUR or now.hour >= WORK_END_HOUR:
            logger.info(f"Outside working hours, skipping")
            return

        logger.info("Starting news collection...")
        await collect_news()
        logger.info("News collection done, sending to subscribers...")
        await send_news_to_subscribers(context)
        logger.info("Hourly job completed successfully")
    except Exception as e:
        logger.error(f"Hourly job error: {e}", exc_info=True)


# === Команды ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username or ""
    add_subscriber(chat_id, username)

    keyboard = [
        [InlineKeyboardButton("📰 Последние новости", callback_data="latest")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❌ Отписаться", callback_data="unsubscribe")],
    ]

    await update.message.reply_text(
        "👋 <b>Новости Екатеринбурга</b>\n\n"
        "Главные новости города каждый час!\n"
        f"⏰ {WORK_START_HOUR}:00 — {WORK_END_HOUR}:00\n\n"
        "📌 Источники:\n"
        "🔴 URA.RU · 🟡 E1.RU · 🔵 66.RU\n"
        "🟢 OBLTV.RU · 🟣 JustMedia\n\n"
        "🤖 AI выбирает главные новости и убирает дубли.\n\n"
        "/news — последние новости\n"
        "/stats — статистика\n"
        "/stop — отписаться",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news_list = get_unsent_news(limit=10)
    if not news_list:
        await update.message.reply_text("📭 Пока нет новостей.")
        return

    for news in news_list[:5]:
        emoji = {"URA.RU": "🔴", "E1.RU": "🟡", "66.RU": "🔵", "OBLTV.RU": "🟢", "JustMedia": "🟣"}.get(news['source'], "📰")
        text = f"{emoji} <b>{news['title']}</b>\n\n{(news.get('description') or '')[:200]}\n\n📎 <a href=\"{news['link']}\">Читать</a>"
        try:
            if news.get('image_url'):
                await update.message.reply_photo(photo=news['image_url'], caption=text[:1024], parse_mode="HTML")
            else:
                await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=False)
        except Exception as e:
            await update.message.reply_text(text, parse_mode="HTML")

    mark_as_sent([n['id'] for n in news_list[:5]])


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    sources = "\n".join(f"  • {s}: {c}" for s, c in stats['sources'].items())
    text = f"📊 <b>Статистика</b>\n\n📰 Всего: {stats['total']}\n📬 Не отправлено: {stats['unsent']}\n👥 Подписчиков: {stats['subscribers']}\n\n{sources}"
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deactivate_subscriber(update.effective_chat.id)
    await update.message.reply_text("😢 Вы отписаны. /start — подписаться снова.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "latest":
        await cmd_news(update, context)
    elif query.data == "stats":
        await cmd_stats(update, context)
    elif query.data == "unsubscribe":
        deactivate_subscriber(update.effective_chat.id)
        await query.edit_message_text("😢 Вы отписаны. /start — подписаться.")


def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан!")
        sys.exit(1)

    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Планировщик через JobQueue (используем run_repeating с async callback)
    job_queue = app.job_queue
    job_queue.run_repeating(
        hourly_job,
        interval=timedelta(minutes=CHECK_INTERVAL_MINUTES),
        first=10,
    )

    # Первый сбор при запуске
    job_queue.run_once(hourly_job, when=5)

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
