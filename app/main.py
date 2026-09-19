"""Market Visit Tracker API with GTM hierarchy and retailer intelligence."""

import csv
import io
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import crud, database
from .auth import get_current_user, hash_password, require_admin_key, require_manager, verify_password, create_token
from .schemas import (CoverageRow, LoginOut, LoginRequest, RetailerHealthOut, RetailerOut, StatsOut,
                      UserOut, VisitCreate, VisitOut)

app = FastAPI(title="Market Visit Tracker API", description="GTM retailer visits, coverage and field intelligence.", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
def on_startup():
    database.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/auth/login", response_model=LoginOut)
def login(payload: LoginRequest):
    user = crud.get_user_by_username(payload.username)
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_token(user)
    safe_user = {k: user.get(k) for k in ("id", "name", "role", "tl", "ss", "rds", "active")}
    return {"access_token": token, "token_type": "bearer", "user": safe_user}


@app.get("/auth/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    if user.get("role") == "MANAGER":
        return {"id": 0, "name": "Manager", "role": "MANAGER", "active": True}
    db_user = crud.get_user_by_username(user.get("sub", user.get("name", "")))
    if not db_user:
        raise HTTPException(status_code=401, detail="User account not found.")
    return db_user


def _scope(user: dict) -> dict:
    role = user.get("role")
    name = user.get("name")

    if role == "TL":
        return {"tl": name}
    if role == "SS":
        return {"ss": name}
    if role == "RDS":
        return {"rds": name}

    return {}

@app.post("/visits", response_model=VisitOut)
def create_visit(payload: VisitCreate, user: dict = Depends(get_current_user)):
    scope = _scope(user)
    retailer = crud.lookup_retailer_by_name(payload.retailer)
    if not retailer:
        raise HTTPException(status_code=400, detail="Retailer is not in the master list.")
    if scope and any(retailer.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You can only log visits for retailers assigned to you.")
    payload.submitted_by = user.get("name", "Manager")
    payload.submitted_role = user.get("role", "MANAGER")
    return crud.create_visit(payload)


@app.get("/visits", response_model=List[VisitOut])
def get_visits(retailer: Optional[str] = None, tl: Optional[str] = None, ss: Optional[str] = None,
               rds: Optional[str] = None, submitted_by: Optional[str] = None,
               submitted_role: Optional[str] = None, date_from: Optional[str] = Query(default=None),
               date_to: Optional[str] = Query(default=None), search: Optional[str] = Query(default=None),
               limit: int = Query(default=500, ge=1, le=2000), offset: int = Query(default=0, ge=0),
               user: dict = Depends(get_current_user)):
    scope = _scope(user)
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
        submitted_by = None
    return crud.list_visits(retailer=retailer, tl=tl, ss=ss, rds=rds, submitted_by=submitted_by,
                            submitted_role=submitted_role, date_from=date_from, date_to=date_to,
                            search=search, limit=limit, offset=offset)


@app.get("/retailers", response_model=List[RetailerOut])
def get_retailers(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                  search: Optional[str] = None, user: dict = Depends(get_current_user)):
    scope = _scope(user)
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.list_retailers(tl=tl, ss=ss, rds=rds, search=search)


@app.get("/visits/{visit_id}", response_model=VisitOut)
def get_visit(visit_id: int, user: dict = Depends(get_current_user)):
    visit = crud.get_visit(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found.")
    scope = _scope(user)
    if scope and any(visit.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot access this visit.")
    return visit


@app.delete("/visits/{visit_id}", status_code=204, dependencies=[Depends(require_admin_key)])
def delete_visit(visit_id: int):
    if not crud.delete_visit(visit_id):
        raise HTTPException(status_code=404, detail="Visit not found.")
    return None


@app.get("/visits/export.csv")
def export_visits_csv(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                      date_from: Optional[str] = None, date_to: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    scope = _scope(user)
    if scope: tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    rows = crud.list_visits(tl=tl, ss=ss, rds=rds, date_from=date_from, date_to=date_to, limit=2000)
    buffer = io.StringIO(); writer = csv.writer(buffer)
    writer.writerow(["id", "visit_date", "retailer", "tl", "ss", "rds", "market", "feedback", "suggestions", "submitted_by", "submitted_role", "created_at"])
    for r in rows:
        writer.writerow([r["id"], r["visit_date"], r["retailer"], r["tl"], r["ss"], r["rds"], r["market"], r["feedback"], r["suggestions"], r["submitted_by"], r["submitted_role"], r["created_at"]])
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=market-visits.csv"})


@app.get("/users", response_model=List[UserOut])
def get_users(role: Optional[str] = Query(default=None, pattern="^(TL|SS|RDS)$"), user: dict = Depends(get_current_user)):
    require_manager(user)
    return crud.list_users(role=role)


@app.post("/admin/provision-users", dependencies=[Depends(require_admin_key)])
def provision_users():
    return {"users": crud.provision_user_credentials(), "note": "Store these temporary passwords securely. They are shown only when credentials are first provisioned."}


@app.get("/stats", response_model=StatsOut)
def get_stats(user: dict = Depends(get_current_user)):
    scope = _scope(user)
    return crud.get_stats(**scope)


@app.get("/coverage", response_model=List[CoverageRow])
def get_coverage(
    group_by: str = Query("tl", pattern="^(tl|ss|rds)$"),
    user: dict = Depends(get_current_user)
):
    role = user.get("role")

    if role in ("TL", "SS", "RDS"):
        group_by = role.lower()

    rows = crud.get_coverage(group_by)

    if role in ("TL", "SS", "RDS"):
        name = user.get("name")
        rows = [r for r in rows if r["name"] == name]

    return rows


@app.get("/retailer-health", response_model=List[RetailerHealthOut])
def retailer_health(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                    zone: Optional[str] = None, priority: Optional[str] = None,
                    limit: int = Query(default=500, ge=1, le=2000), user: dict = Depends(get_current_user)):
    scope = _scope(user)
    if scope: tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.get_retailer_health(tl=tl, ss=ss, rds=rds, zone=zone, priority=priority, limit=limit)
