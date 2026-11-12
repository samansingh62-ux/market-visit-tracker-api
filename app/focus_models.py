"""Focus-model target vs achievement (November 2026 focus variants).

Targets come from the month's tertiary dashboard (focus_targets_YYYY-MM.json); sales and stock come
live from vwork-live-api /api/v1/focus-variants for the user's territory. A VBA's sales are the
sales at the store they are posted to: V-Work's sales feed does not say which VBA uploaded a sale.
"""
import json
from datetime import date
from pathlib import Path

from .alignment import alignment, canonical_name

_DIR = Path(__file__).parent


def load_targets(month: str):
    path = _DIR / f"focus_targets_{month}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _canon_map(d):
    return {canonical_name(k): v for k, v in (d or {}).items()}


def scope_retailers(scope: dict) -> set:
    codes = set()
    for code in alignment.store_codes(scope=scope):
        codes.add(str(alignment.stores[str(code).upper()]["retailer_code"]).upper())
    return codes


def scope_target(targets: dict, role: str, name: str, scope: dict) -> dict:
    """The focus-model targets of the user's own level."""
    models = targets["models"]
    role = (role or "").upper()
    level = {"KAM": "KAM", "SS": "SS", "TL": "TL"}.get(role)
    if not scope:
        return dict(targets.get("ZONE") or {})
    if level:
        own = _canon_map(targets.get(level)).get(canonical_name(name))
        if own:
            return dict(own)
    # RDS, or a name missing from the sheet: add up the counters in the area.
    out = {m: 0 for m in models}
    for code in scope_retailers(scope):
        for m, v in (targets["retailers"].get(code) or {}).items():
            out[m] = out.get(m, 0) + int(v or 0)
    return out


def summary(targets: dict, live: dict, role: str, name: str, scope: dict, today: date) -> dict:
    tgt = scope_target(targets, role, name, scope)
    import calendar
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = days_in_month - today.day + 1
    rows = []
    for m in targets["models"]:
        v = (live.get("variants") or {}).get(m) or {}
        t, mtd = int(tgt.get(m) or 0), int(v.get("mtd") or 0)
        rows.append({"variant": m, "target": t, "mtd": mtd, "ftd": int(v.get("ftd") or 0), "stock": int(v.get("stock") or 0),
                     "pct": round(mtd * 100 / t, 1) if t else None,
                     "per_day_needed": round(max(t - mtd, 0) / days_left, 1) if t else None})
    tt, tm = sum(r["target"] for r in rows), sum(r["mtd"] for r in rows)
    return {"as_of": live.get("as_of"), "days_left": days_left, "expected_pct": round((today.day - 1) * 100 / days_in_month, 1),
            "models": rows, "total": {"target": tt, "mtd": tm, "ftd": sum(r["ftd"] for r in rows),
                                      "pct": round(tm * 100 / tt, 1) if tt else None}}


def detail(targets: dict, live: dict, variant: str, scope: dict) -> dict:
    """Counters not moving the variant, and VBAs with nothing sold this month or today."""
    counters = {c["code"]: c for c in live.get("counters") or []}
    in_scope = scope_retailers(scope) if scope else set(alignment.retailers)
    not_moving, no_stock = [], []
    for code in sorted(in_scope | {c for c in counters if not scope}):
        cv = ((counters.get(code) or {}).get("variants") or {}).get(variant) or {}
        tgt = int(((targets["retailers"].get(code) or {}).get(variant)) or 0)
        stock, mtd = int(cv.get("stock") or 0), int(cv.get("mtd") or 0)
        if mtd:
            continue
        a = (alignment.retailers.get(code) or [{}])
        info = {"code": code, "name": (counters.get(code) or {}).get("name") or a[0].get("retailer_name") or code,
                "tl": " | ".join(sorted({canonical_name(r.get("tl")) for r in a if r.get("tl")})),
                "ss": " | ".join(sorted({canonical_name(r.get("ss")) for r in a if r.get("ss")})),
                "target": tgt, "stock": stock}
        if stock > 0:
            not_moving.append(info)
        elif tgt > 0:
            no_stock.append(info)
    not_moving.sort(key=lambda x: (-x["stock"], -x["target"], x["name"]))
    no_stock.sort(key=lambda x: (-x["target"], x["name"]))

    stores = live.get("stores") or {}
    vbas, zero = 0, []
    for v in targets.get("vbas") or []:
        row = alignment.stores.get(v["store_code"])
        if scope:
            ok = alignment.matches(row, scope) if row else all(
                canonical_name(v.get(k)) == canonical_name(val) for k, val in scope.items() if k in ("tl", "ss"))
            if not ok:
                continue
        vbas += 1
        mtd, ftd = (stores.get(v["store_code"]) or {}).get(variant) or [0, 0]
        if not mtd and not ftd:
            zero.append({"name": v["name"], "type": v["type"], "store": v["store_name"].replace(" (Store)", ""),
                         "store_code": v["store_code"], "tl": (row or {}).get("tl") or v.get("tl"),
                         "target": int((v.get("targets") or {}).get(variant) or 0)})
    zero.sort(key=lambda x: (-x["target"], x["name"]))
    return {"variant": variant, "not_moving": not_moving, "no_stock_with_target": no_stock,
            "vbas_in_area": vbas, "vbas_zero": zero}
