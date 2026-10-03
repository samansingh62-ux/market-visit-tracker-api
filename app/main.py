"""Market Visit Tracker API with GTM hierarchy and retailer intelligence."""

import calendar
import csv
import io
import os
from datetime import date
from pathlib import Path
from typing import List, Optional

import httpx
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from fastapi import Depends, FastAPI, HTTPException, Query, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response

from . import crud, database
from .auth import get_current_user, get_dashboard_user, hash_password, require_admin_key, require_manager, verify_password, create_token
from .schemas import (
    AdminUserOut,
    CoverageRow,
    LoginOut,
    PinLoginRequest,
    LoginRequest,
    PasswordResetOut,
    RetailerHealthOut,
    RetailerOut,
    StatsOut,
    UserOut,
    UserStatusOut,
    VisitCreate,
    VisitOut, PhotoOut,
)
app = FastAPI(title="Market Visit Tracker API", description="GTM retailer visits, coverage and field intelligence.", version="2.1.0")

VWORK_LIVE_API_URL = os.getenv("VWORK_LIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")
VWORK_LIVE_API_KEY = os.getenv("VWORK_LIVE_API_KEY", "").strip()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).resolve().parent / "static"


FOCUS_MODEL_RATES = {
    "Y11": [(2,4,150),(5,8,350),(9,15,500),(16,None,600)],
    "Y21": [(1,3,300),(4,9,600),(10,16,1000),(17,24,1200),(25,None,1600)],
    "Y31t": [(1,1,400),(2,7,700),(8,15,1000),(16,None,1500)],
    "Y51 Pro": [(1,2,500),(3,9,800),(10,15,1000),(16,None,1500)],
    "S2": [(1,2,700),(3,9,1000),(10,15,1500),(16,None,1800)],
    "V70 & V70 FE": [(1,1,500),(2,4,800),(5,9,1300),(10,15,1600),(16,None,2300)],
    "X300 FE": [(1,1,1500),(2,4,2500),(5,None,4000)],
    "X300 Ultra": [(1,1,2000),(2,None,7000)],
}
BACK_SUPPORT_RATES = {
    "Imperial": [0.022,0.024,0.026,0.028],
    "Grand Royal": [0.020,0.022,0.024,0.026],
    "Royal": [0.018,0.020,0.022,0.024],
    "Titanium": [0.017,0.018,0.020,0.022],
    "Platinum": [0.016,0.017,0.019,0.020],
    "Gold": [0.015,0.016,0.018,0.019],
    "Non-Club": [0.0,0.0,0.0,0.0],
}
FESTIVE_SCHEME_START = date(2026, 10, 5)
FESTIVE_SCHEME_END = date(2026, 10, 20)

def _rate_for_units(units, slabs):
    for lo, hi, rate in slabs:
        if units >= lo and (hi is None or units <= hi):
            label = f"{lo}+" if hi is None else (f"{lo} Unit" if lo == hi == 1 else f"{lo}-{hi} Units")
            return rate, label
    return 0, None


def _focus_model_payout(sales_row):
    series = (sales_row or {}).get("series") or {}
    detail, total, total_units = [], 0, 0
    for name, slabs in FOCUS_MODEL_RATES.items():
        units = int(series.get(name) or 0)
        if units <= 0:
            continue
        rate, slab = _rate_for_units(units, slabs)
        payout = units * rate
        total += payout
        total_units += units
        detail.append({"series": name, "units": units, "slab": slab, "rate_per_unit": rate, "payout": payout})
    return {"eligible_units": total_units, "payout": total, "detail": detail}


def _v80_npl_payout(sales_row):
    units = int((sales_row or {}).get("v80_units") or 0)
    if units <= 0:
        return {"units": 0, "slab": None, "normal_sales_payout": 0, "max_total_payout": 0}
    if units == 1:
        slab, normal, total = "1 Unit", 800, 1300
    elif units <= 4:
        slab, normal, total = "2-4 Units", 1000, 1600
    elif units <= 8:
        slab, normal, total = "5-8 Units", 1200, 1900
    elif units <= 12:
        slab, normal, total = "9-12 Units", 1500, 2300
    else:
        slab, normal, total = "13 Units & Above", 2000, 3000
    return {
        "units": units,
        "slab": slab,
        "normal_rate_per_unit": normal,
        "total_rate_per_unit": total,
        "normal_sales_payout": units * normal,
        "max_total_payout": units * total,
    }


def _back_support_estimate(club_value, target_value, sales_row):
    club = str(club_value or "Non-Club").strip()
    rates = BACK_SUPPORT_RATES.get(club, [0.0,0.0,0.0,0.0])
    buckets = (sales_row or {}).get("margin_buckets") or {}
    keys = ["20K-25K","25K-30K","30K-50K","50K+"]
    base_margin = sum(float(buckets.get(k) or 0) * rate for k, rate in zip(keys, rates))
    non_t = float((sales_row or {}).get("non_t_value") or 0)
    t_val = float((sales_row or {}).get("t_series_value") or 0)
    counted_t = min(t_val, non_t / 9) if non_t > 0 else 0
    counted_value = non_t + counted_t
    target_value = float(target_value or 0)
    ach_pct = round(counted_value * 100 / target_value, 1) if target_value > 0 else 0
    if target_value <= 0:
        eligibility, payable = "Target value unavailable", None
    elif ach_pct >= 100:
        eligibility, payable = "100%+ target achieved", round(base_margin)
    elif ach_pct >= 90:
        eligibility, payable = "90-99.9%: proration rule requires confirmation", None
    else:
        eligibility, payable = "Below 90% target achievement", 0
    return {
        "club": club,
        "estimated_sales_value": round(float((sales_row or {}).get("sales_value_estimate") or 0)),
        "counted_achievement_value": round(counted_value),
        "achievement_pct_value": ach_pct,
        "base_margin": round(base_margin),
        "provisional_payable": payable,
        "eligibility": eligibility,
        "unknown_value_units": int((sales_row or {}).get("unknown_value_units") or 0),
        "buckets": {k: round(float(buckets.get(k) or 0)) for k in keys},
    }


def _festive_scheme_payout(club_value, scheme_sales):
    """Provisional Oct-2026 festive booster payout from eligible sales buckets."""
    club_text = str(club_value or "").strip()
    if not club_text:
        return {
            "scheme_type": "Unclassified",
            "slab": None,
            "eligible_units": 0,
            "payout": None,
            "unknown_price_units": int((scheme_sales or {}).get("unknown_price_units") or 0),
            "segments": (scheme_sales or {}).get("segments") or {},
        }

    is_non_club = club_text.lower() == "non-club"
    units = int((scheme_sales or {}).get("eligible_units") or 0)
    segments = (scheme_sales or {}).get("segments") or {}
    unknown_price_units = int((scheme_sales or {}).get("unknown_price_units") or 0)

    if is_non_club:
        scheme_type = "NPO / Non-Club"
        if 2 <= units <= 4:
            slab, rates = "2-4 Units", [200, 300, 400, 500]
        elif 5 <= units <= 9:
            slab, rates = "5-9 Units", [300, 400, 500, 600]
        elif 10 <= units <= 14:
            slab, rates = "10-14 Units", [500, 600, 700, 800]
        elif units >= 15:
            slab, rates = "15 Units & Above", [600, 700, 800, 900]
        else:
            slab, rates = None, [0, 0, 0, 0]
    else:
        scheme_type = "Club / PO"
        if 5 <= units <= 9:
            slab, rates = "5-9 Units", [100, 200, 300, 400]
        elif 10 <= units <= 15:
            slab, rates = "10-15 Units", [200, 300, 400, 500]
        elif 16 <= units <= 20:
            slab, rates = "16-20 Units", [300, 400, 500, 600]
        elif 21 <= units <= 29:
            slab, rates = "21-29 Units", [400, 500, 600, 700]
        elif units >= 30:
            slab, rates = "30 Units & Above", [500, 600, 700, 800]
        else:
            slab, rates = None, [0, 0, 0, 0]

    keys = ["15K-25K", "25K-35K", "35K-50K", "50K+"]
    payout = sum(int(segments.get(k) or 0) * rate for k, rate in zip(keys, rates))

    return {
        "scheme_type": scheme_type,
        "slab": slab,
        "eligible_units": units,
        "payout": payout,
        "unknown_price_units": unknown_price_units,
        "segments": {k: int(segments.get(k) or 0) for k in keys},
    }


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


@app.get("/auth/pin-users", include_in_schema=False)
def pin_users():
    rows = crud.list_users_admin()
    return {
        "TL": sorted([r["name"] for r in rows if r["role"] == "TL"]),
        "SS": sorted([r["name"] for r in rows if r["role"] == "SS"]),
    }


@app.post("/auth/pin-login", response_model=LoginOut)
def pin_login(payload: PinLoginRequest):
    user = crud.get_user_by_pin(payload.pin)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid PIN.")
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
               user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
        submitted_by = None
    return crud.list_visits(retailer=retailer, tl=tl, ss=ss, rds=rds, submitted_by=submitted_by,
                            submitted_role=submitted_role, date_from=date_from, date_to=date_to,
                            search=search, limit=limit, offset=offset)


@app.get("/retailers", response_model=List[RetailerOut])
def get_retailers(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                  search: Optional[str] = None, user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.list_retailers(tl=tl, ss=ss, rds=rds, search=search)


@app.get("/retailers/{retailer_code}/360")
def retailer_360(
    retailer_code: str,
    start_date: Optional[str] = Query(default=None, alias="startDate"),
    end_date: Optional[str] = Query(default=None, alias="endDate"),
    inventory_date: Optional[str] = Query(default=None, alias="inventoryDate"),
    user: dict = Depends(get_dashboard_user),
):
    retailer = crud.lookup_retailer_by_code(retailer_code)
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer is not in the Market Visit master.")

    scope = _scope(user)
    if scope and any(retailer.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot access this retailer.")

    today = date.today()
    start_date = start_date or today.replace(day=1).isoformat()
    end_date = end_date or today.isoformat()
    inventory_date = inventory_date or end_date

    params = {
        "startDate": start_date,
        "endDate": end_date,
        "inventoryDate": inventory_date,
        "pageSize": 500,
        "maxPages": 100,
    }
    headers = {}
    if VWORK_LIVE_API_KEY:
        headers["X-API-Key"] = VWORK_LIVE_API_KEY

    try:
        with httpx.Client(timeout=httpx.Timeout(240.0, connect=10.0)) as client:
            response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/retailers/{retailer['code']}/360",
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Retailer 360 service unavailable: {exc}") from exc

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="No live V-Work data found for this retailer.")
    if not response.is_success:
        detail = "Live retailer intelligence request failed."
        try:
            detail = response.json().get("detail") or detail
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)

    live = response.json()
    visits = crud.retailer_visit_history(retailer["name"], limit=5)

    sales = live.get("sales") or {}
    inventory = live.get("inventory") or {}
    performance = live.get("performance") or {}
    sales_units = int(sales.get("units") or 0)
    stock_units = int(inventory.get("units") or 0)
    dos = performance.get("dos")

    target_month = start_date[:7]
    target_row = crud.get_retailer_target(retailer["code"], target_month)
    target_volume = int(target_row.get("target_volume") or 0) if target_row else None
    target_value = int(target_row.get("target_value") or 0) if target_row else None
    achievement_pct = None
    gap_volume = None
    required_run_rate = None
    days_remaining = None
    if target_volume is not None:
        achievement_pct = round((sales_units / target_volume) * 100, 1) if target_volume > 0 else 0
        gap_volume = max(target_volume - sales_units, 0)
        period_end = date.fromisoformat(end_date)
        month_days = calendar.monthrange(period_end.year, period_end.month)[1]
        days_remaining = max(month_days - period_end.day + 1, 1)
        required_run_rate = round(gap_volume / days_remaining, 1)

    actions = []
    if sales_units == 0:
        actions.append("Discuss sell-out activation and identify why MTD sales are zero.")
    if isinstance(dos, (int, float)):
        if dos < 7:
            actions.append("Stock cover is below 7 days. Prioritise replenishment on fast-moving models.")
        elif dos > 30:
            actions.append("Stock cover is above 30 days. Focus on ageing stock and sell-through actions.")
    model_intelligence = performance.get("model_intelligence") or []
    critical_models = [
        x for x in model_intelligence
        if x.get("status") in ("Out of Stock", "Low Stock", "High Stock", "No MTD Sell-out")
    ]

    for item in critical_models[:4]:
        model = item.get("model") or "Unknown model"
        status = item.get("status")
        sales_qty = int(item.get("sales") or 0)
        stock_qty = int(item.get("stock") or 0)
        model_dos = item.get("dos")
        if status == "Out of Stock":
            actions.append(f"{model}: {sales_qty} MTD sales but zero stock. Replenish immediately.")
        elif status == "Low Stock":
            actions.append(f"{model}: only {model_dos} DOS with {sales_qty} MTD sales. Prioritise replenishment.")
        elif status == "High Stock":
            actions.append(f"{model}: high stock cover at {model_dos} DOS. Discuss sell-through activity.")
        elif status == "No MTD Sell-out":
            actions.append(f"{model}: {stock_qty} units in stock with no MTD sell-out. Identify conversion blocker.")

    if not visits:
        actions.append("No prior market visit is recorded. Capture retailer feedback, commitments and follow-up actions.")
    else:
        last_visit = visits[0]
        if last_visit.get("suggestions"):
            actions.append("Review previous follow-up: " + str(last_visit["suggestions"])[:180])

    return {
        **live,
        "target": {
            "month": target_month,
            "volume": target_volume,
            "value": target_value,
            "achievement_pct": achievement_pct,
            "gap_volume": gap_volume,
            "required_run_rate": required_run_rate,
            "days_remaining": days_remaining,
            "loaded": target_row is not None,
        },
        "market_visit": {
            "master": retailer,
            "recent_visits": visits,
            "what_to_discuss": actions[:5],
        },
    }


@app.get("/visits/{visit_id}", response_model=VisitOut)
def get_visit(visit_id: int, user: dict = Depends(get_dashboard_user)):
    visit = crud.get_visit(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found.")
    scope = _scope(user)
    if scope and any(visit.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot access this visit.")
    return visit


@app.get("/visits/{visit_id}/photos", response_model=List[PhotoOut])
def visit_photos(visit_id: int, user: dict = Depends(get_dashboard_user)):
    visit = crud.get_visit(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found.")
    scope = _scope(user)
    if scope and any(visit.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot access this visit.")
    rows = crud.list_visit_photos(visit_id)
    return [{**r, "url": f"/visits/{visit_id}/photos/{r['id']}"} for r in rows]

@app.get("/visits/{visit_id}/photos/{photo_id}")
def visit_photo(visit_id: int, photo_id: int, user: dict = Depends(get_dashboard_user)):
    visit = crud.get_visit(visit_id)
    photo = crud.get_visit_photo(photo_id)
    if not visit or not photo or photo["visit_id"] != visit_id:
        raise HTTPException(status_code=404, detail="Photo not found.")
    scope = _scope(user)
    if scope and any(visit.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot access this photo.")
    return Response(content=photo["data"], media_type=photo["mime_type"])

@app.post("/visits/{visit_id}/photos", response_model=List[PhotoOut])
async def upload_visit_photos(visit_id: int, files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    visit = crud.get_visit(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found.")
    scope = _scope(user)
    if scope and any(visit.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="You cannot upload photos to this visit.")
    existing = crud.list_visit_photos(visit_id)
    if len(existing) + len(files) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 stock photos per visit.")
    allowed = {"image/jpeg", "image/png", "image/webp"}
    out = []
    for upload in files:
        if upload.content_type not in allowed:
            raise HTTPException(status_code=400, detail="Only JPG, PNG or WEBP images are allowed.")
        data = await upload.read()
        if len(data) > 4 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Each photo must be 4 MB or smaller.")
        row = crud.add_visit_photo(visit_id, upload.filename or "stock-photo", upload.content_type, data)
        out.append({**row, "url": f"/visits/{visit_id}/photos/{row['id']}"})
    return out

@app.delete("/visits/{visit_id}", status_code=204, dependencies=[Depends(require_admin_key)])
def delete_visit(visit_id: int):
    if not crud.delete_visit(visit_id):
        raise HTTPException(status_code=404, detail="Visit not found.")
    return None


@app.get("/exports/all-data.xlsx")
def export_all_data_xlsx(user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    perf = performance_dashboard(user)
    visits = crud.list_visits(
        tl=scope.get("tl"), ss=scope.get("ss"), rds=scope.get("rds"), limit=10000
    )

    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="DCEBFF")
    header_font = Font(bold=True, color="17365D")

    def finish(ws):
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for col in ws.columns:
            letter = col[0].column_letter
            width = max(12, min(36, max(len(str(x.value or "")) for x in col) + 2))
            ws.column_dimensions[letter].width = width

    ws = wb.create_sheet("Summary")
    ws.append(["Metric", "Value"])
    summary = perf.get("summary", {})
    rows = [
        ("User", user.get("name", "Manager")),
        ("Role", user.get("role", "MANAGER")),
        ("Month", perf.get("period", {}).get("month")),
        ("Retailers", summary.get("retailers", 0)),
        ("Target", summary.get("target", 0)),
        ("MTD Sales", summary.get("sales", 0)),
        ("Achievement %", summary.get("achievement_pct", 0)),
        ("Gap", summary.get("gap", 0)),
        ("Required / Day", summary.get("required_per_day", 0)),
        ("Stock", summary.get("stock", 0)),
        ("Productive Retailers", summary.get("productive_retailers", 0)),
        ("Zero Sales Retailers", summary.get("zero_sales_retailers", 0)),
        ("Visits", len(visits)),
        ("Festive Scheme Eligible Units", summary.get("scheme_eligible_units", 0)),
        ("Festive Scheme Provisional Payout", summary.get("scheme_payout", 0)),
        ("Scope", "Full Zone A" if user.get("role") == "MANAGER" else f"{user.get('role')} hierarchy only"),
    ]
    for row in rows:
        ws.append(row)
    finish(ws)

    ws = wb.create_sheet("Retailer Performance")
    ws.append(["Retailer Code","Retailer","TL","SS","RDS","Zone","Club","Target","MTD Sales","Achievement %","Gap","Required / Day","Stock","Avg / Day","DOS","Scheme Type","Scheme Slab","Scheme Eligible Units","Provisional Payout","Unknown Price Units","Last Visit","Days Since Visit","Visit Count","Status"])
    for x in perf.get("retailers", []):
        ws.append([x.get("code"),x.get("name"),x.get("tl"),x.get("ss"),x.get("rds"),x.get("zone"),x.get("club"),x.get("target"),x.get("sales"),x.get("achievement_pct"),x.get("gap"),x.get("required_per_day"),x.get("stock"),x.get("avg_daily_sales"),x.get("dos"),x.get("scheme_type"),x.get("scheme_slab"),x.get("scheme_eligible_units"),x.get("scheme_payout"),x.get("scheme_unknown_price_units"),x.get("last_visit"),x.get("days_since_visit"),x.get("visit_count"),x.get("status")])
    finish(ws)

    ws = wb.create_sheet("Visit History")
    ws.append(["Visit ID","Visit Date","Retailer","Market","TL","SS","RDS","Submitted By","Role","Latitude","Longitude","GPS Accuracy","Photos","Feedback","Suggestions","Created At"])
    for x in visits:
        ws.append([x.get("id"),x.get("visit_date"),x.get("retailer"),x.get("market"),x.get("tl"),x.get("ss"),x.get("rds"),x.get("submitted_by"),x.get("submitted_role"),x.get("latitude"),x.get("longitude"),x.get("gps_accuracy"),x.get("photo_count"),x.get("feedback"),x.get("suggestions"),x.get("created_at")])
    finish(ws)

    for key, title in (("tl","TL Summary"),("ss","SS Summary"),("rds","RDS Summary")):
        ws = wb.create_sheet(title)
        ws.append(["Name","Retailers","Target","MTD Sales","Achievement %","Gap","Stock"])
        for x in perf.get("hierarchy", {}).get(key, []):
            ws.append([x.get("name"),x.get("retailers"),x.get("target"),x.get("sales"),x.get("achievement_pct"),x.get("gap"),x.get("stock")])
        finish(ws)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    role = str(user.get("role") or "MANAGER").lower()
    name = "".join(ch for ch in str(user.get("name") or "Manager") if ch.isalnum() or ch in "-_") or "Manager"
    filename = f"market-visit-tracker-{role}-{name}-{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/visits/export.csv")
def export_visits_csv(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                      date_from: Optional[str] = None, date_to: Optional[str] = None,
                      user: dict = Depends(get_dashboard_user)):
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


@app.post("/admin/targets/upload", dependencies=[Depends(require_admin_key)])
async def admin_upload_targets(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    file: UploadFile = File(...),
):
    """Import monthly retailer targets from the standard Zone A target workbook."""
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload an .xlsx target workbook.")

    try:
        raw = await file.read()
        workbook = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        sheet = workbook[workbook.sheetnames[0]]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read target workbook: {exc}") from exc

    required = {"Retailer Code", "Retailer Name", "Vol Target", "Val Target"}
    header_row = None
    headers = None
    for row_no, values in enumerate(sheet.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        candidate = [str(v).strip() if v is not None else "" for v in values]
        if required.issubset(set(candidate)):
            header_row = row_no
            headers = candidate
            break

    if header_row is None or headers is None:
        raise HTTPException(
            status_code=400,
            detail="Target workbook must contain Retailer Code, Retailer Name, Vol Target and Val Target columns.",
        )

    idx = {name: headers.index(name) for name in required}
    aggregated = {}
    for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        code = values[idx["Retailer Code"]] if idx["Retailer Code"] < len(values) else None
        if code is None or str(code).strip() == "":
            continue
        code = str(code).strip().upper()
        name = values[idx["Retailer Name"]] if idx["Retailer Name"] < len(values) else ""
        volume = values[idx["Vol Target"]] if idx["Vol Target"] < len(values) else 0
        value = values[idx["Val Target"]] if idx["Val Target"] < len(values) else 0
        try:
            volume = int(round(float(volume or 0)))
        except (TypeError, ValueError):
            volume = 0
        try:
            value = int(round(float(value or 0)))
        except (TypeError, ValueError):
            value = 0

        item = aggregated.setdefault(code, {
            "retailer_code": code,
            "retailer_name": str(name or "").strip(),
            "target_volume": 0,
            "target_value": 0,
        })
        item["target_volume"] += volume
        item["target_value"] += value
        if not item["retailer_name"] and name:
            item["retailer_name"] = str(name).strip()

    if not aggregated:
        raise HTTPException(status_code=400, detail="No retailer target rows were found.")

    result = crud.upsert_retailer_targets(month, list(aggregated.values()))
    return {
        **result,
        "filename": file.filename,
        "message": "Monthly retailer targets imported successfully.",
    }


@app.get("/admin/users",
    response_model=List[AdminUserOut],
    dependencies=[Depends(require_admin_key)],
)
def admin_users():
    return crud.list_users_admin()


@app.post(
    "/admin/users/{user_id}/reset-password",
    response_model=PasswordResetOut,
    dependencies=[Depends(require_admin_key)],
)
def admin_reset_password(user_id: int):
    result = crud.reset_user_password(user_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    return result


@app.post(
    "/admin/users/{user_id}/activate",
    response_model=UserStatusOut,
    dependencies=[Depends(require_admin_key)],
)
def admin_activate_user(user_id: int):
    result = crud.set_user_status(
        user_id,
        True,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    return result


@app.post(
    "/admin/users/{user_id}/deactivate",
    response_model=UserStatusOut,
    dependencies=[Depends(require_admin_key)],
)
def admin_deactivate_user(user_id: int):
    result = crud.set_user_status(
        user_id,
        False,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    return result

@app.get("/stats", response_model=StatsOut)
def get_stats(user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    return crud.get_stats(**scope)


@app.get("/coverage", response_model=List[CoverageRow])
def get_coverage(
    group_by: str = Query("tl", pattern="^(tl|ss|rds)$"),
    user: dict = Depends(get_dashboard_user)
):
    role = user.get("role")

    if role in ("TL", "SS", "RDS"):
        group_by = role.lower()

    rows = crud.get_coverage(group_by)

    if role in ("TL", "SS", "RDS"):
        name = user.get("name")
        rows = [r for r in rows if r["name"] == name]

    return rows


@app.get("/performance-trends")
def performance_trends(user: dict = Depends(get_dashboard_user)):
    """Scoped daily sales and model stock/DOS for the logged-in hierarchy."""
    today = date.today()
    scope = _scope(user)
    month = today.strftime("%Y-%m")
    scope_rows = crud.get_performance_scope_rows(
        month,
        tl=scope.get("tl"),
        ss=scope.get("ss"),
        rds=scope.get("rds"),
    )
    codes = [str(r.get("code") or "").strip().upper() for r in scope_rows if r.get("code")]

    headers = {"Content-Type": "application/json"}
    if VWORK_LIVE_API_KEY:
        headers["X-API-Key"] = VWORK_LIVE_API_KEY
    payload = {
        "store_codes": codes,
        "start_date": today.replace(day=1).isoformat(),
        "end_date": today.isoformat(),
        "inventory_date": today.isoformat(),
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            response = client.post(
                f"{VWORK_LIVE_API_URL}/api/v1/dashboard/sales-trends",
                json=payload,
                headers=headers,
            )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Performance trend data unavailable: {exc}") from exc

    return {
        **data,
        "user": {
            "name": user.get("name", "Manager"),
            "role": user.get("role", "MANAGER"),
        },
        "retailer_count": len(codes),
        "model_targets_loaded": False,
        "model_target_note": "Model-level target source is not connected yet; actual sales, stock and DOS are live.",
    }


@app.get("/performance-dashboard")
def performance_dashboard(user: dict = Depends(get_dashboard_user)):
    """Hierarchy-aware retailer performance for TL, SS, RDS and management."""
    today = date.today()
    month = today.strftime("%Y-%m")
    scope = _scope(user)
    rows = crud.get_performance_scope_rows(
        month,
        tl=scope.get("tl"),
        ss=scope.get("ss"),
        rds=scope.get("rds"),
    )

    params = {
        "startDate": today.replace(day=1).isoformat(),
        "endDate": today.isoformat(),
        "inventoryDate": today.isoformat(),
        "pageSize": 500,
        "maxPages": 100,
    }
    headers = {}
    if VWORK_LIVE_API_KEY:
        headers["X-API-Key"] = VWORK_LIVE_API_KEY

    try:
        with httpx.Client(timeout=httpx.Timeout(240.0, connect=10.0)) as client:
            response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/retailers/priority-data",
                params=params,
                headers=headers,
            )
            scheme_response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/schemes/october-festive-sales",
                headers=headers,
            )
        response.raise_for_status()
        scheme_response.raise_for_status()
        live_rows = (response.json() or {}).get("retailers") or []
        scheme_payload = scheme_response.json() or {}
        scheme_rows = scheme_payload.get("retailers") or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Live performance data unavailable: {exc}") from exc

    live_by_code = {
        str(x.get("retailer_code") or "").strip().upper(): x
        for x in live_rows if x.get("retailer_code")
    }

    scheme_by_code = {
        str(x.get("retailer_code") or "").strip().upper(): x
        for x in scheme_rows if x.get("retailer_code")
    }

    month_days = calendar.monthrange(today.year, today.month)[1]
    days_remaining = max(month_days - today.day + 1, 1)
    retailer_rows = []
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        live = live_by_code.get(code, {})
        sales = int(live.get("mtd_sales") or 0)
        stock = int(live.get("good_phone_stock") or 0)
        avg_daily = float(live.get("avg_daily_sales") or 0)
        dos = live.get("dos")
        target = int(row.get("target_volume") or 0)
        scheme = _festive_scheme_payout(row.get("club"), scheme_by_code.get(code, {}))
        gap = max(target - sales, 0)
        ach = round((sales / target) * 100, 1) if target > 0 else 0
        req = round(gap / days_remaining, 1) if target > 0 else 0
        last_visit = row.get("last_visit")
        days_since = None
        if last_visit:
            try:
                days_since = (today - date.fromisoformat(str(last_visit)[:10])).days
            except Exception:
                pass

        if target > 0 and ach < 50:
            status = "Behind"
        elif isinstance(dos, (int, float)) and dos > 45:
            status = "High Stock"
        elif sales > 0 and stock == 0:
            status = "Out of Stock"
        elif sales == 0:
            status = "No Sales"
        else:
            status = "On Track"

        retailer_rows.append({
            "code": code,
            "name": row.get("name"),
            "tl": row.get("tl"),
            "ss": row.get("ss"),
            "rds": row.get("rds"),
            "zone": row.get("zone"),
            "club": row.get("club"),
            "target": target,
            "sales": sales,
            "achievement_pct": ach,
            "gap": gap,
            "required_per_day": req,
            "stock": stock,
            "avg_daily_sales": avg_daily,
            "dos": dos,
            "last_visit": last_visit,
            "days_since_visit": days_since,
            "visit_count": int(row.get("visit_count") or 0),
            "status": status,
            "scheme_type": scheme.get("scheme_type"),
            "scheme_slab": scheme.get("slab"),
            "scheme_eligible_units": scheme.get("eligible_units"),
            "scheme_payout": scheme.get("payout"),
            "scheme_unknown_price_units": scheme.get("unknown_price_units"),
            "scheme_segments": scheme.get("segments"),
        })

    total_target = sum(x["target"] for x in retailer_rows)
    total_sales = sum(x["sales"] for x in retailer_rows)
    total_stock = sum(x["stock"] for x in retailer_rows)
    total_gap = max(total_target - total_sales, 0)
    total_ach = round((total_sales / total_target) * 100, 1) if total_target > 0 else 0
    active_sales = [x for x in retailer_rows if x["sales"] > 0]
    total_scheme_payout = sum(int(x.get("scheme_payout") or 0) for x in retailer_rows)
    total_scheme_units = sum(int(x.get("scheme_eligible_units") or 0) for x in retailer_rows)

    hierarchy = {}
    for field in ("tl", "ss", "rds"):
        groups = {}
        for item in retailer_rows:
            name = item.get(field) or "Unassigned"
            g = groups.setdefault(name, {
                "name": name, "retailers": 0, "target": 0, "sales": 0, "stock": 0,
            })
            g["retailers"] += 1
            g["target"] += item["target"]
            g["sales"] += item["sales"]
            g["stock"] += item["stock"]
        out = []
        for g in groups.values():
            g["achievement_pct"] = round((g["sales"] / g["target"]) * 100, 1) if g["target"] > 0 else 0
            g["gap"] = max(g["target"] - g["sales"], 0)
            out.append(g)
        hierarchy[field] = sorted(out, key=lambda x: x["sales"], reverse=True)

    retailer_rows.sort(key=lambda x: (x["achievement_pct"], -x["sales"]))

    return {
        "period": {
            "month": month,
            "start": today.replace(day=1).isoformat(),
            "end": today.isoformat(),
            "days_remaining": days_remaining,
        },
        "user": {
            "name": user.get("name", "Manager"),
            "role": user.get("role", "MANAGER"),
            "scope": scope,
        },
        "summary": {
            "retailers": len(retailer_rows),
            "target": total_target,
            "sales": total_sales,
            "achievement_pct": total_ach,
            "gap": total_gap,
            "required_per_day": round(total_gap / days_remaining, 1) if total_target > 0 else 0,
            "stock": total_stock,
            "productive_retailers": len(active_sales),
            "zero_sales_retailers": len(retailer_rows) - len(active_sales),
            "scheme_payout": total_scheme_payout,
            "scheme_eligible_units": total_scheme_units,
        },
        "scheme": {
            "name": "Festive Booster Scheme - October 2026",
            "start": FESTIVE_SCHEME_START.isoformat(),
            "end": FESTIVE_SCHEME_END.isoformat(),
            "provisional": True,
            "eligibility_note": "Provisional sales-based payout. Final payout remains subject to upload, activation, pre-activation, MOP and infiltration conditions.",
        },
        "hierarchy": hierarchy,
        "retailers": retailer_rows,
    }


@app.get("/my-target-performance")
def my_target_performance(user: dict = Depends(get_dashboard_user)):
    """TL/SS monthly target vs achievement using assigned retailer targets and live V-Work MTD sales."""
    role = user.get("role")
    if role not in ("TL", "SS"):
        return {
            "available": False,
            "role": role,
            "name": user.get("name"),
            "message": "Target performance is available for TL and SS users.",
        }

    today = date.today()
    month = today.strftime("%Y-%m")
    scope = _scope(user)
    target = crud.get_hierarchy_target_summary(
        month,
        tl=scope.get("tl"),
        ss=scope.get("ss"),
    )
    retailer_codes = set(target.get("retailer_codes") or [])

    params = {
        "startDate": today.replace(day=1).isoformat(),
        "endDate": today.isoformat(),
        "inventoryDate": today.isoformat(),
        "pageSize": 500,
        "maxPages": 100,
    }
    headers = {}
    if VWORK_LIVE_API_KEY:
        headers["X-API-Key"] = VWORK_LIVE_API_KEY

    try:
        with httpx.Client(timeout=httpx.Timeout(240.0, connect=10.0)) as client:
            response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/retailers/priority-data",
                params=params,
                headers=headers,
            )
        response.raise_for_status()
        live_rows = (response.json() or {}).get("retailers") or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Live target achievement unavailable: {exc}") from exc

    achievement_units = sum(
        int(row.get("mtd_sales") or 0)
        for row in live_rows
        if str(row.get("retailer_code") or "").strip().upper() in retailer_codes
    )
    target_volume = int(target.get("target_volume") or 0)
    achievement_pct = round((achievement_units / target_volume) * 100, 1) if target_volume > 0 else 0
    gap = max(target_volume - achievement_units, 0)
    month_days = calendar.monthrange(today.year, today.month)[1]
    days_remaining = max(month_days - today.day + 1, 1)
    required_per_day = round(gap / days_remaining, 1) if target_volume > 0 else 0

    return {
        "available": True,
        "month": month,
        "role": role,
        "name": user.get("name"),
        "target": target_volume,
        "achievement": achievement_units,
        "achievement_pct": achievement_pct,
        "gap": gap,
        "required_per_day": required_per_day,
        "days_remaining": days_remaining,
        "retailers": len(retailer_codes),
    }


@app.get("/visit-priorities")
def visit_priorities(
    limit: int = Query(default=10, ge=1, le=25),
    user: dict = Depends(get_dashboard_user),
):
    """Rank retailers for today's field visit using recency + live sales velocity + Good Phone DOS."""
    scope = _scope(user)
    health_rows = crud.get_retailer_health(
        tl=scope.get("tl"),
        ss=scope.get("ss"),
        rds=scope.get("rds"),
        limit=2000,
    )

    today = date.today()
    params = {
        "startDate": today.replace(day=1).isoformat(),
        "endDate": today.isoformat(),
        "inventoryDate": today.isoformat(),
        "pageSize": 500,
        "maxPages": 100,
    }
    headers = {}
    if VWORK_LIVE_API_KEY:
        headers["X-API-Key"] = VWORK_LIVE_API_KEY

    try:
        with httpx.Client(timeout=httpx.Timeout(240.0, connect=10.0)) as client:
            response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/retailers/priority-data",
                params=params,
                headers=headers,
            )
        response.raise_for_status()
        live_rows = (response.json() or {}).get("retailers") or []
    except Exception:
        live_rows = []

    live_by_code = {
        str(r.get("retailer_code") or "").strip().upper(): r
        for r in live_rows
        if r.get("retailer_code")
    }

    ranked = []
    for row in health_rows:
        code = str(row.get("code") or "").strip().upper()
        live = live_by_code.get(code, {})
        days = row.get("days_since_visit")
        avg_daily = float(live.get("avg_daily_sales") or 0)
        dos = live.get("dos")
        stock = int(live.get("good_phone_stock") or 0)
        sales = int(live.get("mtd_sales") or 0)

        if days is None:
            recency_score = 50
        elif days >= 30:
            recency_score = 50
        elif days >= 15:
            recency_score = 40
        elif days >= 8:
            recency_score = 25
        else:
            recency_score = min(20, max(0, int(days) * 2))

        if sales > 0 and stock == 0:
            dos_score = 30
            stock_signal = "Out of stock"
        elif isinstance(dos, (int, float)) and dos < 7:
            dos_score = 30
            stock_signal = "Low stock"
        elif isinstance(dos, (int, float)) and dos > 45:
            dos_score = 25
            stock_signal = "High stock"
        elif isinstance(dos, (int, float)) and dos > 30:
            dos_score = 15
            stock_signal = "Elevated stock"
        else:
            dos_score = 0
            stock_signal = "Stock balanced"

        if avg_daily >= 5:
            velocity_score = 20
        elif avg_daily >= 2:
            velocity_score = 15
        elif avg_daily >= 1:
            velocity_score = 10
        elif avg_daily > 0:
            velocity_score = 5
        else:
            velocity_score = 0

        reasons = []
        if days is None:
            reasons.append("Never visited")
        elif days >= 15:
            reasons.append(f"{days} days since last visit")
        elif days >= 8:
            reasons.append(f"Follow-up due after {days} days")
        if stock_signal != "Stock balanced":
            reasons.append(stock_signal)
        if avg_daily >= 2:
            reasons.append(f"Strong velocity {avg_daily:.1f}/day")
        elif sales == 0:
            reasons.append("No MTD sales")

        ranked.append({
            "retailer_code": code,
            "retailer": row.get("name"),
            "zone": row.get("zone"),
            "club": row.get("club"),
            "rds": row.get("rds"),
            "last_visit": row.get("last_visit"),
            "days_since_visit": days,
            "mtd_sales": sales,
            "avg_daily_sales": avg_daily,
            "good_phone_stock": stock,
            "dos": dos,
            "priority_score": recency_score + dos_score + velocity_score,
            "reason": " · ".join(reasons[:3]) or "Routine coverage",
        })

    ranked.sort(key=lambda x: (x["priority_score"], x["avg_daily_sales"]), reverse=True)
    return ranked[:limit]


@app.get("/retailer-health", response_model=List[RetailerHealthOut])
def retailer_health(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                    zone: Optional[str] = None, priority: Optional[str] = None,
                    limit: int = Query(default=500, ge=1, le=2000), user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    if scope: tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.get_retailer_health(tl=tl, ss=ss, rds=rds, zone=zone, priority=priority, limit=limit)
