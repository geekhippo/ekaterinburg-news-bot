import sqlite3
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "news.db"


def get_db():
    """Получить соединение с БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализация базы данных"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            source TEXT NOT NULL,
            hash TEXT UNIQUE NOT NULL,
            is_hot INTEGER DEFAULT 0,
            is_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_news_hash ON news(hash);
        CREATE INDEX IF NOT EXISTS idx_news_sent ON news(is_sent);
        CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at);

        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE NOT NULL,
            username TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def make_hash(title: str, link: str) -> str:
    """Создать хеш новости для дедупликации"""
    # Нормализуем заголовок: убриаем пунктуацию и лишние пробелы
    import re
    normalized = re.sub(r'[^\w\s]', '', title.strip().lower())
    normalized = re.sub(r'\s+', ' ', normalized)
    text = f"{normalized}|{link.strip()}"
    return hashlib.md5(text.encode()).hexdigest()


def add_news(title: str, link: str, description: str = "",
             image_url: str = "", source: str = "") -> bool:
    """
    Добавить новость в БД.
    Возвращает True если новость новая, False если дубликат.
    """
    h = make_hash(title, link)
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO news (title, link, description, image_url, source, hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, link, description, image_url, source, h)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def find_similar_news(title: str, hours: int = 24) -> list:
    """
    Найти похожие новости за последние N часов.
    Использует простое сравнение по ключевым словам.
    """
    conn = get_db()
    cutoff = datetime.now() - timedelta(hours=hours)
    rows = conn.execute(
        "SELECT * FROM news WHERE created_at > ? ORDER BY created_at DESC",
        (cutoff.isoformat(),)
    ).fetchall()
    conn.close()

    # Простая проверка на пересечение ключевых слов
    import re
    title_words = set(re.findall(r'\w+', title.lower()))
    similar = []
    for row in rows:
        row_words = set(re.findall(r'\w+', row['title'].lower()))
        if not row_words:
            continue
        overlap = len(title_words & row_words) / max(len(row_words), 1)
        if overlap > 0.5:  # Более 50% совпадения слов
            similar.append(dict(row))
    return similar


def get_unsent_news(limit: int = 20) -> list:
    """Получить неотправленные новости"""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM news WHERE is_sent = 0 ORDER BY created_at DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_as_sent(news_ids: list):
    """Пометить новости как отправленные"""
    if not news_ids:
        return
    conn = get_db()
    placeholders = ','.join('?' * len(news_ids))
    conn.execute(
        f"""UPDATE news SET is_sent = 1, sent_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})""",
        news_ids
    )
    conn.commit()
    conn.close()


def get_active_subscribers() -> list:
    """Получить активных подписчиков"""
    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id FROM subscribers WHERE is_active = 1"
    ).fetchall()
    conn.close()
    return [row['chat_id'] for row in rows]


def add_subscriber(chat_id: int, username: str = ""):
    """Добавить подписчика"""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO subscribers (chat_id, username) VALUES (?, ?)""",
        (chat_id, username)
    )
    conn.commit()
    conn.close()


def deactivate_subscriber(chat_id: int):
    """Деактивировать подписчика"""
    conn = get_db()
    conn.execute(
        "UPDATE subscribers SET is_active = 0 WHERE chat_id = ?",
        (chat_id,)
    )
    conn.commit()
    conn.close()


def cleanup_old_news(days: int = 7):
    """Удалить старые новости"""
    conn = get_db()
    cutoff = datetime.now() - timedelta(days=days)
    conn.execute(
        "DELETE FROM news WHERE created_at < ?",
        (cutoff.isoformat(),)
    )
    conn.commit()
    conn.close()


def get_stats() -> dict:
    """Получить статистику"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM news").fetchone()['c']
    unsent = conn.execute("SELECT COUNT(*) as c FROM news WHERE is_sent = 0").fetchone()['c']
    subscribers = conn.execute("SELECT COUNT(*) as c FROM subscribers WHERE is_active = 1").fetchone()['c']
    sources = conn.execute(
        "SELECT source, COUNT(*) as c FROM news GROUP BY source ORDER BY c DESC"
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "unsent": unsent,
        "subscribers": subscribers,
        "sources": {row['source']: row['c'] for row in sources}
    }


if __name__ == "__main__":
    init_db()
    print("Database initialized!")
    print(f"Stats: {get_stats()}")
