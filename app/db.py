import os

from .env import load_optional_dotenv

load_optional_dotenv()
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = os.getenv('DB_PATH', 'data/app.db')
MIGRATIONS_DIR = Path('migrations')


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, applied_at TEXT NOT NULL)')
        applied = {row['name'] for row in conn.execute('SELECT name FROM migrations').fetchall()}
        for path in sorted(MIGRATIONS_DIR.glob('*.sql')):
            if path.name in applied:
                continue
            sql = path.read_text(encoding='utf-8')
            conn.executescript(sql)
            conn.execute('INSERT INTO migrations (name, applied_at) VALUES (?, ?)', (path.name, _utc_now()))
        conn.commit()
