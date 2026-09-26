import json
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

APP_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL")
RETAILERS_SEED_PATH = APP_DIR / "retailers_seed.json"
RETAILER_TARGETS_SEP26_PATH = APP_DIR / "retailer_targets_2026-09.json"

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
                created_at TEXT NOT NULL,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                gps_accuracy DOUBLE PRECISION
            )
        """)
        conn.execute("ALTER TABLE visits ADD COLUMN IF NOT EXISTS submitted_role TEXT")
        conn.execute("ALTER TABLE visits ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
        conn.execute("ALTER TABLE visits ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
        conn.execute("ALTER TABLE visits ADD COLUMN IF NOT EXISTS gps_accuracy DOUBLE PRECISION")
        conn.execute("UPDATE visits SET submitted_role = 'Field' WHERE submitted_role IS NULL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS visit_photos (
                id BIGSERIAL PRIMARY KEY,
                visit_id BIGINT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                data BYTEA NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visit_photos_visit_id ON visit_photos(visit_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS retailer_targets (
                month TEXT NOT NULL,
                retailer_code TEXT NOT NULL,
                retailer_name TEXT,
                target_volume INTEGER NOT NULL DEFAULT 0,
                target_value BIGINT NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (month, retailer_code)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_retailer_targets_month ON retailer_targets(month)")

        # September 2026 targets supplied by management. Seed only when that month
        # has not already been imported, so a later manager upload is preserved.
        seed_month = "2026-09"
        target_count = conn.execute(
            "SELECT COUNT(*) AS c FROM retailer_targets WHERE month = %s",
            (seed_month,),
        ).fetchone()["c"]
        if target_count == 0 and RETAILER_TARGETS_SEP26_PATH.exists():
            with open(RETAILER_TARGETS_SEP26_PATH, "r", encoding="utf-8") as f:
                target_seed = json.load(f)
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO retailer_targets
                        (month, retailer_code, retailer_name, target_volume, target_value, updated_at)
                    VALUES
                        (%s, %s,
                         COALESCE((SELECT name FROM retailers WHERE UPPER(code) = UPPER(%s)), ''),
                         %s, %s, CURRENT_TIMESTAMP::text)
                    ON CONFLICT (month, retailer_code) DO NOTHING
                """, [
                    (seed_month, row[0], row[0], int(row[1] or 0), int(row[2] or 0))
                    for row in target_seed
                    if isinstance(row, list) and len(row) >= 3 and row[0]
                ])

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
                pin_hash TEXT,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                UNIQUE(name, role)
            )
        """)
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pin_hash TEXT")
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

        # Zone A TL/SS PINs. Only PBKDF2 hashes are stored in the application.
        pin_seeds = {
    "V. Lalbiakdika":["TL","xYMtXqly1hZzsi62HVHcVg==$tNX3Ov9-m86C92YXDWo60t7ZN-U60JplsSvPWATXwrc="],
    "Lalthuammawia":["TL","Ealu8QCoT4YqwDIpncuZNw==$yeNS_f_BRB-l2XsSzX8W6E7BoBQQ9ydzn1By_Ot-k9k="],
    "R.Zodinthara":["TL","MOyWG8ocyIMiEnXFjL0w_Q==$CWY8eFaBNjdodUsUV_vKCyoNo3-De_a9aLgGLn5zHHo="],
    "Polash Roy":["TL","23NA9zoDfmhQI8TCf4Iqwg==$CRSRxn3psYNB95-t798BogNfKhdHCAEfePate8_UAKc="],
    "Robert Zoramthara":["TL","ToDpOm9UVGJ5KAB4EocLFg==$BQO3nFMWwjrhexnmq9XEZ0aNbem79Gl5yDWTnRIq2yE="],
    "Manidipta Bhattacharjee":["TL","vTaqOK0GeCe7VDqFR4_Teg==$OeAYs6_KZXwXm4tZLZUkY0ok6jBymmUPjR_QHEQnpWE="],
    "Bichitra Saharia":["TL","tEE0bRHNFd_QZhIsqGkJaw==$ohSeU-vMmJOAmEIG1uWEnKSeYzarLLy-GoUpDhJE1IQ="],
    "Ajay Rai":["TL","-hAeJo_vDqXc7sxdRXFb1A==$h5vJ_M8-pPeUrWExUln6n84YvS85c8zcHubiMJYUokY="],
    "Rajesh Deb":["TL","23C9c4emfAPpOJ5Wrt6OyQ==$nUbxhsqP-o-TTHQH_pDh0qCreTpKMUjPt5PCD2wgFbU="],
    "Subhashish Dasgupta":["TL","hqPj7PIgM3AXlCrq9XL5oQ==$BxoguAad_ZqUO_V6pnZmp-fa14M13eLYQ08hid6GMgg="],
    "Monojit Rudra Paul":["TL","OFNtpwCarW88gAwkaDcmTg==$sRmTOYko_bkagh0ALNfLk0f8raBwz8n68VoBKjOhfCQ="],
    "Debabrata Dey":["TL","FGv_3f2wuXv2cxai4zL3Kg==$yjARIl_VwmnTvAQzKTj9Ti4aM03F-At9OXjooROHq8s="],
    "Ratan Chandra Dey":["TL","QdF-_Xdfyki6IO_vIrbCLw==$29eoUN0lLWyL3VMj9WI2zXu1zIf2wU7G2C1X2fD8KTM="],
    "A K Mehbub A Laskar":["TL","gAghLKh6gr73Hc_dM8OYLw==$ncrE4FOIuKZQq360XIg7kftrdpfRZCM6YQngOxc05-E="],
    "Krishna Bhowmick":["TL","wHgMY5-duTP7M0diycrUcQ==$D9UVjEHD3ZABteO5wUF8a96kpDhYL7oPj-rt0nYPp44="],
    "Sachin Gurung":["TL","RllXiDYVFHUwSZ_eD_5LEw==$t2WKJYqO40pW0vitZQR4Gdik_znw6KujXny_XeWALCs="],
    "Suman Dey":["TL","x7uWIAbojoZ-8gZ1t4r6dw==$AXLDAmQWOvf8dYkuIayiQk95SL5O0wcrHgZJbKQ1q7g="],
    "Bappan Das":["TL","Ec1gRwifZLr2u9LeZBpYnw==$BjHEd0BRs1qe4Dy5FVcFSOx5f7xUajKktdwXRFHi6cI="],
    "Stallon Ningthoujam":["TL","pEEhvP5hFg_oN9WNzxSvPg==$sDjy4OHKMF013UmhyjY87aEXJWKCqLhruoiJY1BogbA="],
    "Gobindo Mandal":["TL","bOrLBp-OSSztdT1s2Pka2w==$9Ng9UI5VHTI0Fdju-TSBvQagv1Hj5d1zWa2-gGRrbUU="],
    "Bishnu Suklabaidya":["TL","GAON5Z9w2bBp-AqbQgqW6A==$XkB2TuyXmy4xBVzuNlGl0BBx1Nij2U_ZnWyH-9z48t4="],
    "Saurav Dey":["TL","McOlJAsswXEpYBwhRIq1GA==$ekkHe02cDM93lwF1-FF6HW6XJeeQ3QPN2VKAKVc5qgw="],
    "Rahul Sharma":["TL","pEJeirf8eHoudqQzLJrbmw==$6fX-5XRcL1k065nAyA1HAg7GdM6SoXWE3A5_4dwL8Pk="],
    "Pappu Kumar":["SS","Nhh8DP47r1a0KCumRwj0Hw==$Lsx6aEoot4E2Il4Oe4tSjlqfDml_kkdRAyEfJTWOZ1o="],
    "Prasenjit Deb":["SS","Q3pMJ83rzMFauffjcZOfBA==$pjDlBctHzCgKnN3lZ3yN1gwp0ariurK7x6tAqoS1M80="],
    "Sujit Sinha":["SS","JURxLIVUYoadE8r2w-MujQ==$9nTtfGf2t-8pTZnca4T3ryhBW8YS0geX7i7K8JEUpjk="],
    "Avisek Das":["SS","1xd6-yy0SrAIGV0f_17bJA==$YiYSVDG6UWzxQde_7j5xX1Qh1pNNBFRC_YWoUqCJhSg="],
    "Subir Kumar Sinha":["SS","Z_ILa7UCgutbkkJqRVQh7Q==$_um0RK6Km5bFziz56EcBd-jd2geCdbOylJtXv3v7Ur4="],
    "Abhishek Pradhan":["SS","NW1uZyc01YnwrvtsjaBssQ==$XiuEF44RezzONUVVuhwDapgG8sdTQuFhbR0w1xsuTNI="],
    "Sougaijam Kennedy":["SS","0TcY1e6Gtb-OzMU8w0UJVw==$IkIRGttNrfqo2F6VI3NKqyYmGluJX8Be5ycIFroaCpw="],
    "Naba Jyoti Bora":["SS","bcWRloNfPssMjzlc4j0lUQ==$bdgdEcrBpep644jNcw_8eVZP4JUlm3dwUMGD-bSLPoA="],
    "Vacant-Zone A":["SS","oryim6X9mWzzbQU5pvoJ2w==$MoNp3nQEmF8j1fnaJDkNKUzIeGMOcDiJW6yzvARP_XY="]
}
        for name, (role, pin_hash) in pin_seeds.items():
            conn.execute("UPDATE users SET pin_hash = %s WHERE name = %s AND role = %s", (pin_hash, name, role))

