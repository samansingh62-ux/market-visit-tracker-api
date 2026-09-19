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
                submitted_role TEXT,
                tl TEXT,
                ss TEXT,
                rds TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("ALTER TABLE visits ADD COLUMN IF NOT EXISTS submitted_role TEXT")
        conn.execute("UPDATE visits SET submitted_role = 'Field' WHERE submitted_role IS NULL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                tl TEXT,
                ss TEXT,
                rds TEXT,
                username TEXT UNIQUE,
                password_hash TEXT,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                UNIQUE(name, role)
            )
        """)
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        for column in ("retailer", "tl", "ss", "rds", "visit_date"):
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_visits_{column} ON visits({column})")

        count = conn.execute("SELECT COUNT(*) AS c FROM retailers").fetchone()["c"]
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

        # User identity/hierarchy master. Credentials are only populated by admin provisioning.
        rows = conn.execute("""
            SELECT DISTINCT tl AS name, 'TL' AS role, tl, NULL AS ss, NULL AS rds
            FROM retailers WHERE tl IS NOT NULL AND tl != ''
            UNION
            SELECT DISTINCT ss AS name, 'SS' AS role, NULL AS tl, ss, NULL AS rds
            FROM retailers WHERE ss IS NOT NULL AND ss != ''
            UNION
            SELECT DISTINCT rds AS name, 'RDS' AS role, NULL AS tl, NULL AS ss, rds
            FROM retailers WHERE rds IS NOT NULL AND rds != ''
        """).fetchall()
        for row in rows:
            base = "".join(ch.lower() if ch.isalnum() else "." for ch in row["name"]).strip(".")
            row["username"] = f"{base}.{row['role'].lower()}"
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO users (name, role, tl, ss, rds, username)
                VALUES (%(name)s, %(role)s, %(tl)s, %(ss)s, %(rds)s, %(username)s)
                ON CONFLICT (name, role) DO UPDATE SET
                    tl = EXCLUDED.tl,
                    ss = EXCLUDED.ss,
                    rds = EXCLUDED.rds,
                    username = COALESCE(users.username, EXCLUDED.username),
                    active = TRUE
            """, rows)
