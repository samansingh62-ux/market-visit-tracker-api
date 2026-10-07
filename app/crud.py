from datetime import datetime, timezone
from typing import Optional

from . import database
from .auth import verify_password


def lookup_retailer(conn, name: str):
    row = conn.execute("SELECT * FROM retailers WHERE name = %s", (name,)).fetchone()
    return dict(row) if row else None


def lookup_retailer_by_name(name: str):
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM retailers WHERE name = %s", (name,)).fetchone()
        return dict(row) if row else None



def lookup_retailer_by_code(code: str):
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM retailers WHERE UPPER(code) = UPPER(%s)",
            (code.strip(),),
        ).fetchone()
        return dict(row) if row else None


def get_explicit_hierarchy_target(month: str, level: str, name: str) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT month, level, name, target_volume, target_value
            FROM hierarchy_targets
            WHERE month = %s AND UPPER(level) = UPPER(%s) AND name = %s
            """,
            (month, level, name),
        ).fetchone()
    return dict(row) if row else None


def list_explicit_hierarchy_targets(month: str, level: str) -> dict:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT name, target_volume, target_value
            FROM hierarchy_targets
            WHERE month = %s AND UPPER(level) = UPPER(%s)
            """,
            (month, level),
        ).fetchall()
    return {str(r["name"]): dict(r) for r in rows}


def get_hierarchy_target_summary(month: str, tl: Optional[str] = None, ss: Optional[str] = None) -> dict:
    clauses = ["t.month = %s"]
    params = [month]
    if tl:
        clauses.append("r.tl = %s")
        params.append(tl)
    if ss:
        clauses.append("r.ss = %s")
        params.append(ss)
    where = " AND ".join(clauses)
    with database.get_conn() as conn:
        row = conn.execute(f"""
            SELECT
                COALESCE(SUM(t.target_volume), 0) AS target_volume,
                COALESCE(SUM(t.target_value), 0) AS target_value,
                COUNT(DISTINCT t.retailer_code) AS target_retailers
            FROM retailer_targets t
            JOIN retailers r ON UPPER(r.code) = UPPER(t.retailer_code)
            WHERE {where}
        """, params).fetchone()
        retailers = conn.execute(
            f"""SELECT code, name FROM retailers r WHERE {" AND ".join([c.replace("t.month = %s", "1=1") for c in clauses[1:]]) if len(clauses)>1 else "1=1"}""",
            params[1:],
        ).fetchall()
    return {
        "target_volume": int(row["target_volume"] or 0),
        "target_value": int(row["target_value"] or 0),
        "target_retailers": int(row["target_retailers"] or 0),
        "retailer_codes": [str(x["code"]).strip().upper() for x in retailers if x.get("code")],
    }


def get_performance_scope_rows(
    month: str,
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    kam: Optional[str] = None,
) -> list[dict]:
    clauses = ["1=1"]
    params = []
    if tl:
        clauses.append("r.tl = %s")
        params.append(tl)
    if ss:
        clauses.append("r.ss = %s")
        params.append(ss)
    if rds:
        clauses.append("r.rds = %s")
        params.append(rds)
    if kam:
        clauses.append("r.kam = %s")
        params.append(kam)
    where = " AND ".join(clauses)
    with database.get_conn() as conn:
        rows = conn.execute(f"""
            SELECT
                r.code, r.name, r.tl, r.ss, r.rds, r.kam, r.zone, r.club, r.town_name, r.district_name,
                COALESCE(t.target_volume, 0) AS target_volume,
                COALESCE(t.target_value, 0) AS target_value,
                v.last_visit,
                COALESCE(v.visit_count, 0) AS visit_count
            FROM retailers r
            LEFT JOIN retailer_targets t
              ON UPPER(t.retailer_code) = UPPER(r.code) AND t.month = %s
            LEFT JOIN (
                SELECT retailer, MAX(visit_date) AS last_visit, COUNT(*) AS visit_count
                FROM visits
                GROUP BY retailer
            ) v ON v.retailer = r.name
            WHERE {where}
            ORDER BY r.name
        """, [month, *params]).fetchall()
    return [dict(row) for row in rows]


def get_retailer_target(retailer_code: str, month: str) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT month, retailer_code, retailer_name, target_volume, target_value, updated_at
            FROM retailer_targets
            WHERE month = %s AND UPPER(retailer_code) = UPPER(%s)
            """,
            (month, retailer_code.strip()),
        ).fetchone()
        return dict(row) if row else None


def upsert_retailer_targets(month: str, rows: list) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        conn.execute("DELETE FROM retailer_targets WHERE month = %s", (month,))
        for row in rows:
            conn.execute(
                """
                INSERT INTO retailer_targets
                    (month, retailer_code, retailer_name, target_volume, target_value, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (month, retailer_code) DO UPDATE SET
                    retailer_name = EXCLUDED.retailer_name,
                    target_volume = EXCLUDED.target_volume,
                    target_value = EXCLUDED.target_value,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    month,
                    row["retailer_code"],
                    row.get("retailer_name") or "",
                    int(row.get("target_volume") or 0),
                    int(row.get("target_value") or 0),
                    now,
                ),
            )
    return {
        "month": month,
        "retailers": len(rows),
        "target_volume": sum(int(r.get("target_volume") or 0) for r in rows),
        "target_value": sum(int(r.get("target_value") or 0) for r in rows),
    }


def retailer_visit_history(retailer_name: str, limit: int = 5) -> list:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, retailer, market, visit_date, feedback, suggestions,
                   submitted_by, submitted_role, created_at
            FROM visits
            WHERE retailer = %s
            ORDER BY visit_date DESC, created_at DESC
            LIMIT %s
            """,
            (retailer_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def create_visit(payload) -> dict:
    with database.get_conn() as conn:
        info = lookup_retailer(conn, payload.retailer) or {}
        cur = conn.execute("""
            INSERT INTO visits
                (retailer, market, visit_date, feedback, suggestions,
                 submitted_by, submitted_role, tl, ss, rds, created_at, latitude, longitude, gps_accuracy)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            payload.retailer, payload.market, payload.visit_date.isoformat(),
            payload.feedback or "", payload.suggestions or "",
            payload.submitted_by or "Unknown", payload.submitted_role or "Field",
            info.get("tl", ""), info.get("ss", ""), info.get("rds", ""),
            datetime.now(timezone.utc).isoformat(),
            payload.latitude, payload.longitude, payload.gps_accuracy,
        ))
        visit_id = cur.fetchone()["id"]
        row = conn.execute("SELECT * FROM visits WHERE id = %s", (visit_id,)).fetchone()
        return dict(row)


def list_visits(retailer: Optional[str] = None, tl: Optional[str] = None,
                ss: Optional[str] = None, rds: Optional[str] = None, kam: Optional[str] = None,
                submitted_by: Optional[str] = None,
                submitted_role: Optional[str] = None,
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                search: Optional[str] = None, limit: int = 500,
                offset: int = 0) -> list:
    clauses, params = [], []
    for col, value in (("retailer", retailer), ("tl", tl), ("ss", ss), ("rds", rds),
                       ("submitted_by", submitted_by), ("submitted_role", submitted_role)):
        if value:
            clauses.append(f"{col} = %s")
            params.append(value)
    if kam:
        clauses.append("EXISTS (SELECT 1 FROM retailers rk WHERE rk.name = v.retailer AND rk.kam = %s)")
        params.append(kam)
    if date_from:
        clauses.append("visit_date >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("visit_date <= %s")
        params.append(date_to)
    if search:
        clauses.append("(retailer ILIKE %s OR market ILIKE %s OR feedback ILIKE %s OR suggestions ILIKE %s)")
        like = f"%{search}%"
        params.extend([like] * 4)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""SELECT v.*, COUNT(p.id) AS photo_count
                 FROM visits v
                 LEFT JOIN visit_photos p ON p.visit_id = v.id
                 {where}
                 GROUP BY v.id
                 ORDER BY v.visit_date DESC, v.created_at DESC
                 LIMIT %s OFFSET %s"""
    params.extend([limit, offset])
    with database.get_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_visit(visit_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM visits WHERE id = %s", (visit_id,)).fetchone()
        return dict(row) if row else None


def delete_visit(visit_id: int) -> bool:
    with database.get_conn() as conn:
        return conn.execute("DELETE FROM visits WHERE id = %s", (visit_id,)).rowcount > 0


def list_retailers(tl: Optional[str] = None, ss: Optional[str] = None,
                   rds: Optional[str] = None, kam: Optional[str] = None, search: Optional[str] = None) -> list:
    clauses, params = [], []
    for col, value in (("tl", tl), ("ss", ss), ("rds", rds), ("kam", kam)):
        if value:
            clauses.append(f"{col} = %s")
            params.append(value)
    if search:
        clauses.append("name ILIKE %s")
        params.append(f"%{search}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with database.get_conn() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM retailers {where} ORDER BY name", params).fetchall()]


def list_users_admin() -> list:
    with database.get_conn() as conn:
        rows = conn.execute("""
            SELECT
                u.id,
                u.name,
                u.role,
                u.tl,
                u.ss,
                u.rds,
                u.kam,
                u.username,
                u.active,
                u.whatsapp_number,
                COUNT(r.code) AS assigned_retailers
            FROM users u
            LEFT JOIN retailers r
                ON (
                    (u.role = 'TL' AND r.tl = u.name)
                    OR
                    (u.role = 'SS' AND r.ss = u.name)
                    OR
                    (u.role = 'RDS' AND r.rds = u.name)
                    OR
                    (u.role = 'KAM' AND r.kam = u.name)
                )
            GROUP BY
                u.id,
                u.name,
                u.role,
                u.tl,
                u.ss,
                u.rds,
                u.kam,
                u.username,
                u.active,
                u.whatsapp_number
            ORDER BY u.role, u.name
        """).fetchall()

        return [dict(row) for row in rows]


def update_user_whatsapp_number(user_id: int, whatsapp_number: Optional[str]) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            UPDATE users
            SET whatsapp_number = %s
            WHERE id = %s
            RETURNING id, name, role, username, whatsapp_number, active
            """,
            (whatsapp_number or None, user_id),
        ).fetchone()
        return dict(row) if row else None


def get_user_admin(user_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, name, role, tl, ss, rds, kam, username, whatsapp_number, active
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def create_whatsapp_notification_log(user_id: int, preview_text: str, status: str = "PREVIEWED", provider_message_id: Optional[str] = None, error_detail: Optional[str] = None) -> Optional[dict]:
    from datetime import datetime, timezone
    with database.get_conn() as conn:
        user = conn.execute(
            "SELECT id, name, role, whatsapp_number FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not user:
            return None
        row = conn.execute(
            """
            INSERT INTO whatsapp_notification_log
                (user_id, recipient_name, recipient_role, whatsapp_number, preview_text, status, provider_message_id, error_detail, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, user_id, recipient_name, recipient_role, whatsapp_number, preview_text, status, provider_message_id, error_detail, created_at
            """,
            (
                user["id"], user["name"], user["role"], user["whatsapp_number"],
                preview_text, status, provider_message_id, error_detail, datetime.now(timezone.utc).isoformat(),
            ),
        ).fetchone()
        return dict(row)


def list_whatsapp_notification_logs(limit: int = 50) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, recipient_name, recipient_role, whatsapp_number,
                   preview_text, status, provider_message_id, error_detail, created_at
            FROM whatsapp_notification_log
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def reset_user_password(user_id: int) -> Optional[dict]:
    import secrets
    from .auth import hash_password

    password = secrets.token_urlsafe(9)

    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, name, role, username
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        ).fetchone()

        if not row:
            return None

        conn.execute(
            """
            UPDATE users
            SET password_hash = %s,
                active = TRUE
            WHERE id = %s
            """,
            (hash_password(password), user_id),
        )

        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "username": row["username"],
            "temporary_password": password,
        }


def set_user_status(user_id: int, active: bool) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            UPDATE users
            SET active = %s
            WHERE id = %s
            RETURNING id, name, role, username, active
            """,
            (active, user_id),
        ).fetchone()

        return dict(row) if row else None


def get_stats(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None, kam: Optional[str] = None) -> dict:
    with database.get_conn() as conn:
        retailer_clauses, retailer_params = [], []
        for col, value in (("tl", tl), ("ss", ss), ("rds", rds), ("kam", kam)):
            if value:
                retailer_clauses.append(f"r.{col} = %s")
                retailer_params.append(value)
        retailer_where = f"WHERE {' AND '.join(retailer_clauses)}" if retailer_clauses else ""

        visit_clauses, visit_params = [], []
        for col, value in (("tl", tl), ("ss", ss), ("rds", rds)):
            if value:
                visit_clauses.append(f"v.{col} = %s")
                visit_params.append(value)
        if kam:
            visit_clauses.append("EXISTS (SELECT 1 FROM retailers rk WHERE rk.name = v.retailer AND rk.kam = %s)")
            visit_params.append(kam)
        visit_where = f"WHERE {' AND '.join(visit_clauses)}" if visit_clauses else ""

        return {
            "total_visits": conn.execute(f"SELECT COUNT(*) AS c FROM visits v {visit_where}", visit_params).fetchone()["c"],
            "unique_retailers_visited": conn.execute(f"SELECT COUNT(DISTINCT v.retailer) AS c FROM visits v {visit_where}", visit_params).fetchone()["c"],
            "unique_markets": conn.execute(f"SELECT COUNT(DISTINCT v.market) AS c FROM visits v {visit_where}", visit_params).fetchone()["c"],
            "total_retailers_in_master": conn.execute(f"SELECT COUNT(*) AS c FROM retailers r {retailer_where}", retailer_params).fetchone()["c"],
        }

def get_coverage(group_by: str, kam: Optional[str] = None) -> list:
    if group_by not in ("tl", "ss", "rds"):
        raise ValueError("group_by must be one of: tl, ss, rds")
    with database.get_conn() as conn:
        scope_sql = " AND kam = %s" if kam else ""
        scope_params = [kam] if kam else []
        assigned_rows = conn.execute(
            f"SELECT {group_by} AS grp, COUNT(*) AS assigned FROM retailers WHERE {group_by} IS NOT NULL AND {group_by} != ''{scope_sql} GROUP BY {group_by}",
            scope_params,
        ).fetchall()
        result = []
        for row in assigned_rows:
            grp, assigned = row["grp"], row["assigned"]
            visited_params = [grp]
            visited_scope = ""
            if kam:
                visited_scope = " AND r.kam = %s"
                visited_params.append(kam)
            visited = conn.execute(
                f"SELECT COUNT(DISTINCT v.retailer) AS c FROM visits v JOIN retailers r ON r.name = v.retailer WHERE r.{group_by} = %s{visited_scope}",
                visited_params,
            ).fetchone()["c"]
            total_visits = conn.execute(
                f"SELECT COUNT(*) AS c FROM visits v JOIN retailers r ON r.name = v.retailer WHERE r.{group_by} = %s{visited_scope}",
                visited_params,
            ).fetchone()["c"]
            result.append({"name": grp, "assigned": assigned, "visited": visited,
                           "coverage_pct": round((visited / assigned) * 100, 1) if assigned else 0.0,
                           "total_visits": total_visits})
        return sorted(result, key=lambda r: r["name"])

def get_retailer_health(tl: Optional[str] = None, ss: Optional[str] = None,
                        rds: Optional[str] = None, kam: Optional[str] = None, zone: Optional[str] = None,
                        priority: Optional[str] = None, limit: int = 500) -> list:
    clauses, params = [], []
    for col, value in (("tl", tl), ("ss", ss), ("rds", rds), ("kam", kam), ("zone", zone)):
        if value:
            clauses.append(f"r.{col} = %s")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT r.code, r.name, r.tl, r.ss, r.rds, r.kam, r.zone, r.club, r.status,
               COUNT(v.id) AS visit_count,
               MAX(v.visit_date) AS last_visit,
               CASE WHEN MAX(v.visit_date) IS NULL THEN NULL
                    ELSE CURRENT_DATE - MAX(v.visit_date)::date END AS days_since_visit
        FROM retailers r
        LEFT JOIN visits v ON v.retailer = r.name
        {where}
        GROUP BY r.code, r.name, r.tl, r.ss, r.rds, r.kam, r.zone, r.club, r.status
        ORDER BY CASE WHEN MAX(v.visit_date) IS NULL THEN 0 ELSE 1 END,
                 MAX(v.visit_date) ASC NULLS FIRST, r.name
        LIMIT %s
    """
    params.append(limit)
    with database.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    for row in rows:
        d = row["days_since_visit"]
        if d is None:
            row["priority"] = "Never Visited"
        elif d >= 15:
            row["priority"] = "Overdue 15+ Days"
        elif d >= 8:
            row["priority"] = "Due 8–14 Days"
        else:
            row["priority"] = "Recently Visited"
    if priority:
        rows = [r for r in rows if r["priority"] == priority]
    return rows


def get_user_by_username(username: str) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(%s) AND active = TRUE",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None


def provision_user_credentials() -> list:
    """Generate temporary passwords for users without credentials."""
    import secrets
    from .auth import hash_password

    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, role, username FROM users WHERE active = TRUE AND (password_hash IS NULL OR password_hash = '') ORDER BY role, name"
        ).fetchall()
        result = []
        for row in rows:
            password = secrets.token_urlsafe(9)
            conn.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(password), row["id"]),
            )
            result.append({"name": row["name"], "role": row["role"], "username": row["username"], "temporary_password": password})
        return result


def add_visit_photo(visit_id: int, filename: str, mime_type: str, data: bytes) -> dict:
    with database.get_conn() as conn:
        row = conn.execute("""
            INSERT INTO visit_photos (visit_id, filename, mime_type, data, size_bytes, created_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id, visit_id, filename, mime_type, size_bytes, created_at
        """, (visit_id, filename, mime_type, data, len(data), datetime.now(timezone.utc).isoformat())).fetchone()
        return dict(row)


def list_visit_photos(visit_id: int) -> list:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, visit_id, filename, mime_type, size_bytes, created_at FROM visit_photos WHERE visit_id = %s ORDER BY id",
            (visit_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_visit_photo(photo_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM visit_photos WHERE id = %s", (photo_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_name_role(name: str, role: str) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(name) = LOWER(%s) AND role = %s AND active = TRUE",
            (name.strip(), role),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_pin(pin: str) -> Optional[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE active = TRUE AND role IN ('TL','SS','KAM','RDS') AND pin_hash IS NOT NULL"
        ).fetchall()
        matches = []
        for row in rows:
            user = dict(row)
            if verify_password(pin, user["pin_hash"]):
                matches.append(user)
        if len(matches) == 1:
            return matches[0]
        return None


def upsert_daily_retailer_remark(
    remark_date: str,
    retailer_code: str,
    retailer_name: str,
    submitted_by: str,
    submitted_role: str,
    remark: str,
) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO daily_retailer_remarks
                (remark_date, retailer_code, retailer_name, submitted_by, submitted_role, remark, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (remark_date, retailer_code, submitted_by, submitted_role)
            DO UPDATE SET remark = EXCLUDED.remark, updated_at = EXCLUDED.updated_at
            RETURNING id, remark_date, retailer_code, retailer_name, submitted_by, submitted_role, remark, created_at, updated_at
            """,
            (
                remark_date,
                retailer_code,
                retailer_name,
                submitted_by,
                submitted_role,
                remark,
                now,
                now,
            ),
        ).fetchone()
        return dict(row)


def list_daily_retailer_remarks(
    remark_date: str,
    submitted_by: Optional[str] = None,
    submitted_role: Optional[str] = None,
) -> list[dict]:
    clauses = ["remark_date = %s"]
    params = [remark_date]
    if submitted_by:
        clauses.append("submitted_by = %s")
        params.append(submitted_by)
    if submitted_role:
        clauses.append("submitted_role = %s")
        params.append(submitted_role)
    where = " AND ".join(clauses)
    with database.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, remark_date, retailer_code, retailer_name, submitted_by,
                   submitted_role, remark, created_at, updated_at
            FROM daily_retailer_remarks
            WHERE {where}
            ORDER BY retailer_name
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_kam_whatsapp_recipients(kam_name: str, role: Optional[str] = None) -> list[dict]:
    clauses = ["u.active = TRUE", "u.role IN ('TL','SS')"]
    role_params = []
    if role in ("TL", "SS"):
        clauses.append("u.role = %s")
        role_params.append(role)
    where = " AND ".join(clauses)
    with database.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                u.id,
                u.name,
                u.role,
                u.whatsapp_number,
                u.active,
                CASE
                    WHEN u.role = 'TL' THEN (
                        SELECT COUNT(*) FROM retailers r
                        WHERE r.kam = %s AND r.tl = u.name
                    )
                    WHEN u.role = 'SS' THEN (
                        SELECT COUNT(*) FROM retailers r
                        WHERE r.kam = %s AND r.ss = u.name
                    )
                    ELSE 0
                END AS assigned_retailers
            FROM users u
            WHERE {where}
              AND (
                    (u.role = 'TL' AND EXISTS (
                        SELECT 1 FROM retailers r1
                        WHERE r1.kam = %s AND r1.tl = u.name
                    ))
                    OR
                    (u.role = 'SS' AND EXISTS (
                        SELECT 1 FROM retailers r2
                        WHERE r2.kam = %s AND r2.ss = u.name
                    ))
              )
            ORDER BY u.role, u.name
            """,
            [kam_name, kam_name, *role_params, kam_name, kam_name],
        ).fetchall()
        return [dict(row) for row in rows]


def kam_can_message_user(kam_name: str, user_id: int) -> bool:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM users u
            WHERE u.id = %s
              AND u.active = TRUE
              AND u.role IN ('TL','SS')
              AND (
                    (u.role = 'TL' AND EXISTS (
                        SELECT 1 FROM retailers r
                        WHERE r.kam = %s AND r.tl = u.name
                    ))
                    OR
                    (u.role = 'SS' AND EXISTS (
                        SELECT 1 FROM retailers r
                        WHERE r.kam = %s AND r.ss = u.name
                    ))
              )
            LIMIT 1
            """,
            (user_id, kam_name, kam_name),
        ).fetchone()
        return row is not None


def list_kam_area_users(kam_name: str) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                u.id,
                u.name,
                u.role,
                u.tl,
                u.ss,
                u.rds,
                u.kam,
                u.username,
                u.active,
                u.whatsapp_number,
                CASE
                    WHEN u.role = 'TL' THEN (
                        SELECT COUNT(*) FROM retailers r
                        WHERE r.kam = %s AND r.tl = u.name
                    )
                    WHEN u.role = 'SS' THEN (
                        SELECT COUNT(*) FROM retailers r
                        WHERE r.kam = %s AND r.ss = u.name
                    )
                    WHEN u.role = 'RDS' THEN (
                        SELECT COUNT(*) FROM retailers r
                        WHERE r.kam = %s AND r.rds = u.name
                    )
                    ELSE 0
                END AS assigned_retailers
            FROM users u
            WHERE u.role IN ('TL','SS','RDS')
              AND (
                    (u.role = 'TL' AND EXISTS (
                        SELECT 1 FROM retailers r1
                        WHERE r1.kam = %s AND r1.tl = u.name
                    ))
                    OR
                    (u.role = 'SS' AND EXISTS (
                        SELECT 1 FROM retailers r2
                        WHERE r2.kam = %s AND r2.ss = u.name
                    ))
                    OR
                    (u.role = 'RDS' AND EXISTS (
                        SELECT 1 FROM retailers r3
                        WHERE r3.kam = %s AND r3.rds = u.name
                    ))
              )
            ORDER BY u.role, u.name
            """,
            (kam_name, kam_name, kam_name, kam_name, kam_name, kam_name),
        ).fetchall()
        return [dict(row) for row in rows]


def kam_can_manage_user(kam_name: str, user_id: int) -> bool:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM users u
            WHERE u.id = %s
              AND u.role IN ('TL','SS','RDS')
              AND (
                    (u.role = 'TL' AND EXISTS (
                        SELECT 1 FROM retailers r
                        WHERE r.kam = %s AND r.tl = u.name
                    ))
                    OR
                    (u.role = 'SS' AND EXISTS (
                        SELECT 1 FROM retailers r
                        WHERE r.kam = %s AND r.ss = u.name
                    ))
                    OR
                    (u.role = 'RDS' AND EXISTS (
                        SELECT 1 FROM retailers r
                        WHERE r.kam = %s AND r.rds = u.name
                    ))
              )
            LIMIT 1
            """,
            (user_id, kam_name, kam_name, kam_name),
        ).fetchone()
        return row is not None


def get_whatsapp_broadcast_config() -> dict:
    with database.get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, enabled, send_hour, send_minute, audience, updated_at
            FROM whatsapp_broadcast_config
            WHERE id = 1
            """
        ).fetchone()
        return dict(row) if row else {
            "id": 1,
            "enabled": True,
            "send_hour": 19,
            "send_minute": 0,
            "audience": "TL",
            "updated_at": None,
        }


def update_whatsapp_broadcast_config(
    enabled: bool,
    send_hour: int,
    send_minute: int,
    audience: str = "TL",
) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO whatsapp_broadcast_config
                (id, enabled, send_hour, send_minute, audience, updated_at)
            VALUES (1, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                send_hour = EXCLUDED.send_hour,
                send_minute = EXCLUDED.send_minute,
                audience = EXCLUDED.audience,
                updated_at = EXCLUDED.updated_at
            RETURNING id, enabled, send_hour, send_minute, audience, updated_at
            """,
            (bool(enabled), int(send_hour), int(send_minute), str(audience), now),
        ).fetchone()
        return dict(row)


def list_active_users_by_role(role: str) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, role, tl, ss, rds, kam, username, whatsapp_number, active
            FROM users
            WHERE active = TRUE AND role = %s
            ORDER BY name
            """,
            (role,),
        ).fetchall()
        return [dict(row) for row in rows]


def claim_whatsapp_broadcast_run(
    run_key: str,
    run_date: str,
    scope_key: str,
    audience: str,
    trigger: str,
) -> Optional[dict]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO whatsapp_broadcast_runs
                (run_key, run_date, scope_key, audience, trigger, started_at, status)
            VALUES (%s,%s,%s,%s,%s,%s,'RUNNING')
            ON CONFLICT (run_key) DO NOTHING
            RETURNING *
            """,
            (run_key, run_date, scope_key, audience, trigger, now),
        ).fetchone()
        return dict(row) if row else None


def finish_whatsapp_broadcast_run(
    run_id: int,
    status: str,
    total_recipients: int,
    submitted: int,
    skipped_no_number: int,
    skipped_no_data: int,
    failed: int,
    detail: Optional[str] = None,
) -> Optional[dict]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        row = conn.execute(
            """
            UPDATE whatsapp_broadcast_runs
            SET finished_at = %s,
                status = %s,
                total_recipients = %s,
                submitted = %s,
                skipped_no_number = %s,
                skipped_no_data = %s,
                failed = %s,
                detail = %s
            WHERE id = %s
            RETURNING *
            """,
            (
                now,
                status,
                int(total_recipients),
                int(submitted),
                int(skipped_no_number),
                int(skipped_no_data),
                int(failed),
                detail,
                run_id,
            ),
        ).fetchone()
        return dict(row) if row else None


def get_whatsapp_broadcast_run(run_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM whatsapp_broadcast_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None


def list_whatsapp_broadcast_runs(limit: int = 20) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM whatsapp_broadcast_runs
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_management_eod_remarks(date_from: str, date_to: str) -> list[dict]:
    """All saved TL/SS remarks in the inclusive reporting period."""
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.remark_date, d.submitted_by, d.submitted_role,
                   d.retailer_code, d.retailer_name, d.remark,
                   r.tl, r.ss, r.rds, d.created_at, d.updated_at
            FROM daily_retailer_remarks d
            LEFT JOIN retailers r ON r.code = d.retailer_code
            WHERE d.remark_date >= %s AND d.remark_date <= %s
              AND d.submitted_role IN ('TL', 'SS')
            ORDER BY d.remark_date, d.submitted_role, d.submitted_by,
                     d.retailer_name, d.retailer_code
            """,
            (date_from, date_to),
        ).fetchall()
        return [dict(row) for row in rows]


def create_missing_rds_pins() -> list[dict]:
    """Provision only missing RDS PINs; return plaintext once to the admin."""
    import secrets
    from .auth import hash_password
    created = []
    with database.get_conn() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(724091)")
        users = [dict(row) for row in conn.execute(
            "SELECT id, name, username, role, pin_hash FROM users "
            "WHERE active = TRUE AND role IN ('TL','SS','KAM','RDS') FOR UPDATE"
        ).fetchall()]
        hashes = [u["pin_hash"] for u in users if u.get("pin_hash")]
        issued = set()
        for user in users:
            if user["role"] != "RDS" or user.get("pin_hash"):
                continue
            for _ in range(1000):
                pin = str(secrets.randbelow(9000) + 1000)
                if pin in issued or any(verify_password(pin, saved) for saved in hashes):
                    continue
                break
            else:
                raise RuntimeError("Unable to allocate a unique PIN.")
            conn.execute("UPDATE users SET pin_hash = %s WHERE id = %s",
                         (hash_password(pin), user["id"]))
            issued.add(pin)
            created.append({"name": user["name"], "username": user["username"], "pin": pin})
    return created
