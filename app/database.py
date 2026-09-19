import json
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

APP_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL")
RETAILERS_SEED_PATH = APP_DIR / "retailers_seed.json"

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


@contextmanager
def get_conn():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
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
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id BIGSERIAL PRIMARY KEY,
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
        """)

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_retailer "
            "ON visits(retailer)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_tl "
            "ON visits(tl)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_ss "
            "ON visits(ss)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_rds "
            "ON visits(rds)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_visits_date "
            "ON visits(visit_date)"
        )

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM retailers"
        ).fetchone()["c"]

        if count == 0 and RETAILERS_SEED_PATH.exists():
            with open(RETAILERS_SEED_PATH, "r", encoding="utf-8") as f:
                seed = json.load(f)

            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO retailers
                        (code, name, tl, ss, rds, zone, club, status)
                    VALUES
                        (%(code)s, %(name)s, %(tl)s, %(ss)s, %(rds)s,
                         %(zone)s, %(club)s, %(status)s)
                    ON CONFLICT (code) DO NOTHING
                """, seed)
