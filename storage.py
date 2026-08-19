import sqlite3
import time
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage.db")

# Кулдаун команды !delegate — 5 часов
DELEGATE_CD_SECONDS = 5 * 60 * 60

# Кулдаун на переотправку мейн-панели в канал после заявки — 15 секунд
PANEL_RESEND_CD_SECONDS = 15


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delegate_cd (
                user_id TEXT PRIMARY KEY,
                last_used REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS main_panels (
                panel_type TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                message_id TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS panel_resend_cd (
                channel_id TEXT PRIMARY KEY,
                last_used REAL NOT NULL
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO counters (name, value) VALUES ('appeal_counter', 0)"
        )
        conn.commit()
    finally:
        conn.close()


_init_db()


def next_appeal_id() -> int:
    conn = _connect()
    try:
        conn.execute("UPDATE counters SET value = value + 1 WHERE name = 'appeal_counter'")
        conn.commit()
        row = conn.execute("SELECT value FROM counters WHERE name = 'appeal_counter'").fetchone()
        return row[0]
    finally:
        conn.close()


def reset_appeal_counter() -> int:
    """Обнуляет счётчик обращений (команда !rnumber). Возвращает значение, которое было до обнуления."""
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM counters WHERE name = 'appeal_counter'").fetchone()
        old_value = row[0] if row else 0
        conn.execute("UPDATE counters SET value = 0 WHERE name = 'appeal_counter'")
        conn.commit()
        return old_value
    finally:
        conn.close()


def check_delegate_cd(user_id) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT last_used FROM delegate_cd WHERE user_id = ?",
            (str(user_id),)
        ).fetchone()
        last = row[0] if row else 0
        return time.time() - last >= DELEGATE_CD_SECONDS
    finally:
        conn.close()


def set_delegate_cd(user_id):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO delegate_cd (user_id, last_used) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_used = excluded.last_used",
            (str(user_id), time.time())
        )
        conn.commit()
    finally:
        conn.close()


# ───────────────────────────────────────────────
# Мейн-панели (роли/отпуск/обращения): где они висят,
# чтобы после рестарта бота не отправлять их заново вручную
# ───────────────────────────────────────────────
def save_panel_location(panel_type: str, channel_id, message_id):
    """Сохраняет/обновляет местоположение мейн-панели (канал + сообщение) по её типу."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO main_panels (panel_type, channel_id, message_id) VALUES (?, ?, ?) "
            "ON CONFLICT(panel_type) DO UPDATE SET "
            "channel_id = excluded.channel_id, message_id = excluded.message_id",
            (panel_type, str(channel_id), str(message_id))
        )
        conn.commit()
    finally:
        conn.close()


def get_panel_location(panel_type: str):
    """Возвращает (channel_id, message_id) для указанного типа панели или None, если не сохранено."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT channel_id, message_id FROM main_panels WHERE panel_type = ?",
            (panel_type,)
        ).fetchone()
        if row:
            return int(row[0]), int(row[1])
        return None
    finally:
        conn.close()


def get_all_panel_locations() -> dict:
    """Возвращает {panel_type: (channel_id, message_id)} для всех сохранённых панелей."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT panel_type, channel_id, message_id FROM main_panels").fetchall()
        return {row[0]: (int(row[1]), int(row[2])) for row in rows}
    finally:
        conn.close()


def check_panel_resend_cd(channel_id) -> bool:
    """True, если с последней переотправки мейн-панели в этот канал прошло >= 15 секунд."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT last_used FROM panel_resend_cd WHERE channel_id = ?",
            (str(channel_id),)
        ).fetchone()
        last = row[0] if row else 0
        return time.time() - last >= PANEL_RESEND_CD_SECONDS
    finally:
        conn.close()


def set_panel_resend_cd(channel_id):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO panel_resend_cd (channel_id, last_used) VALUES (?, ?) "
            "ON CONFLICT(channel_id) DO UPDATE SET last_used = excluded.last_used",
            (str(channel_id), time.time())
        )
        conn.commit()
    finally:
        conn.close()