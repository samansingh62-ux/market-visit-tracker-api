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
        # Store-level split of a multi-store retailer's target (when the target file gives one).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_targets (
                month TEXT NOT NULL,
                store_code TEXT NOT NULL,
                retailer_code TEXT NOT NULL,
                target_volume INTEGER NOT NULL DEFAULT 0,
                target_value BIGINT NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (month, store_code)
            )
        """)

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

        _seed_monthly_targets(conn)
        _apply_hierarchy_target_updates(conn)

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

        # Competitor sales and activity, entered by the field team per retailer.
        # One row per brand per submission; the latest row for a retailer/brand/month is current.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS competition_entries (
                id BIGSERIAL PRIMARY KEY,
                month TEXT NOT NULL,
                retailer_code TEXT NOT NULL,
                retailer_name TEXT NOT NULL,
                brand TEXT NOT NULL,
                mtd_units INTEGER,
                promoters INTEGER,
                demo_units INTEGER,
                branding BOOLEAN,
                offer TEXT,
                offer_amount INTEGER,
                launch_model TEXT,
                launch_price INTEGER,
                notes TEXT,
                submitted_by TEXT NOT NULL,
                submitted_role TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_competition_month_retailer ON competition_entries(month, retailer_code, brand, created_at)")

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

        apply_alignment(conn)

        # User identity/hierarchy master. Credentials are only populated by admin provisioning.
        rows = conn.execute("""
            SELECT DISTINCT tl AS name, 'TL' AS role, tl, NULL AS ss, NULL AS rds
            FROM store_alignment WHERE tl IS NOT NULL AND tl != '' AND tl != 'SS Direct (NPO)'
            UNION
            SELECT DISTINCT ss AS name, 'SS' AS role, NULL AS tl, ss, NULL AS rds
            FROM store_alignment WHERE ss IS NOT NULL AND ss != ''
            UNION
            SELECT DISTINCT rds AS name, 'RDS' AS role, NULL AS tl, NULL AS ss, rds
            FROM store_alignment WHERE rds IS NOT NULL AND rds != ''
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
    "Pappu Kumar":["SS","Nhh8DP47r1a0KCumRwj0Hw==$Lsx6aEoot4E2Il4Oe4tSjlqfDml_kkdRAyEfJTWOZ1o="],
    "Prasenjit Deb":["SS","Q3pMJ83rzMFauffjcZOfBA==$pjDlBctHzCgKnN3lZ3yN1gwp0ariurK7x6tAqoS1M80="],
    "Sujit Sinha":["SS","JURxLIVUYoadE8r2w-MujQ==$9nTtfGf2t-8pTZnca4T3ryhBW8YS0geX7i7K8JEUpjk="],
    "Avisek Das":["SS","1xd6-yy0SrAIGV0f_17bJA==$YiYSVDG6UWzxQde_7j5xX1Qh1pNNBFRC_YWoUqCJhSg="],
    "Subir Kumar Sinha":["SS","Z_ILa7UCgutbkkJqRVQh7Q==$_um0RK6Km5bFziz56EcBd-jd2geCdbOylJtXv3v7Ur4="],
    "Abhishek Pradhan":["TL","NW1uZyc01YnwrvtsjaBssQ==$XiuEF44RezzONUVVuhwDapgG8sdTQuFhbR0w1xsuTNI="],
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

        # Zone-wide admin login with full change access; hash only in ADMIN_PIN_HASH.
        admin_pin_hash = os.getenv("ADMIN_PIN_HASH", "").strip()
        if admin_pin_hash:
            conn.execute("""
                INSERT INTO users (name, role, username, pin_hash, active)
                VALUES (%s, 'ADMIN', 'admin', %s, TRUE)
                ON CONFLICT (name, role) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, active = TRUE
            """, (os.getenv("ADMIN_NAME", "Saman").strip() or "Saman", admin_pin_hash))

        # More full-access admins: ADMIN_USERS_JSON = [{"name": ..., "username": ..., "pin_hash": ...}].
        try:
            extra_admins = json.loads(os.getenv("ADMIN_USERS_JSON", "") or "[]")
        except Exception:
            extra_admins = []
        for adm in extra_admins if isinstance(extra_admins, list) else []:
            if not isinstance(adm, dict) or not adm.get("name") or not adm.get("pin_hash") or not adm.get("username"):
                continue
            conn.execute("""
                INSERT INTO users (name, role, username, pin_hash, active)
                VALUES (%s, 'ADMIN', %s, %s, TRUE)
                ON CONFLICT (name, role) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, active = TRUE
            """, (str(adm["name"]).strip(), str(adm["username"]).strip(), str(adm["pin_hash"]).strip()))

        # Zone-wide view-only logins (no admin): VIEWER_USERS_JSON = [{"name", "username", "pin_hash"}].
        try:
            viewers = json.loads(os.getenv("VIEWER_USERS_JSON", "") or "[]")
        except Exception:
            viewers = []
        for v in viewers if isinstance(viewers, list) else []:
            if not isinstance(v, dict) or not v.get("name") or not v.get("pin_hash") or not v.get("username"):
                continue
            conn.execute("""
                INSERT INTO users (name, role, username, pin_hash, active)
                VALUES (%s, 'VIEWER', %s, %s, TRUE)
                ON CONFLICT (name, role) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, active = TRUE
            """, (str(v["name"]).strip(), str(v["username"]).strip(), str(v["pin_hash"]).strip()))

        # Zone-wide CEO login. The PIN hash lives only in the CEO_PIN_HASH environment variable.
        ceo_pin_hash = os.getenv("CEO_PIN_HASH", "").strip()
        if ceo_pin_hash:
            conn.execute("""
                INSERT INTO users (name, role, username, pin_hash, active)
                VALUES (%s, 'CEO', 'ceo', %s, TRUE)
                ON CONFLICT (name, role) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, active = TRUE
            """, (os.getenv("CEO_NAME", "Evan").strip() or "Evan", ceo_pin_hash))

        # Apply the explicit SS-to-TL role correction without losing credentials or history.
        conn.execute("""
            UPDATE users AS tl_user
            SET pin_hash = COALESCE(ss_user.pin_hash, tl_user.pin_hash),
                password_hash = COALESCE(ss_user.password_hash, tl_user.password_hash),
                whatsapp_number = COALESCE(NULLIF(ss_user.whatsapp_number, ''), tl_user.whatsapp_number),
                tl = 'Abhishek Pradhan', ss = NULL, active = TRUE
            FROM users AS ss_user
            WHERE tl_user.name = 'Abhishek Pradhan' AND tl_user.role = 'TL'
              AND ss_user.name = tl_user.name AND ss_user.role = 'SS' AND ss_user.active = TRUE
        """)
        conn.execute("""
            UPDATE users SET active = FALSE
            WHERE name = 'Abhishek Pradhan' AND role = 'SS'
        """)

        # People removed from the system: login off, PIN cleared, history kept.
        for name, role in REMOVED_USERS:
            conn.execute("UPDATE users SET active = FALSE, pin_hash = NULL WHERE name = %s AND role = %s", (name, role))


# Removed from Zone A (name, role). "SS Direct (NPO)" is the alignment's label for NPO outlets with no
# TL, not a person.
REMOVED_USERS = [
    ("Rahul Sharma", "TL"),       # removed 13 Nov 2026 (Saman)
    ("SS Direct (NPO)", "TL"),
]


# Target files re-issued after the month was seeded: month -> stamp of the corrected file.
TARGET_FILE_RELOADS = {
    "2026-11": "2026-11-12 11:45:00+00",  # Tertiary dashboard till 11 Nov: new stores, Manipur targets
}


def _seed_monthly_targets(conn):
    """Seed retailer_targets_YYYY-MM.json, store_targets_YYYY-MM.json and hierarchy_targets_YYYY-MM.json
    for months from Nov 2026 on, only when that month has nothing yet (a later upload is kept)."""
    import re
    for path in sorted(APP_DIR.glob("retailer_targets_*.json")):
        m = re.search(r"(\d{4}-\d{2})", path.name)
        if not m or m.group(1) < "2026-11":
            continue
        month = m.group(1)
        latest = conn.execute("SELECT COUNT(*) AS c, MAX(updated_at) AS u FROM retailer_targets WHERE month = %s", (month,)).fetchone()
        reload_stamp = TARGET_FILE_RELOADS.get(month)
        if int(latest["c"] or 0):
            # A corrected target file replaces the month only while nothing newer was uploaded.
            if not reload_stamp or str(latest["u"] or "") >= reload_stamp:
                continue
            conn.execute("DELETE FROM retailer_targets WHERE month = %s", (month,))
        rows = json.load(open(path, "r", encoding="utf-8"))
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO retailer_targets (month, retailer_code, retailer_name, target_volume, target_value, updated_at)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s::text, CURRENT_TIMESTAMP::text))
                ON CONFLICT (month, retailer_code) DO NOTHING
            """, [(month, str(r[0]).strip().upper(), (r[3] if len(r) > 3 else "") or "", int(r[1] or 0), int(r[2] or 0), reload_stamp)
                  for r in rows if isinstance(r, list) and len(r) >= 3 and r[0]])
        store_path = APP_DIR / f"store_targets_{month}.json"
        if store_path.exists():
            conn.execute("DELETE FROM store_targets WHERE month = %s", (month,))
            stores = json.load(open(store_path, "r", encoding="utf-8"))
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO store_targets (month, store_code, retailer_code, target_volume, target_value, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP::text)
                    ON CONFLICT (month, store_code) DO NOTHING
                """, [(month, str(r[0]).strip().upper(), str(r[1]).strip().upper(), int(r[2] or 0), int(r[3] or 0))
                      for r in stores if isinstance(r, list) and len(r) >= 4 and r[0]])
        hier_path = APP_DIR / f"hierarchy_targets_{month}.json"
        if hier_path.exists() and not int(conn.execute(
                "SELECT COUNT(*) AS c FROM hierarchy_targets WHERE month = %s", (month,)).fetchone()["c"] or 0):
            hier = json.load(open(hier_path, "r", encoding="utf-8"))
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO hierarchy_targets (month, level, name, target_volume, target_value, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP::text)
                    ON CONFLICT (month, level, name) DO NOTHING
                """, [(month, str(r[0]).upper(), str(r[1]).strip(), int(r[2] or 0), int(r[3] or 0))
                      for r in hier if isinstance(r, list) and len(r) >= 4 and r[1]])


def _apply_hierarchy_target_updates(conn):
    """Apply one-off TL/SS/RDS/zone target changes from hierarchy_target_updates.json.
    Each entry is [month, level, name, volume, value, stamp]; it is written only while the
    stored row is older than its stamp, so a later upload or edit is never overwritten."""
    path = APP_DIR / "hierarchy_target_updates.json"
    if not path.exists():
        return
    for month, level, name, vol, val, stamp in json.load(open(path, "r", encoding="utf-8")):
        conn.execute("""
            INSERT INTO hierarchy_targets (month, level, name, target_volume, target_value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (month, level, name) DO UPDATE
            SET target_volume = EXCLUDED.target_volume, target_value = EXCLUDED.target_value,
                updated_at = EXCLUDED.updated_at
            WHERE hierarchy_targets.updated_at < EXCLUDED.updated_at
        """, (month, str(level).upper(), name, int(vol), int(val), stamp))


def chain_store_name(store_name):
    """'Reliance Retail Jio- Itanagar (Store)' -> 'Reliance Retail Jio- Itanagar'."""
    name = str(store_name or "").strip()
    name = name[:-len("(Store)")].strip() if name.endswith("(Store)") else name
    if name.startswith("Infiniti Retail Limited"):  # Croma's legal name
        name = "Croma" + name[len("Infiniti Retail Limited"):]
    return name


def apply_alignment(conn):
    """Transactional master update, retaining store grain and every shared assignment."""
    from .alignment import alignment, canonical_name
    conn.execute("""
        CREATE TABLE IF NOT EXISTS store_alignment (
            store_code TEXT PRIMARY KEY, store_name TEXT NOT NULL,
            retailer_code TEXT NOT NULL, retailer_name TEXT NOT NULL,
            kam TEXT NOT NULL, ss TEXT NOT NULL, tl TEXT NOT NULL, rds TEXT NOT NULL,
            ss_id TEXT, tl_id TEXT, source_month TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_store_alignment_retailer ON store_alignment(retailer_code)")
    conn.execute("ALTER TABLE store_alignment ADD COLUMN IF NOT EXISTS unit_code TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_store_alignment_unit ON store_alignment(unit_code)")
    conn.execute("CREATE TABLE IF NOT EXISTS alignment_retailer_backup_20261008 AS SELECT * FROM retailers")
    conn.execute("DELETE FROM store_alignment")
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO store_alignment
            (store_code, store_name, retailer_code, retailer_name, kam, ss, tl, rds, ss_id, tl_id, source_month, unit_code)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'2026-11',%s)
        """, [(r["store_code"], r["store_name"], r["retailer_code"], r["retailer_name"],
               canonical_name(r["kam"]), canonical_name(r["ss"]), canonical_name(r["tl"]),
               canonical_name(r["rds"]), r["ss_id"], r["tl_id"], alignment.unit_code(r)) for r in alignment.rows])
        cur.executemany("""
            INSERT INTO retailers (code,name,tl,ss,rds,kam,zone,club,status,town_name,district_name)
            VALUES (%s,%s,%s,%s,%s,%s,'Zone A',%s,'Active',%s,%s)
            ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, tl=EXCLUDED.tl, ss=EXCLUDED.ss,
                rds=EXCLUDED.rds, kam=EXCLUDED.kam, club=EXCLUDED.club,
                status='Active', town_name=EXCLUDED.town_name, district_name=EXCLUDED.district_name
        """, [(code, rows[0]["retailer_name"], canonical_name(rows[0]["tl"]),
               canonical_name(rows[0]["ss"]), canonical_name(rows[0]["rds"]),
               canonical_name(rows[0]["kam"]), rows[0]["club"] or "",
               rows[0]["town_name"] or "", rows[0]["district_name"] or "")
              for code, rows in alignment.retailers.items() if code not in alignment.chains])
        # Each chain store is listed on its own, named as the store.
        chain_units = []
        for code in sorted(alignment.chains):
            for r in alignment.retailers[code]:
                name = chain_store_name(r["store_name"])
                chain_units.append((str(r["store_code"]).strip().upper(), name, canonical_name(r["tl"]),
                                    canonical_name(r["ss"]), canonical_name(r["rds"]), canonical_name(r["kam"]),
                                    r["club"] or "", r["town_name"] or "", r["district_name"] or ""))
        cur.executemany("""
            INSERT INTO retailers (code,name,tl,ss,rds,kam,zone,club,status,town_name,district_name)
            VALUES (%s,%s,%s,%s,%s,%s,'Zone A',%s,'Active',%s,%s)
            ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, tl=EXCLUDED.tl, ss=EXCLUDED.ss,
                rds=EXCLUDED.rds, kam=EXCLUDED.kam, club=EXCLUDED.club,
                status='Active', town_name=EXCLUDED.town_name, district_name=EXCLUDED.district_name
        """, chain_units)
    conn.execute("UPDATE retailers SET status='Outside current alignment' WHERE code NOT IN (SELECT unit_code FROM store_alignment)")
    # Targets are uploaded per retailer. A multi-store retailer's target goes to its stores as the
    # target file splits it (store_targets) or, without a split, equally (remainder to the first stores).
    conn.execute("DROP VIEW IF EXISTS unit_targets")
    conn.execute("""
        CREATE VIEW unit_targets AS
        WITH units AS (SELECT DISTINCT UPPER(retailer_code) AS retailer_code, unit_code FROM store_alignment),
        n AS (
            SELECT retailer_code, unit_code,
                   COUNT(*) OVER (PARTITION BY retailer_code) AS cnt,
                   ROW_NUMBER() OVER (PARTITION BY retailer_code ORDER BY unit_code) AS rn
            FROM units
        ),
        split AS (SELECT DISTINCT month, retailer_code FROM store_targets)
        SELECT t.month, n.unit_code, t.retailer_code, t.retailer_name, t.updated_at,
               CASE WHEN sp.retailer_code IS NOT NULL AND n.cnt > 1 THEN COALESCE(s.target_volume, 0)
                    ELSE (t.target_volume / n.cnt + CASE WHEN n.rn <= t.target_volume % n.cnt THEN 1 ELSE 0 END) END::INTEGER AS target_volume,
               CASE WHEN sp.retailer_code IS NOT NULL AND n.cnt > 1 THEN COALESCE(s.target_value, 0)
                    ELSE (t.target_value / n.cnt + CASE WHEN n.rn <= t.target_value % n.cnt THEN 1 ELSE 0 END) END::BIGINT AS target_value
        FROM retailer_targets t
        JOIN n ON n.retailer_code = UPPER(t.retailer_code)
        LEFT JOIN split sp ON sp.month = t.month AND sp.retailer_code = n.retailer_code
        LEFT JOIN store_targets s ON s.month = t.month AND s.store_code = n.unit_code
    """)
