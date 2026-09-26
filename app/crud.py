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
                ss: Optional[str] = None, rds: Optional[str] = None,
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
                   rds: Optional[str] = None, search: Optional[str] = None) -> list:
    clauses, params = [], []
    for col, value in (("tl", tl), ("ss", ss), ("rds", rds)):
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
                u.username,
                u.active,
                COUNT(r.code) AS assigned_retailers
            FROM users u
            LEFT JOIN retailers r
                ON (
                    (u.role = 'TL' AND r.tl = u.name)
                    OR
                    (u.role = 'SS' AND r.ss = u.name)
                    OR
                    (u.role = 'RDS' AND r.rds = u.name)
                )
            GROUP BY
                u.id,
                u.name,
                u.role,
                u.tl,
                u.ss,
                u.rds,
                u.username,
                u.active
            ORDER BY u.role, u.name
        """).fetchall()

        return [dict(row) for row in rows]


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


def get_stats(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None) -> dict:
    with database.get_conn() as conn:
        clauses, params = [], []
        for col, value in (("tl", tl), ("ss", ss), ("rds", rds)):
            if value:
                clauses.append(f"{col} = %s"); params.append(value)
        vwhere = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return {
            "total_visits": conn.execute(f"SELECT COUNT(*) AS c FROM visits {vwhere}", params).fetchone()["c"],
            "unique_retailers_visited": conn.execute(f"SELECT COUNT(DISTINCT retailer) AS c FROM visits {vwhere}", params).fetchone()["c"],
            "unique_markets": conn.execute(f"SELECT COUNT(DISTINCT market) AS c FROM visits {vwhere}", params).fetchone()["c"],
            "total_retailers_in_master": conn.execute(f"SELECT COUNT(*) AS c FROM retailers {vwhere}", params).fetchone()["c"],
        }


def get_coverage(group_by: str) -> list:
    if group_by not in ("tl", "ss", "rds"):
        raise ValueError("group_by must be one of: tl, ss, rds")
    with database.get_conn() as conn:
        assigned_rows = conn.execute(
            f"SELECT {group_by} AS grp, COUNT(*) AS assigned FROM retailers WHERE {group_by} IS NOT NULL AND {group_by} != '' GROUP BY {group_by}"
        ).fetchall()
        result = []
        for row in assigned_rows:
            grp, assigned = row["grp"], row["assigned"]
            visited = conn.execute(
                f"SELECT COUNT(DISTINCT v.retailer) AS c FROM visits v JOIN retailers r ON r.name = v.retailer WHERE r.{group_by} = %s", (grp,)
            ).fetchone()["c"]
            total_visits = conn.execute(f"SELECT COUNT(*) AS c FROM visits WHERE {group_by} = %s", (grp,)).fetchone()["c"]
            result.append({"name": grp, "assigned": assigned, "visited": visited,
                           "coverage_pct": round((visited / assigned) * 100, 1) if assigned else 0.0,
                           "total_visits": total_visits})
        return sorted(result, key=lambda r: r["name"])


def get_retailer_health(tl: Optional[str] = None, ss: Optional[str] = None,
                        rds: Optional[str] = None, zone: Optional[str] = None,
                        priority: Optional[str] = None, limit: int = 500) -> list:
    clauses, params = [], []
    for col, value in (("tl", tl), ("ss", ss), ("rds", rds), ("zone", zone)):
        if value:
            clauses.append(f"r.{col} = %s")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT r.code, r.name, r.tl, r.ss, r.rds, r.zone, r.club, r.status,
               COUNT(v.id) AS visit_count,
               MAX(v.visit_date) AS last_visit,
               CASE WHEN MAX(v.visit_date) IS NULL THEN NULL
                    ELSE CURRENT_DATE - MAX(v.visit_date)::date END AS days_since_visit
        FROM retailers r
        LEFT JOIN visits v ON v.retailer = r.name
        {where}
        GROUP BY r.code, r.name, r.tl, r.ss, r.rds, r.zone, r.club, r.status
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
            "SELECT * FROM users WHERE active = TRUE AND role IN ('TL','SS') AND pin_hash IS NOT NULL"
        ).fetchall()
        matches = []
        for row in rows:
            user = dict(row)
            if verify_password(pin, user["pin_hash"]):
                matches.append(user)
        if len(matches) == 1:
            return matches[0]
        return None
