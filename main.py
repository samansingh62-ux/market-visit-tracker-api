"""
Market Visit Tracker API

A small FastAPI service for logging retailer visits and reporting
coverage by TL (Team Leader), SS (Sales Supervisor), and RDS
(distributor), so management can see retailer-wise tracking.

Run locally:
    uvicorn app.main:app --reload --port 8000

Then open http://localhost:8000/docs for interactive API docs.

See README.md for deployment notes and authentication setup.
"""

import csv
import io
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import crud, database
from .auth import require_admin_key, require_api_key
from .schemas import CoverageRow, RetailerOut, StatsOut, VisitCreate, VisitOut

app = FastAPI(
    title="Market Visit Tracker API",
    description="Log retailer visits and track coverage by TL, SS, and RDS.",
    version="1.0.0",
)

# Allow calls from any origin by default. Tighten this (list specific
# domains) before exposing the API publicly if that matters to you.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    database.init_db()


@app.get("/health")
def health():
    """Unauthenticated health check for uptime monitors / load balancers."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------

@app.post("/visits", response_model=VisitOut, dependencies=[Depends(require_api_key)])
def create_visit(payload: VisitCreate):
    """Log a new market visit. TL/SS/RDS are filled in automatically by
    matching `retailer` against the master retailer list."""
    return crud.create_visit(payload)


@app.get("/visits", response_model=List[VisitOut], dependencies=[Depends(require_api_key)])
def get_visits(
    retailer: Optional[str] = None,
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    search: Optional[str] = Query(default=None, description="Free-text search across retailer, market, feedback, suggestions"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    """List visits, newest first, with optional filters."""
    return crud.list_visits(
        retailer=retailer, tl=tl, ss=ss, rds=rds,
        date_from=date_from, date_to=date_to, search=search,
        limit=limit, offset=offset,
    )


@app.get("/visits/export.csv", dependencies=[Depends(require_api_key)])
def export_visits_csv(
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Export visits matching the given filters as a CSV file."""
    rows = crud.list_visits(tl=tl, ss=ss, rds=rds, date_from=date_from, date_to=date_to, limit=2000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "visit_date", "retailer", "tl", "ss", "rds", "market", "feedback", "suggestions", "submitted_by", "created_at"])
    for r in rows:
        writer.writerow([r["id"], r["visit_date"], r["retailer"], r["tl"], r["ss"], r["rds"], r["market"], r["feedback"], r["suggestions"], r["submitted_by"], r["created_at"]])
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=market-visits.csv"},
    )


@app.get("/visits/{visit_id}", response_model=VisitOut, dependencies=[Depends(require_api_key)])
def get_visit(visit_id: int):
    visit = crud.get_visit(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found.")
    return visit


@app.delete("/visits/{visit_id}", status_code=204, dependencies=[Depends(require_admin_key)])
def delete_visit(visit_id: int):
    """Delete a visit. Requires the admin API key (see auth.py)."""
    deleted = crud.delete_visit(visit_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Visit not found.")
    return None


# ---------------------------------------------------------------------------
# Retailers (master list)
# ---------------------------------------------------------------------------

@app.get("/retailers", response_model=List[RetailerOut], dependencies=[Depends(require_api_key)])
def get_retailers(
    tl: Optional[str] = None,
    ss: Optional[str] = None,
    rds: Optional[str] = None,
    search: Optional[str] = None,
):
    """List retailers from the master list, optionally filtered by TL, SS, RDS, or name."""
    return crud.list_retailers(tl=tl, ss=ss, rds=rds, search=search)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

@app.get("/stats", response_model=StatsOut, dependencies=[Depends(require_api_key)])
def get_stats():
    """Overall counts: total visits, unique retailers/markets visited, master list size."""
    return crud.get_stats()


@app.get("/coverage", response_model=List[CoverageRow], dependencies=[Depends(require_api_key)])
def get_coverage(group_by: str = Query(..., pattern="^(tl|ss|rds)$", description="One of: tl, ss, rds")):
    """
    Retailer-wise coverage tracking, grouped by TL, SS, or RDS.

    For each value of the chosen dimension: how many retailers are
    assigned to it, how many have received at least one visit, the
    resulting coverage percentage, and the total number of visits logged.
    """
    return crud.get_coverage(group_by)
