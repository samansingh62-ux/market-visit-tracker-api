from datetime import datetime, timezone
from typing import Optional

from . import database


def lookup_retailer(conn, name: str):
    row = conn.execute(
        "SELECT * FROM retailers WHERE name = %s", (name,)
    ).fetchone()
    return dict(row) if row else None


def create_visit(payload) -> dict:
    with database.get_conn() as conn:
        info = lookup_retailer(conn, payload.retailer) or {}
        cur = conn.execute("""
            INSERT INTO visits
                (retailer, market, visit_date, feedback, suggestions,
                 submitted_by, tl, ss, rds, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            payload.retailer, payload.market, payload.visit_date.isoformat(),
            payload.feedback or "", payload.suggestions or "",
            payload.submitted_by or "Unknown", info.get("tl", ""),
            info.get("ss", ""), info.get("rds", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        visit_id = cur.fetchone()["id"]
        row = conn.execute(
            "SELECT * FROM visits WHERE id = %s", (visit_id,)
        ).fetchone()
        return dict(row)


def list_visits(retailer: Optional[str] = None, tl: Optional[str] = None,
                ss: Optional[str] = None, rds: Optional[str] = None,
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                search: Optional[str] = None, limit: int = 500,
                offset: int = 0) -> list:
    clauses, params = [], []
    for col, value in (("retailer", retailer), ("tl", tl), ("ss", ss), ("rds", rds)):
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
        clauses.append("(retailer LIKE %s OR market LIKE %s OR feedback LIKE %s OR suggestions LIKE %s)")
        like = f"%{search}%"
        params.extend([like] * 4)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""SELECT * FROM visits {where}
                ORDER BY visit_date DESC, created_at DESC
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
        clauses.append("name LIKE %s")
        params.append(f"%{search}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with database.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM retailers {where} ORDER BY name", params
        ).fetchall()]


def get_stats() -> dict:
    with database.get_conn() as conn:
        return {
            "total_visits": conn.execute("SELECT COUNT(*) AS c FROM visits").fetchone()["c"],
            "unique_retailers_visited": conn.execute("SELECT COUNT(DISTINCT retailer) AS c FROM visits").fetchone()["c"],
            "unique_markets": conn.execute("SELECT COUNT(DISTINCT market) AS c FROM visits").fetchone()["c"],
            "total_retailers_in_master": conn.execute("SELECT COUNT(*) AS c FROM retailers").fetchone()["c"],
        }


def get_coverage(group_by: str) -> list:
    if group_by not in ("tl", "ss", "rds"):
        raise ValueError("group_by must be one of: tl, ss, rds")
    with database.get_conn() as conn:
        assigned_rows = conn.execute(
            f"""SELECT {group_by} AS grp, COUNT(*) AS assigned
                FROM retailers
                WHERE {group_by} IS NOT NULL AND {group_by} != ''
                GROUP BY {group_by}"""
        ).fetchall()
        result = []
        for row in assigned_rows:
            grp, assigned = row["grp"], row["assigned"]
            visited = conn.execute(
                f"""SELECT COUNT(DISTINCT v.retailer) AS c
                    FROM visits v JOIN retailers r ON r.name = v.retailer
                    WHERE r.{group_by} = %s""", (grp,)
            ).fetchone()["c"]
            total_visits = conn.execute(
                f"SELECT COUNT(*) AS c FROM visits WHERE {group_by} = %s", (grp,)
            ).fetchone()["c"]
            result.append({
                "name": grp, "assigned": assigned, "visited": visited,
                "coverage_pct": round((visited / assigned) * 100, 1) if assigned else 0.0,
                "total_visits": total_visits,
            })
        return sorted(result, key=lambda r: r["name"])
