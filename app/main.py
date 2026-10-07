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
    DailyRetailerRemarkCreate,
    LoginOut,
    PinLoginRequest,
    LoginRequest,
    PasswordResetOut,
    RetailerHealthOut,
    RetailerOut,
    StatsOut,
    UserOut,
    UserStatusOut,
    WhatsappNumberUpdate,
    WhatsappNotificationLogCreate,
    VisitCreate,
    VisitOut, PhotoOut,
)
app = FastAPI(title="Market Visit Tracker API", description="GTM retailer visits, coverage and field intelligence.", version="2.1.0")

VWORK_LIVE_API_URL = os.getenv("VWORK_LIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")
VWORK_LIVE_API_KEY = os.getenv("VWORK_LIVE_API_KEY", "").strip()
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID", "").strip()
WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0").strip() or "v26.0"
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "zone_a_incentive_update_v2").strip() or "zone_a_incentive_update_v2"
WHATSAPP_TEMPLATE_LANGUAGE = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en").strip() or "en"
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).resolve().parent / "static"

def _normalize_whatsapp_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) != 12 or not digits.startswith("91"):
        raise HTTPException(status_code=400, detail="Use a valid Indian WhatsApp number, e.g. +919876543210.")
    return "+" + digits


def _format_inr(value) -> str:
    try:
        return "₹" + format(int(round(float(value or 0))), ",")
    except Exception:
        return "₹0"


def _whatsapp_configured() -> bool:
    return bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)


def _whatsapp_headers() -> dict:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _whatsapp_template_body_text() -> str:
    return (
        "vivo NESA Zone A - October 2026 Update\n"
        "{{1}}: {{2}}\n"
        "Target: {{3}} units\n"
        "MTD Achievement: {{4}} units ({{5}}%)\n"
        "Gap: {{6}} units\n"
        "Required / Day: {{7}}\n"
        "{{13}}\n\n"
        "Provisional Incentive Summary\n"
        "Festive Booster: {{8}}\n"
        "Focus Model: {{9}}\n"
        "V80 Normal: {{10}}\n"
        "Back Support (known): {{11}}\n"
        "Total Known / Provisional: {{12}}\n\n"
        "Final payout remains subject to scheme eligibility and compliance conditions."
    )




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
    safe_user = {k: user.get(k) for k in ("id", "name", "role", "tl", "ss", "rds", "kam", "active")}
    return {"access_token": token, "token_type": "bearer", "user": safe_user}


@app.get("/auth/pin-users", include_in_schema=False)
def pin_users():
    rows = crud.list_users_admin()
    return {
        "TL": sorted([r["name"] for r in rows if r["role"] == "TL"]),
        "SS": sorted([r["name"] for r in rows if r["role"] == "SS"]),
        "KAM": sorted([r["name"] for r in rows if r["role"] == "KAM"]),
    }


@app.post("/auth/pin-login", response_model=LoginOut)
def pin_login(payload: PinLoginRequest):
    user = crud.get_user_by_pin(payload.pin)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid PIN.")
    token = create_token(user)
    safe_user = {k: user.get(k) for k in ("id", "name", "role", "tl", "ss", "rds", "kam", "active")}
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
    if role == "KAM":
        return {"kam": name}

    return {}


def _record_matches_scope(record: dict, scope: dict) -> bool:
    if not scope:
        return True
    for key, value in scope.items():
        if key == "kam":
            if record.get("kam") == value:
                continue
            retailer_name = record.get("retailer") or record.get("name")
            if not retailer_name:
                return False
            retailer = crud.lookup_retailer_by_name(str(retailer_name))
            if not retailer or retailer.get("kam") != value:
                return False
        elif record.get(key) != value:
            return False
    return True



def _require_kam(user: dict) -> dict:
    if str(user.get("role") or "").upper() != "KAM":
        raise HTTPException(status_code=403, detail="KAM access required.")
    return user


@app.post("/visits", response_model=VisitOut)
def create_visit(payload: VisitCreate, user: dict = Depends(get_current_user)):
    scope = _scope(user)
    retailer = crud.lookup_retailer_by_name(payload.retailer)
    if not retailer:
        raise HTTPException(status_code=400, detail="Retailer is not in the master list.")
    if scope and not _record_matches_scope(retailer, scope):
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
    kam = scope.get("kam") if scope else None
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
        submitted_by = None
    return crud.list_visits(retailer=retailer, tl=tl, ss=ss, rds=rds, kam=kam, submitted_by=submitted_by,
                            submitted_role=submitted_role, date_from=date_from, date_to=date_to,
                            search=search, limit=limit, offset=offset)


@app.get("/retailers", response_model=List[RetailerOut])
def get_retailers(tl: Optional[str] = None, ss: Optional[str] = None, rds: Optional[str] = None,
                  search: Optional[str] = None, user: dict = Depends(get_dashboard_user)):
    scope = _scope(user)
    kam = scope.get("kam") if scope else None
    if scope:
        tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.list_retailers(tl=tl, ss=ss, rds=rds, kam=kam, search=search)


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
    if scope and not _record_matches_scope(visit, scope):
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
        tl=scope.get("tl"), ss=scope.get("ss"), rds=scope.get("rds"), kam=scope.get("kam"), limit=10000
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
        ("Focus Model Provisional Payout", summary.get("focus_scheme_payout", 0)),
        ("V80 Normal Sales Provisional Payout", summary.get("v80_normal_sales_payout", 0)),
        ("V80 Maximum Conditional Payout", summary.get("v80_max_total_payout", 0)),
        ("Back Support Base Margin", summary.get("back_support_base_margin", 0)),
        ("Back Support Known Payable", summary.get("back_support_payable_known", 0)),
        ("Scope", "Full Zone A" if user.get("role") == "MANAGER" else f"{user.get('role')} hierarchy only"),
    ]
    for row in rows:
        ws.append(row)
    finish(ws)

    ws = wb.create_sheet("Retailer Performance")
    ws.append(["Retailer Code","Retailer","Town","District","TL","SS","RDS","Zone","Club","Target","MTD Sales","Achievement %","Gap","Required / Day","Stock","Avg / Day","DOS","Festive Type","Festive Slab","Festive Eligible Units","Festive Payout","Focus Eligible Units","Focus Payout","V80 Units","V80 Slab","V80 Normal Payout","V80 Max Conditional Payout","Back Support Base Margin","Back Support Payable","Back Support Achievement %","Back Support Eligibility","Last Visit","Days Since Visit","Visit Count","Status"])
    for x in perf.get("retailers", []):
        ws.append([x.get("code"),x.get("name"),x.get("town_name"),x.get("district_name"),x.get("tl"),x.get("ss"),x.get("rds"),x.get("zone"),x.get("club"),x.get("target"),x.get("sales"),x.get("achievement_pct"),x.get("gap"),x.get("required_per_day"),x.get("stock"),x.get("avg_daily_sales"),x.get("dos"),x.get("scheme_type"),x.get("scheme_slab"),x.get("scheme_eligible_units"),x.get("scheme_payout"),x.get("focus_scheme_units"),x.get("focus_scheme_payout"),x.get("v80_units"),x.get("v80_slab"),x.get("v80_normal_sales_payout"),x.get("v80_max_total_payout"),x.get("back_support_base_margin"),x.get("back_support_payable"),x.get("back_support_achievement_pct"),x.get("back_support_eligibility"),x.get("last_visit"),x.get("days_since_visit"),x.get("visit_count"),x.get("status")])
    finish(ws)

    ws = wb.create_sheet("Visit History")
    ws.append(["Visit ID","Visit Date","Retailer","Market","TL","SS","RDS","Submitted By","Role","Latitude","Longitude","GPS Accuracy","Photos","Feedback","Suggestions","Created At"])
    for x in visits:
        ws.append([x.get("id"),x.get("visit_date"),x.get("retailer"),x.get("market"),x.get("tl"),x.get("ss"),x.get("rds"),x.get("submitted_by"),x.get("submitted_role"),x.get("latitude"),x.get("longitude"),x.get("gps_accuracy"),x.get("photo_count"),x.get("feedback"),x.get("suggestions"),x.get("created_at")])
    finish(ws)

    for key, title in (("tl","TL Summary"),("ss","SS Summary"),("rds","RDS Summary")):
        ws = wb.create_sheet(title)
        ws.append(["Name","Retailers","Target","MTD Sales","Achievement %","Gap","Stock","Festive Payout","Focus Payout","V80 Normal Payout","Back Support Known","Total Known Payout"])
        for x in perf.get("hierarchy", {}).get(key, []):
            ws.append([x.get("name"),x.get("retailers"),x.get("target"),x.get("sales"),x.get("achievement_pct"),x.get("gap"),x.get("stock"),x.get("festive_payout"),x.get("focus_payout"),x.get("v80_normal_payout"),x.get("back_support_known"),x.get("total_known_payout")])
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
    kam = scope.get("kam") if scope else None
    if scope: tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    rows = crud.list_visits(tl=tl, ss=ss, rds=rds, kam=kam, date_from=date_from, date_to=date_to, limit=2000)
    buffer = io.StringIO(); writer = csv.writer(buffer)
    writer.writerow(["id", "visit_date", "retailer", "tl", "ss", "rds", "market", "feedback", "suggestions", "submitted_by", "submitted_role", "created_at"])
    for r in rows:
        writer.writerow([r["id"], r["visit_date"], r["retailer"], r["tl"], r["ss"], r["rds"], r["market"], r["feedback"], r["suggestions"], r["submitted_by"], r["submitted_role"], r["created_at"]])
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=market-visits.csv"})


@app.get("/users", response_model=List[UserOut])
def get_users(role: Optional[str] = Query(default=None, pattern="^(TL|SS|RDS|KAM)$"), user: dict = Depends(get_current_user)):
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


@app.patch("/admin/users/{user_id}/whatsapp", dependencies=[Depends(require_admin_key)])
def admin_update_whatsapp(user_id: int, payload: WhatsappNumberUpdate):
    number = _normalize_whatsapp_number(payload.whatsapp_number)
    result = crud.update_user_whatsapp_number(user_id, number)
    if not result:
        raise HTTPException(status_code=404, detail="User not found.")
    return result


@app.get("/admin/whatsapp/preview", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_preview(user_id: int = Query(..., ge=1)):
    target_user = crud.get_user_admin(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
    if target_user.get("role") not in ("TL", "SS", "RDS"):
        raise HTTPException(status_code=400, detail="WhatsApp preview is limited to TL, SS and RDS.")

    scoped_user = {
        "name": target_user.get("name"),
        "role": target_user.get("role"),
        "tl": target_user.get("tl"),
        "ss": target_user.get("ss"),
        "rds": target_user.get("rds"),
        "active": target_user.get("active", True),
    }
    perf = performance_dashboard(scoped_user)
    summary = perf.get("summary") or {}
    target = int(summary.get("target") or 0)
    sales = int(summary.get("sales") or 0)
    ach = float(summary.get("achievement_pct") or 0)
    gap = int(summary.get("gap") or 0)
    req = summary.get("required_per_day") or 0
    festive = int(summary.get("scheme_payout") or 0)
    focus = int(summary.get("focus_scheme_payout") or 0)
    v80 = int(summary.get("v80_normal_sales_payout") or 0)
    back = int(summary.get("back_support_payable_known") or 0)
    total_known = festive + focus + v80 + back

    zero_sales_rows = [
        row for row in (perf.get("retailers") or [])
        if int(row.get("sales") or 0) == 0
    ]
    zero_sales_count = len(zero_sales_rows)
    zero_sales_names = [str(row.get("name") or "").strip() for row in zero_sales_rows if row.get("name")]
    if target_user.get("role") in ("TL", "SS"):
        zero_sales_line = f"Zero Sales Retailers: {zero_sales_count}"
        zero_sales_detail = ", ".join(zero_sales_names) if zero_sales_names else "None"
    else:
        zero_sales_line = "Zero Sales Retailers: Not applicable"
        zero_sales_detail = ""

    lines = [
        "vivo NESA Zone A - October 2026 Update",
        f"{target_user.get('role')}: {target_user.get('name')}",
        "",
        f"Target: {target:,} units",
        f"MTD Achievement: {sales:,} units ({ach:.1f}%)",
        f"Gap: {gap:,} units",
        f"Required / Day: {round(float(req),1)}",
        zero_sales_line,
        *([f"Zero Sales Retailer List: {zero_sales_detail}"] if zero_sales_detail else []),
        "",
        "Provisional Incentive Summary",
        f"Festive Booster: {_format_inr(festive)}",
        f"Focus Model: {_format_inr(focus)}",
        f"V80 Normal: {_format_inr(v80)}",
        f"Back Support (known): {_format_inr(back)}",
        f"Total Known / Provisional: {_format_inr(total_known)}",
        "",
        "Final payout remains subject to scheme eligibility and compliance conditions.",
    ]
    template_parameters = [
        str(target_user.get("role") or ""),
        str(target_user.get("name") or ""),
        f"{target:,}",
        f"{sales:,}",
        f"{ach:.1f}",
        f"{gap:,}",
        str(round(float(req), 1)),
        _format_inr(festive),
        _format_inr(focus),
        _format_inr(v80),
        _format_inr(back),
        _format_inr(total_known),
        zero_sales_line if not zero_sales_detail else f"{zero_sales_line} | {zero_sales_detail}",
    ]
    return {
        "user_id": target_user.get("id"),
        "name": target_user.get("name"),
        "role": target_user.get("role"),
        "whatsapp_number": target_user.get("whatsapp_number"),
        "message": "\n".join(lines),
        "template_parameters": template_parameters,
        "template_name": WHATSAPP_TEMPLATE_NAME,
        "template_language": WHATSAPP_TEMPLATE_LANGUAGE,
        "connected": _whatsapp_configured(),
        "send_status": "WhatsApp Cloud API configured." if _whatsapp_configured() else "WhatsApp Business integration not connected yet.",
    }


@app.get("/admin/whatsapp/status", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_status():
    configured = _whatsapp_configured()
    template_status = "UNKNOWN"
    template_error = None
    if configured and WHATSAPP_WABA_ID:
        try:
            url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_VERSION}/{WHATSAPP_WABA_ID}/message_templates"
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = client.get(
                    url,
                    params={"name": WHATSAPP_TEMPLATE_NAME, "limit": 10},
                    headers=_whatsapp_headers(),
                )
            response.raise_for_status()
            rows = (response.json() or {}).get("data") or []
            match = next((x for x in rows if x.get("name") == WHATSAPP_TEMPLATE_NAME), None)
            template_status = str((match or {}).get("status") or "NOT_FOUND")
        except Exception as exc:
            template_status = "CHECK_FAILED"
            template_error = str(exc)[:240]
    elif not WHATSAPP_WABA_ID:
        template_status = "WABA_ID_MISSING"

    return {
        "configured": configured,
        "phone_number_id_configured": bool(WHATSAPP_PHONE_NUMBER_ID),
        "access_token_configured": bool(WHATSAPP_ACCESS_TOKEN),
        "waba_id_configured": bool(WHATSAPP_WABA_ID),
        "template_name": WHATSAPP_TEMPLATE_NAME,
        "template_language": WHATSAPP_TEMPLATE_LANGUAGE,
        "template_status": template_status,
        "template_error": template_error,
        "can_send": bool(configured and template_status in ("APPROVED", "ACTIVE")),
    }


@app.post("/admin/whatsapp/template/submit", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_template_submit():
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_WABA_ID:
        raise HTTPException(
            status_code=503,
            detail="WHATSAPP_ACCESS_TOKEN and WHATSAPP_WABA_ID must be configured in Render.",
        )
    payload = {
        "name": WHATSAPP_TEMPLATE_NAME,
        "language": WHATSAPP_TEMPLATE_LANGUAGE,
        "category": "UTILITY",
        "components": [{
            "type": "BODY",
            "text": _whatsapp_template_body_text(),
            "example": {
                "body_text": [[
                    "TL", "Example Name", "1,000", "450", "45.0", "550", "22.0",
                    "₹12,000", "₹8,000", "₹3,000", "₹4,500", "₹27,500",
                    "Zero Sales Retailers: 3 | Retailer A, Retailer B, Retailer C"
                ]]
            },
        }],
    }
    url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_VERSION}/{WHATSAPP_WABA_ID}/message_templates"
    try:
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = client.post(url, json=payload, headers=_whatsapp_headers())
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            detail = ((data or {}).get("error") or {}).get("message") or f"Meta API error {response.status_code}"
            raise HTTPException(status_code=502, detail=detail)
        return {
            "submitted": True,
            "template_name": WHATSAPP_TEMPLATE_NAME,
            "meta_response": data,
            "message": "Template submitted to Meta for review.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Template submission failed: {exc}") from exc


@app.post("/admin/whatsapp/send", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_send(user_id: int = Query(..., ge=1)):
    if not _whatsapp_configured():
        raise HTTPException(
            status_code=503,
            detail="WhatsApp Cloud API credentials are not configured in Render.",
        )

    preview = admin_whatsapp_preview(user_id)
    number = _normalize_whatsapp_number(preview.get("whatsapp_number"))
    if not number:
        raise HTTPException(status_code=400, detail="Recipient WhatsApp number is missing.")

    payload = {
        "messaging_product": "whatsapp",
        "to": number.lstrip("+"),
        "type": "template",
        "template": {
            "name": WHATSAPP_TEMPLATE_NAME,
            "language": {"code": WHATSAPP_TEMPLATE_LANGUAGE},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(value)}
                    for value in (preview.get("template_parameters") or [])
                ],
            }],
        },
    }
    url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    try:
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = client.post(url, json=payload, headers=_whatsapp_headers())
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            detail = ((data or {}).get("error") or {}).get("message") or f"Meta API error {response.status_code}"
            crud.create_whatsapp_notification_log(
                user_id,
                preview.get("message") or "",
                "FAILED",
                error_detail=detail,
            )
            raise HTTPException(status_code=502, detail=detail)

        messages = (data or {}).get("messages") or []
        message_id = messages[0].get("id") if messages else None
        log = crud.create_whatsapp_notification_log(
            user_id,
            preview.get("message") or "",
            "SUBMITTED",
            provider_message_id=message_id,
        )
        return {
            "sent": True,
            "status": "SUBMITTED",
            "provider_message_id": message_id,
            "recipient": preview.get("name"),
            "whatsapp_number": number,
            "log": log,
        }
    except HTTPException:
        raise
    except Exception as exc:
        detail = str(exc)[:400]
        crud.create_whatsapp_notification_log(
            user_id,
            preview.get("message") or "",
            "FAILED",
            error_detail=detail,
        )
        raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {detail}") from exc


@app.get("/kam/whatsapp/recipients")
def kam_whatsapp_recipients(
    role: Optional[str] = Query(default=None, pattern="^(TL|SS)$"),
    user: dict = Depends(get_current_user),
):
    _require_kam(user)
    return crud.list_kam_whatsapp_recipients(str(user.get("name") or ""), role=role)


@app.get("/kam/whatsapp/preview")
def kam_whatsapp_preview(
    user_id: int = Query(..., ge=1),
    user: dict = Depends(get_current_user),
):
    _require_kam(user)
    kam_name = str(user.get("name") or "")
    if not crud.kam_can_message_user(kam_name, user_id):
        raise HTTPException(status_code=403, detail="This TL/SS is outside your KAM hierarchy.")
    return admin_whatsapp_preview(user_id)


@app.get("/kam/whatsapp/status")
def kam_whatsapp_status(user: dict = Depends(get_current_user)):
    _require_kam(user)
    return admin_whatsapp_status()


@app.post("/kam/whatsapp/send")
def kam_whatsapp_send(
    user_id: int = Query(..., ge=1),
    user: dict = Depends(get_current_user),
):
    _require_kam(user)
    kam_name = str(user.get("name") or "")
    if not crud.kam_can_message_user(kam_name, user_id):
        raise HTTPException(status_code=403, detail="This TL/SS is outside your KAM hierarchy.")
    return admin_whatsapp_send(user_id)


@app.post("/kam/whatsapp/send-all")
def kam_whatsapp_send_all(
    role: str = Query(default="ALL", pattern="^(ALL|TL|SS)$"),
    user: dict = Depends(get_current_user),
):
    _require_kam(user)
    kam_name = str(user.get("name") or "")
    role_filter = None if role == "ALL" else role
    recipients = crud.list_kam_whatsapp_recipients(kam_name, role=role_filter)

    results = []
    sent = 0
    skipped = 0
    failed = 0
    for recipient in recipients:
        if not recipient.get("whatsapp_number"):
            skipped += 1
            results.append({
                "user_id": recipient.get("id"),
                "name": recipient.get("name"),
                "role": recipient.get("role"),
                "status": "SKIPPED_NO_NUMBER",
            })
            continue
        try:
            result = admin_whatsapp_send(int(recipient["id"]))
            sent += 1
            results.append({
                "user_id": recipient.get("id"),
                "name": recipient.get("name"),
                "role": recipient.get("role"),
                "status": result.get("status") or "SUBMITTED",
                "provider_message_id": result.get("provider_message_id"),
            })
        except HTTPException as exc:
            failed += 1
            results.append({
                "user_id": recipient.get("id"),
                "name": recipient.get("name"),
                "role": recipient.get("role"),
                "status": "FAILED",
                "detail": str(exc.detail),
            })

    return {
        "kam": kam_name,
        "role_filter": role,
        "total_recipients": len(recipients),
        "submitted": sent,
        "skipped_no_number": skipped,
        "failed": failed,
        "results": results,
    }


@app.post("/admin/whatsapp/log", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_log(payload: WhatsappNotificationLogCreate):
    status = str(payload.status or "PREVIEWED").upper()
    if status not in ("PREVIEWED", "READY", "NOT_CONNECTED", "SUBMITTED", "FAILED"):
        raise HTTPException(status_code=400, detail="Unsupported notification status.")
    row = crud.create_whatsapp_notification_log(payload.user_id, payload.preview_text, status)
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


@app.get("/admin/whatsapp/logs", dependencies=[Depends(require_admin_key)])
def admin_whatsapp_logs(limit: int = Query(default=25, ge=1, le=100)):
    return crud.list_whatsapp_notification_logs(limit=limit)


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

    scope = _scope(user)
    rows = crud.get_coverage(group_by, kam=scope.get("kam"))

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
        kam=scope.get("kam"),
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
    """Hierarchy-aware retailer performance for TL, SS, RDS, KAM and management."""
    today = date.today()
    month = today.strftime("%Y-%m")
    scope = _scope(user)
    rows = crud.get_performance_scope_rows(
        month,
        tl=scope.get("tl"),
        ss=scope.get("ss"),
        rds=scope.get("rds"),
        kam=scope.get("kam"),
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
            additional_response = client.get(
                f"{VWORK_LIVE_API_URL}/api/v1/schemes/october-additional-sales",
                headers=headers,
            )
        response.raise_for_status()
        scheme_response.raise_for_status()
        additional_response.raise_for_status()
        live_rows = (response.json() or {}).get("retailers") or []
        scheme_payload = scheme_response.json() or {}
        scheme_rows = scheme_payload.get("retailers") or []
        additional_payload = additional_response.json() or {}
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

    focus_by_code = {
        str(x.get("retailer_code") or "").strip().upper(): x
        for x in ((additional_payload.get("focus_model") or {}).get("retailers") or [])
        if x.get("retailer_code")
    }
    v80_by_code = {
        str(x.get("retailer_code") or "").strip().upper(): x
        for x in ((additional_payload.get("v80_npl") or {}).get("retailers") or [])
        if x.get("retailer_code")
    }
    back_by_code = {
        str(x.get("retailer_code") or "").strip().upper(): x
        for x in ((additional_payload.get("back_support") or {}).get("retailers") or [])
        if x.get("retailer_code")
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
        focus_scheme = _focus_model_payout(focus_by_code.get(code, {}))
        v80_scheme = _v80_npl_payout(v80_by_code.get(code, {}))
        back_support = _back_support_estimate(row.get("club"), row.get("target_value"), back_by_code.get(code, {}))
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
            "kam": row.get("kam"),
            "zone": row.get("zone"),
            "club": row.get("club"),
            "town_name": row.get("town_name"),
            "district_name": row.get("district_name"),
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
            "focus_scheme_units": focus_scheme.get("eligible_units"),
            "focus_scheme_payout": focus_scheme.get("payout"),
            "focus_scheme_detail": focus_scheme.get("detail"),
            "v80_units": v80_scheme.get("units"),
            "v80_slab": v80_scheme.get("slab"),
            "v80_normal_sales_payout": v80_scheme.get("normal_sales_payout"),
            "v80_max_total_payout": v80_scheme.get("max_total_payout"),
            "back_support_base_margin": back_support.get("base_margin"),
            "back_support_payable": back_support.get("provisional_payable"),
            "back_support_achievement_pct": back_support.get("achievement_pct_value"),
            "back_support_eligibility": back_support.get("eligibility"),
            "back_support_unknown_value_units": back_support.get("unknown_value_units"),
        })

    total_target = sum(x["target"] for x in retailer_rows)
    total_sales = sum(x["sales"] for x in retailer_rows)

    explicit_summary_target = None
    role = str(user.get("role") or "MANAGER").upper()
    if role == "MANAGER":
        explicit_summary_target = crud.get_explicit_hierarchy_target(month, "ZONE", "Zone A")
    elif role in ("TL", "SS", "RDS"):
        explicit_summary_target = crud.get_explicit_hierarchy_target(
            month, role, str(user.get("name") or "")
        )
    if explicit_summary_target:
        total_target = int(explicit_summary_target.get("target_volume") or 0)
    total_stock = sum(x["stock"] for x in retailer_rows)
    total_gap = max(total_target - total_sales, 0)
    total_ach = round((total_sales / total_target) * 100, 1) if total_target > 0 else 0
    active_sales = [x for x in retailer_rows if x["sales"] > 0]
    total_scheme_payout = sum(int(x.get("scheme_payout") or 0) for x in retailer_rows)
    total_scheme_units = sum(int(x.get("scheme_eligible_units") or 0) for x in retailer_rows)
    total_focus_payout = sum(int(x.get("focus_scheme_payout") or 0) for x in retailer_rows)
    total_v80_normal = sum(int(x.get("v80_normal_sales_payout") or 0) for x in retailer_rows)
    total_v80_max = sum(int(x.get("v80_max_total_payout") or 0) for x in retailer_rows)
    total_back_base = sum(int(x.get("back_support_base_margin") or 0) for x in retailer_rows)
    total_back_payable = sum(int(x.get("back_support_payable") or 0) for x in retailer_rows if x.get("back_support_payable") is not None)

    hierarchy = {}
    for field in ("tl", "ss", "rds"):
        explicit_targets = crud.list_explicit_hierarchy_targets(month, field.upper())
        groups = {}
        for item in retailer_rows:
            name = item.get(field) or "Unassigned"
            g = groups.setdefault(name, {
                "name": name, "retailers": 0, "target": 0, "sales": 0, "stock": 0,
                "festive_payout": 0, "focus_payout": 0, "v80_normal_payout": 0,
                "back_support_known": 0,
            })
            g["retailers"] += 1
            g["target"] += item["target"]
            g["sales"] += item["sales"]
            g["stock"] += item["stock"]
            g["festive_payout"] += int(item.get("scheme_payout") or 0)
            g["focus_payout"] += int(item.get("focus_scheme_payout") or 0)
            g["v80_normal_payout"] += int(item.get("v80_normal_sales_payout") or 0)
            if item.get("back_support_payable") is not None:
                g["back_support_known"] += int(item.get("back_support_payable") or 0)
        out = []
        for g in groups.values():
            explicit = explicit_targets.get(g["name"])
            if explicit:
                g["target"] = int(explicit.get("target_volume") or 0)
                g["target_value"] = int(explicit.get("target_value") or 0)
            g["achievement_pct"] = round((g["sales"] / g["target"]) * 100, 1) if g["target"] > 0 else 0
            g["gap"] = max(g["target"] - g["sales"], 0)
            g["total_known_payout"] = g["festive_payout"] + g["focus_payout"] + g["v80_normal_payout"] + g["back_support_known"]
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
            "focus_scheme_payout": total_focus_payout,
            "v80_normal_sales_payout": total_v80_normal,
            "v80_max_total_payout": total_v80_max,
            "back_support_base_margin": total_back_base,
            "back_support_payable_known": total_back_payable,
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
    if role not in ("TL", "SS", "RDS"):
        return {
            "available": False,
            "role": role,
            "name": user.get("name"),
            "message": "Target performance is available for TL, SS and RDS users.",
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
    explicit_target = crud.get_explicit_hierarchy_target(month, role, str(user.get("name") or ""))

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
    target_volume = int(
        (explicit_target or {}).get("target_volume")
        if explicit_target is not None
        else target.get("target_volume") or 0
    )
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


@app.get("/eod-remarks/retailers")
def eod_remark_retailers(user: dict = Depends(get_current_user)):
    role = str(user.get("role") or "").upper()
    if role not in ("TL", "SS", "RDS"):
        raise HTTPException(status_code=403, detail="EOD remarks are available to TL, SS and RDS users.")

    perf = performance_dashboard(user)
    today = date.today().isoformat()
    existing = {
        str(row.get("retailer_code") or "").strip().upper(): row
        for row in crud.list_daily_retailer_remarks(
            today,
            submitted_by=str(user.get("name") or ""),
            submitted_role=role,
        )
    }

    rows = []
    for row in (perf.get("retailers") or []):
        sales = int(row.get("sales") or 0)
        ach = float(row.get("achievement_pct") or 0)
        target = int(row.get("target") or 0)
        if sales == 0 or (target > 0 and ach < 50):
            code = str(row.get("code") or "").strip().upper()
            saved = existing.get(code) or {}
            rows.append({
                "code": code,
                "name": row.get("name"),
                "sales": sales,
                "target": target,
                "achievement_pct": ach,
                "remark": saved.get("remark") or "",
                "updated_at": saved.get("updated_at"),
            })

    rows.sort(key=lambda x: (x["sales"], x["achievement_pct"], str(x["name"] or "")))
    return {
        "date": today,
        "role": role,
        "name": user.get("name"),
        "count": len(rows),
        "retailers": rows,
    }


@app.post("/eod-remarks")
def save_eod_remark(payload: DailyRetailerRemarkCreate, user: dict = Depends(get_current_user)):
    role = str(user.get("role") or "").upper()
    if role not in ("TL", "SS", "RDS"):
        raise HTTPException(status_code=403, detail="EOD remarks are available to TL, SS and RDS users.")

    code = str(payload.retailer_code or "").strip().upper()
    retailer = crud.lookup_retailer_by_code(code)
    if not retailer:
        raise HTTPException(status_code=404, detail="Retailer not found.")

    scope = _scope(user)
    if scope and any(retailer.get(k) != v for k, v in scope.items()):
        raise HTTPException(status_code=403, detail="Retailer is outside your hierarchy.")

    perf = performance_dashboard(user)
    perf_row = next(
        (
            row for row in (perf.get("retailers") or [])
            if str(row.get("code") or "").strip().upper() == code
        ),
        None,
    )
    if not perf_row:
        raise HTTPException(status_code=404, detail="Retailer performance is unavailable.")

    sales = int(perf_row.get("sales") or 0)
    target = int(perf_row.get("target") or 0)
    ach = float(perf_row.get("achievement_pct") or 0)
    if not (sales == 0 or (target > 0 and ach < 50)):
        raise HTTPException(status_code=400, detail="Remarks can only be submitted for low-sale retailers.")

    return crud.upsert_daily_retailer_remark(
        remark_date=date.today().isoformat(),
        retailer_code=code,
        retailer_name=str(retailer.get("name") or perf_row.get("name") or ""),
        submitted_by=str(user.get("name") or ""),
        submitted_role=role,
        remark=str(payload.remark).strip(),
    )


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
        kam=scope.get("kam"),
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
    kam = scope.get("kam") if scope else None
    if scope: tl, ss, rds = scope.get("tl"), scope.get("ss"), scope.get("rds")
    return crud.get_retailer_health(tl=tl, ss=ss, rds=rds, kam=kam, zone=zone, priority=priority, limit=limit)
