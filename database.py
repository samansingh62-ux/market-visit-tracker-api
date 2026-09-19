"""
SQLite database layer for the Market Visit Tracker API.

Uses the standard library's sqlite3 module directly (no ORM) to keep
dependencies minimal. The database file path is configurable via the
DB_PATH environment variable and defaults to ./data/market_visits.db.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DB_PATH", str(APP_DIR.parent / "data" / "market_visits.db"))
RETAILERS_SEED_PATH = APP_DIR / "retailers_seed.json"


def _ensure_data_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn():
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist, and seed retailers on first run."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS retailers (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                tl TEXT,
                ss TEXT,
                rds TEXT,
                zone TEXT,
                club TEXT,
                status TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                retailer TEXT NOT NULL,
                market TEXT,
                visit_date TEXT NOT NULL,
                feedback TEXT,
                suggestions TEXT,
                submitted_by TEXT,
                tl TEXT,
                ss TEXT,
                rds TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_retailer ON visits(retailer)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_tl ON visits(tl)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_ss ON visits(ss)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_rds ON visits(rds)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(visit_date)")

        count = conn.execute("SELECT COUNT(*) AS c FROM retailers").fetchone()["c"]
        if count == 0 and RETAILERS_SEED_PATH.exists():
            with open(RETAILERS_SEED_PATH, "r", encoding="utf-8") as f:
                seed = json.load(f)
            conn.executemany(
                """
                INSERT OR IGNORE INTO retailers (code, name, tl, ss, rds, zone, club, status)
                VALUES (:code, :name, :tl, :ss, :rds, :zone, :club, :status)
                """,
                seed,
            )
