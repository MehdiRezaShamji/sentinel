import os
import sqlite3

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "sentinel.db"))

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            task TEXT,
            exposure_minutes INTEGER,
            buddy_id TEXT,
            status TEXT,
            latitude REAL,
            longitude REAL
        )
    """)
    conn.commit()

    # Migration: add telegram_chat_id column if it doesn't exist yet
    cursor.execute("PRAGMA table_info(workers)")
    columns = [row[1] for row in cursor.fetchall()]
    if "telegram_chat_id" not in columns:
        cursor.execute("ALTER TABLE workers ADD COLUMN telegram_chat_id TEXT")
        conn.commit()
    
    # Check if empty
    cursor.execute("SELECT COUNT(*) FROM workers")
    if cursor.fetchone()[0] == 0:
        # Default workers data matching BASE_WORKERS
        workers_data = [
            ("W001", "Alex", "+15550000001", "Road maintenance", 60, "W002", "working", 40.7128, -74.0060),
            ("W002", "Jordan", "+15550000002", "Equipment inspection", 30, "W001", "working", 40.7128, -74.0060),
            ("W003", "Sam", "+15550000003", "Heavy road work", 60, "W001", "working", 40.7128, -74.0060)
        ]
        cursor.executemany("""
            INSERT INTO workers (id, name, phone, task, exposure_minutes, buddy_id, status, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, workers_data)
        conn.commit()
    conn.close()

def load_workers_from_db() -> list[dict]:
    # Make sure DB is initialized
    init_db()
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers")
    rows = cursor.fetchall()
    conn.close()
    
    workers = []
    for r in rows:
        workers.append({
            "id": r["id"],
            "name": r["name"],
            "phone": r["phone"],
            "telegram_chat_id": r["telegram_chat_id"] if r["telegram_chat_id"] else None,
            "task": r["task"],
            "exposure_minutes": r["exposure_minutes"],
            "buddy_id": r["buddy_id"],
            "status": r["status"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "check_in_status": None,
            "check_in_sent_at": None,
            "buddy_verification_status": None,
            "buddy_notified_at": None
        })
    return workers

def update_worker_phone(worker_id: str, new_phone: str):
    """Legacy — updates the phone column (should not be used for Telegram chat IDs)."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE workers SET phone = ? WHERE id = ?", (new_phone, worker_id))
    conn.commit()
    conn.close()

def update_worker_telegram_chat_id(worker_id: str, chat_id: str):
    """Persist the discovered Telegram chat ID for a worker, separate from their phone number."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE workers SET telegram_chat_id = ? WHERE id = ?", (chat_id, worker_id))
    conn.commit()
    conn.close()

