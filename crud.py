from datetime import datetime, timezone
from typing import Optional

from . import database


def lookup_retailer(conn, name: str):
    row = conn.execute(
        "SELECT * FROM retailers WHERE name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


def create_visit(payload) -> dict:
    with database.get_conn() as conn:
        info = lookup_retailer(conn, payload.retailer) or {}
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO visits
                (retailer, market, visit_date, feedback, suggestions, submitted_by, tl, ss, rds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.retailer,
                payload.market,
                payload.visit_date.isoformat(),
                payload.feedback or "",
                payload.suggestions or "",
                payload.submitted_by or "Unknown",
                info.get("tl", ""),
                info.get("ss", ""),
                info.get("rds", ""),
                now,
            ),
        )
        visit_id = cur.lastrowid
        row = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        return dict(row)


def list_visits(
    retailer: Optional[str] = None,
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list:
    clauses = []
    params: list = []

    if retailer:
        clauses.append("retailer = ?")
        params.append(retailer)
    if tl:
        clauses.append("tl = ?")
        params.append(tl)
    if ss:
        clauses.append("ss = ?")
        params.append(ss)
    if rds:
        clauses.append("rds = ?")
        params.append(rds)
    if date_from:
        clauses.append("visit_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("visit_date <= ?")
        params.append(date_to)
    if search:
        clauses.append("(retailer LIKE ? OR market LIKE ? OR feedback LIKE ? OR suggestions LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT * FROM visits
        {where}
        ORDER BY visit_date DESC, created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    with database.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_visit(visit_id: int) -> Optional[dict]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        return dict(row) if row else None


def delete_visit(visit_id: int) -> bool:
    with database.get_conn() as conn:
        cur = conn.execute("DELETE FROM visits WHERE id = ?", (visit_id,))
        return cur.rowcount > 0


def list_retailers(
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    search: Optional[str] = None,
) -> list:
    clauses = []
    params: list = []
    if tl:
        clauses.append("tl = ?")
        params.append(tl)
    if ss:
        clauses.append("ss = ?")
        params.append(ss)
    if rds:
        clauses.append("rds = ?")
        params.append(rds)
    if search:
        clauses.append("name LIKE ?")
        params.append(f"%{search}%")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM retailers {where} ORDER BY name"

    with database.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with database.get_conn() as conn:
        total_visits = conn.execute("SELECT COUNT(*) AS c FROM visits").fetchone()["c"]
        unique_retailers = conn.execute(
            "SELECT COUNT(DISTINCT retailer) AS c FROM visits"
        ).fetchone()["c"]
        unique_markets = conn.execute(
            "SELECT COUNT(DISTINCT market) AS c FROM visits"
        ).fetchone()["c"]
        total_master = conn.execute("SELECT COUNT(*) AS c FROM retailers").fetchone()["c"]
        return {
            "total_visits": total_visits,
            "unique_retailers_visited": unique_retailers,
            "unique_markets": unique_markets,
            "total_retailers_in_master": total_master,
        }


def get_coverage(group_by: str) -> list:
    """
    group_by must be one of 'tl', 'ss', 'rds'.
    Returns, for each value of that column in the retailer master list:
    how many retailers are assigned, how many distinct ones have at
    least one visit, coverage percentage, and total visit count.
    """
    if group_by not in ("tl", "ss", "rds"):
        raise ValueError("group_by must be one of: tl, ss, rds")

    with database.get_conn() as conn:
        assigned_rows = conn.execute(
            f"""
            SELECT {group_by} AS grp, COUNT(*) AS assigned
            FROM retailers
            WHERE {group_by} IS NOT NULL AND {group_by} != ''
            GROUP BY {group_by}
            """
        ).fetchall()

        result = []
        for row in assigned_rows:
            grp = row["grp"]
            assigned = row["assigned"]

            visited = conn.execute(
                f"""
                SELECT COUNT(DISTINCT v.retailer) AS c
                FROM visits v
                JOIN retailers r ON r.name = v.retailer
                WHERE r.{group_by} = ?
                """,
                (grp,),
            ).fetchone()["c"]

            total_visits = conn.execute(
                f"SELECT COUNT(*) AS c FROM visits WHERE {group_by} = ?",
                (grp,),
            ).fetchone()["c"]

            coverage_pct = round((visited / assigned) * 100, 1) if assigned else 0.0

            result.append(
                {
                    "name": grp,
                    "assigned": assigned,
                    "visited": visited,
                    "coverage_pct": coverage_pct,
                    "total_visits": total_visits,
                }
            )

        result.sort(key=lambda r: r["name"])
        return result
