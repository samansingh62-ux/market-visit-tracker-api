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
RETAILER_TARGETS_OCT26_PATH = APP_DIR / "retailer_targets_2026-10.json"
HIERARCHY_TARGETS_OCT26_PATH = APP_DIR / "hierarchy_targets_2026-10.json"
TL_CONTACTS_OCT26_PATH = APP_DIR / "tl_contacts_2026-10.json"
RETAILER_LOCATION_SEED_GLOB = "retailer_locations_*.json"

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

        conn.execute("ALTER TABLE retailers ADD COLUMN IF NOT EXISTS town_name TEXT")
        conn.execute("ALTER TABLE retailers ADD COLUMN IF NOT EXISTS district_name TEXT")
        conn.execute("ALTER TABLE retailers ADD COLUMN IF NOT EXISTS kam TEXT")

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS hierarchy_targets (
                month TEXT NOT NULL,
                level TEXT NOT NULL,
                name TEXT NOT NULL,
                target_volume INTEGER NOT NULL DEFAULT 0,
                target_value BIGINT NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (month, level, name)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hierarchy_targets_month ON hierarchy_targets(month)")

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

        oct_seed_month = "2026-10"
        oct_target_count = conn.execute(
            "SELECT COUNT(*) AS c FROM retailer_targets WHERE month = %s",
            (oct_seed_month,),
        ).fetchone()["c"]
        if oct_target_count == 0 and RETAILER_TARGETS_OCT26_PATH.exists():
            with open(RETAILER_TARGETS_OCT26_PATH, "r", encoding="utf-8") as f:
                oct_seed = json.load(f)
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
                    (oct_seed_month, row[0], row[0], int(row[1] or 0), int(row[2] or 0))
                    for row in oct_seed
                    if isinstance(row, list) and len(row) >= 3 and row[0]
                ])

        hierarchy_target_count = conn.execute(
            "SELECT COUNT(*) AS c FROM hierarchy_targets WHERE month = %s",
            (oct_seed_month,),
        ).fetchone()["c"]
        if hierarchy_target_count == 0 and HIERARCHY_TARGETS_OCT26_PATH.exists():
            with open(HIERARCHY_TARGETS_OCT26_PATH, "r", encoding="utf-8") as f:
                hierarchy_seed = json.load(f)
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO hierarchy_targets
                        (month, level, name, target_volume, target_value, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP::text)
                    ON CONFLICT (month, level, name) DO NOTHING
                """, [
                    (oct_seed_month, str(row[0]).upper(), str(row[1]).strip(), int(row[2] or 0), int(row[3] or 0))
                    for row in hierarchy_seed
                    if isinstance(row, list) and len(row) >= 4 and row[1]
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
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_number TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS kam TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_notification_log (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                recipient_name TEXT NOT NULL,
                recipient_role TEXT NOT NULL,
                whatsapp_number TEXT,
                preview_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PREVIEWED',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("ALTER TABLE whatsapp_notification_log ADD COLUMN IF NOT EXISTS provider_message_id TEXT")
        conn.execute("ALTER TABLE whatsapp_notification_log ADD COLUMN IF NOT EXISTS error_detail TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_log_created_at ON whatsapp_notification_log(created_at)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_broadcast_config (
                id SMALLINT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                send_hour INTEGER NOT NULL DEFAULT 19,
                send_minute INTEGER NOT NULL DEFAULT 0,
                audience TEXT NOT NULL DEFAULT 'TL',
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO whatsapp_broadcast_config
                (id, enabled, send_hour, send_minute, audience, updated_at)
            VALUES (1, TRUE, 19, 0, 'TL', CURRENT_TIMESTAMP::text)
            ON CONFLICT (id) DO NOTHING
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_broadcast_runs (
                id BIGSERIAL PRIMARY KEY,
                run_key TEXT NOT NULL UNIQUE,
                run_date TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                audience TEXT NOT NULL,
                trigger TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                total_recipients INTEGER NOT NULL DEFAULT 0,
                submitted INTEGER NOT NULL DEFAULT 0,
                skipped_no_number INTEGER NOT NULL DEFAULT 0,
                skipped_no_data INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                detail TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_broadcast_runs_started ON whatsapp_broadcast_runs(started_at)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_retailer_remarks (
                id BIGSERIAL PRIMARY KEY,
                remark_date TEXT NOT NULL,
                retailer_code TEXT NOT NULL,
                retailer_name TEXT NOT NULL,
                submitted_by TEXT NOT NULL,
                submitted_role TEXT NOT NULL,
                remark TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(remark_date, retailer_code, submitted_by, submitted_role)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_remarks_date ON daily_retailer_remarks(remark_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_remarks_retailer ON daily_retailer_remarks(retailer_code)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS kam_rds_assignments (
                kam_name TEXT NOT NULL,
                rds TEXT NOT NULL,
                PRIMARY KEY (kam_name, rds)
            )
        """)

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

        # Apply retailer town/district seed from the September 2026 alignment master.
        # Only matching retailer codes are updated; unmatched retailers remain blank until
        # a newer alignment master provides their location.
        location_rows = []
        for path in sorted(APP_DIR.glob(RETAILER_LOCATION_SEED_GLOB)):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    rows_in_file = json.load(f)
                for row in rows_in_file:
                    if isinstance(row, list) and len(row) >= 3 and row[0]:
                        location_rows.append({
                            "code": str(row[0]).strip().upper(),
                            "town_name": str(row[1] or "").strip(),
                            "district_name": str(row[2] or "").strip(),
                        })
            except Exception:
                continue

        if location_rows:
            with conn.cursor() as cur:
                cur.executemany("""
                    UPDATE retailers
                    SET town_name = %(town_name)s,
                        district_name = %(district_name)s
                    WHERE UPPER(code) = UPPER(%(code)s)
                """, location_rows)

        kam_assignment_seed = [
            ("Biswajit Bania", "Channel Infomatic"),
            ("Prasanta Roy", "Net To Net"),
            ("Prasanta Roy", "M/s Laxmi Stores"),
            ("Prasanta Roy", "Himalayan Agencies"),
            ("Sailen Das", "Rainbow Traders"),
            ("Sailen Das", "Star Telecom"),
            ("Sailen Das", "Amplified Communications Private Limited"),
            ("Sailen Das", "Digital Infotech"),
            ("Ireshwad Mehdi", "K M Enterprise (NHIN)"),
            ("Ireshwad Mehdi", "M/S Ete Hi Choice"),
            ("Ireshwad Mehdi", "Jyoti Cycle Stores and Agency (Zone A)"),
            ("Ireshwad Mehdi", "Star Telecom(West Kameng)"),
        ]
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO kam_rds_assignments (kam_name, rds)
                VALUES (%s, %s)
                ON CONFLICT (kam_name, rds) DO NOTHING
                """,
                kam_assignment_seed,
            )

        conn.execute("""
            UPDATE retailers r
            SET kam = k.kam_name
            FROM kam_rds_assignments k
            WHERE r.rds = k.rds
              AND (r.kam IS DISTINCT FROM k.kam_name)
        """)

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

        # Seed TL WhatsApp contacts supplied by management.
        if TL_CONTACTS_OCT26_PATH.exists():
            try:
                with open(TL_CONTACTS_OCT26_PATH, "r", encoding="utf-8") as f:
                    contact_seed = json.load(f)
                with conn.cursor() as cur:
                    cur.executemany("""
                        UPDATE users
                        SET whatsapp_number = COALESCE(NULLIF(whatsapp_number, ''), %(number)s)
                        WHERE role = 'TL' AND name = %(name)s
                    """, [
                        {"name": str(row[0]).strip(), "number": str(row[1]).strip()}
                        for row in contact_seed
                        if isinstance(row, list) and len(row) >= 2 and row[0] and row[1]
                    ])
            except Exception:
                pass

        kam_users = [
            ("Biswajit Bania", "KAM", "biswajit.bania.kam", "Biswajit Bania", "a5kE8tNPPFwwalYqQDWa2w==$7qnKylwxhJkN0A2vp0tfIz-jVTLV92AKRYtoCb56dPk="),
            ("Prasanta Roy", "KAM", "prasanta.roy.kam", "Prasanta Roy", "SpLLUQD-bPfoEg8cK25JgA==$vc9o2V_gBT7Rx8od9czJoqLAzH9r8_MFvresylgL6Tg="),
            ("Sailen Das", "KAM", "sailen.das.kam", "Sailen Das", "8QdVpI1GbBXb-1GwZOP3Sg==$tlYyHs4UZgSE_KoMHvn5aVvL6KRdCT_SLB1J9mEk67E="),
            ("Ireshwad Mehdi", "KAM", "ireshwad.mehdi.kam", "Ireshwad Mehdi", "2T3Z8Q7Yyzv7cG1Dz4hK5Q==$gyF6qBBxe15n2q4p80Fk1u_zBtyblMwWOfiraJEZCfQ="),
        ]
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO users (name, role, username, kam, password_hash)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (name, role) DO UPDATE SET
                    username = COALESCE(users.username, EXCLUDED.username),
                    kam = EXCLUDED.kam,
                    password_hash = COALESCE(users.password_hash, EXCLUDED.password_hash),
                    active = TRUE
            """, kam_users)

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
    "Vacant-Zone A":["SS","oryim6X9mWzzbQU5pvoJ2w==$MoNp3nQEmF8j1fnaJDkNKUzIeGMOcDiJW6yzvARP_XY="],
    "Biswajit Bania":["KAM","CxWt8jy0PKA-8OQKCW7YJQ==$NeqA5CzpLUMPwX8y44XcCeN-BrF72ZsesyRgSqCPlqY="],
    "Prasanta Roy":["KAM","c2FiRDC0B5IVu1ISIF6BDA==$qgNgY20QMmAKTquXZqEDhsfh6c2hLYiC-hKp8_VXItQ="],
    "Sailen Das":["KAM","bGMXwMxGTNxyqyZhZTqPAQ==$FUdAc6Ua1iJ0Aqm8cy3287nWJoY62sCuU0ACUd8160Y="],
    "Ireshwad Mehdi":["KAM","oq67gtLF6jwPH6me3cRSzQ==$vyV7Y9VMcrxYyU7fIBHX1uEchG00ryXWRqd_VEtNWmg="]
}
        for name, (role, pin_hash) in pin_seeds.items():
            conn.execute("UPDATE users SET pin_hash = %s WHERE name = %s AND role = %s", (pin_hash, name, role))

