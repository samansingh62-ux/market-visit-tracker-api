"""November 2026 retailer schemes (Zone A), worked out from V-Work sales.

Every figure here is provisional: the circulars also need 100% V-Work upload,
90% activation, pre-activation under 5% (else 20% off) and no MOP breach or
infiltration, none of which can be checked from sales data.

Sales come from vwork-live-api /api/v1/schemes/november-sales, one row per
retailer:
    booster: {"segments": {"20K-25K": n, "25K-35K": n, "35K-50K": n, "50K+": n},
              "below_20k_units": n, "unknown_price_units": n}
    models:  {"Y11": n, "Y21": n, ..., "X Fold6": n}           (1-15 Nov)
    month:   {"non_t_value": x, "t_series_value": x, "unknown_value_units": n,
              "margin_buckets": {"20K-25K": x, "25K-30K": x, "30K-50K": x, "50K+": x}}
"""
from datetime import date

YEAR, MONTH = 2026, 11
BOOSTER_START, BOOSTER_END = date(2026, 11, 1), date(2026, 11, 10)
MODEL_START, MODEL_END = date(2026, 11, 1), date(2026, 11, 15)
MONTH_START, MONTH_END = date(2026, 11, 1), date(2026, 11, 30)

BOOSTER_BANDS = ["20K-25K", "25K-35K", "35K-50K", "50K+"]
# (from units, to units or None, per-unit rate in each price band)
BOOSTER_PO = [
    (5, 9, [100, 200, 300, 300]),
    (10, 15, [150, 250, 400, 400]),
    (16, 20, [200, 300, 500, 500]),
    (21, 29, [250, 400, 600, 600]),
    (30, None, [300, 500, 700, 700]),
]
BOOSTER_NPO = [
    (2, 4, [200, 300, 400, 500]),
    (5, 9, [300, 400, 500, 600]),
    (10, 14, [500, 600, 700, 800]),
    (15, None, [600, 700, 800, 900]),
]

# Per-unit slab pay-outs; all variants of a series count together.
FOCUS = {
    "Y11": ("Y11 5G", [(2, 4, 150), (5, 8, 350), (9, 15, 500), (16, None, 600)]),
    "Y21": ("Y21 5G", [(1, 3, 300), (4, 9, 600), (10, 16, 1000), (17, 24, 1200), (25, None, 1600)]),
    "Y31t": ("Y31t 5G", [(1, 1, 400), (2, 7, 700), (8, 15, 1000), (16, None, 1500)]),
    "S2": ("S2", [(1, 2, 700), (3, 9, 1000), (10, 15, 1500), (16, None, 1800)]),
    "S2 FE": ("S2 FE", [(1, 2, 1000), (3, 5, 1200), (6, 9, 1500), (10, 14, 2000), (15, None, 2500)]),
    "V80": ("V80", [(1, 1, 800), (2, 4, 1000), (5, 8, 1300), (9, 12, 1600), (13, None, 2000)]),
}
CLEARANCE = {
    "Y51 Pro": ("Y51 Pro", [(1, 2, 700), (3, 9, 1000), (10, 15, 1300), (16, None, 1800)]),
    "V70 FE": ("V70 FE", [(1, 1, 1000), (2, 4, 1500), (5, 9, 2000), (10, None, 2500)]),
    "X300 Ultra": ("X300 Ultra", [(1, None, 5000)]),
}
ADDITIONAL = {
    "Y05": ("Y05", [(2, 4, 200), (5, 8, 400), (9, None, 600)]),
    "X300 FE": ("X300 FE", [(1, 1, 1500), (2, 4, 2500), (5, None, 4000)]),
    "X Fold6": ("X Fold6", [(1, None, 3000)]),
}

CLUB_ORDER = ["Non-Club", "Gold", "Platinum", "Titanium", "Royal", "Grand Royal", "Imperial"]
CLUB_FLOOR = {"Gold": 4e5, "Platinum": 8e5, "Titanium": 15e5, "Royal": 20e5, "Grand Royal": 30e5, "Imperial": 45e5}
MARGIN_BANDS = ["20K-25K", "25K-30K", "30K-50K", "50K+"]
MARGIN_RATES = {
    "Imperial": [0.022, 0.024, 0.026, 0.028],
    "Grand Royal": [0.020, 0.022, 0.024, 0.026],
    "Royal": [0.018, 0.020, 0.022, 0.024],
    "Titanium": [0.017, 0.018, 0.020, 0.022],
    "Platinum": [0.016, 0.017, 0.019, 0.020],
    "Gold": [0.015, 0.016, 0.018, 0.019],
    "Non-Club": [0.0, 0.0, 0.0, 0.0],
}
SHOPBOY_CORE = [(280000, 7000), (400000, 14000), (600000, 18000), (900000, 22000)]
SHOPBOY_UNIFORM = [(155000, 2000), (250000, 5000), (400000, 7000), (550000, 10000)]


def _slab_label(lo, hi):
    if hi is None:
        return f"{lo}+ units" if lo > 1 else "1+ unit"
    if lo == hi:
        return f"{lo} unit" if lo == 1 else f"{lo} units"
    return f"{lo}-{hi} units"


def _find(units, slabs):
    for i, (lo, hi, *_rest) in enumerate(slabs):
        if units >= lo and (hi is None or units <= hi):
            return i
    return None


def _pay(units, slabs):
    i = _find(units, slabs)
    rate = slabs[i][2] if i is not None else 0
    return i, rate, units * rate


def _model_lines(models, table, stock=None):
    """Per-series payout, what the next slab would pay, and what selling the stock on hand would pay."""
    lines, total, extra = [], 0, 0
    for key, (label, slabs) in table.items():
        units = int((models or {}).get(key) or 0)
        i, rate, payout = _pay(units, slabs)
        nxt = None
        j = (i + 1) if i is not None else 0
        if j < len(slabs):
            lo, _hi, nrate = slabs[j]
            nxt = {"units_more": lo - units, "rate": nrate, "payout": lo * nrate}
        total += payout
        line = {"series": label, "units": units, "slab": _slab_label(*slabs[i][:2]) if i is not None else None,
                "rate": rate, "payout": payout, "next": nxt}
        if stock is not None:
            st = int(stock.get(key) or 0)
            ai, arate, apay = _pay(units + st, slabs)
            line["stock"] = st
            line["if_all_sold"] = {"units": units + st, "slab": _slab_label(*slabs[ai][:2]) if ai is not None else None,
                                   "rate": arate, "payout": apay, "extra": apay - payout}
            if nxt:
                line["next"]["stock_short"] = max(nxt["units_more"] - st, 0)   # 0 = the stock on hand is enough
            extra += apay - payout
        lines.append(line)
    out = {"payout": total, "units": sum(x["units"] for x in lines), "lines": lines}
    if stock is not None:
        out["stock_extra"] = extra
    return out


def _club_name(value):
    text = str(value or "").strip()
    for c in CLUB_ORDER:
        if text.lower() == c.lower():
            return c
    return None


def _club_by_value(value):
    best = "Non-Club"
    for c in CLUB_ORDER[1:]:
        if value >= CLUB_FLOOR[c]:
            best = c
    return best


def booster(club, data):
    data = data or {}
    seg = {k: int((data.get("segments") or {}).get(k) or 0) for k in BOOSTER_BANDS}
    units = sum(seg.values())
    club_name = _club_name(club)
    out = {"segments": seg, "units": units,
           "below_20k_units": int(data.get("below_20k_units") or 0),
           "unknown_price_units": int(data.get("unknown_price_units") or 0)}
    if club_name is None:
        return {**out, "type": None, "slab": None, "payout": None, "note": "Club not set for this counter"}
    po = club_name != "Non-Club"
    slabs = BOOSTER_PO if po else BOOSTER_NPO
    i = _find(units, slabs)
    rates = slabs[i][2] if i is not None else [0, 0, 0, 0]
    payout = sum(seg[k] * r for k, r in zip(BOOSTER_BANDS, rates))
    return {**out, "type": "PO" if po else "NPO", "slab": _slab_label(*slabs[i][:2]) if i is not None else None,
            "rates": dict(zip(BOOSTER_BANDS, rates)), "payout": payout,
            "min_units": slabs[0][0]}


def back_support(club, target_value, data):
    data = data or {}
    buckets = {k: float((data.get("margin_buckets") or {}).get(k) or 0) for k in MARGIN_BANDS}
    non_t = float(data.get("non_t_value") or 0)
    t_val = float(data.get("t_series_value") or 0)
    counted_t = min(t_val, non_t / 9) if non_t > 0 else 0.0   # T-series capped at 10% of achievement
    counted = non_t + counted_t
    assigned = _club_name(club)
    by_value = _club_by_value(counted)
    used = assigned or "Non-Club"
    upgraded = CLUB_ORDER.index(by_value) > CLUB_ORDER.index(used)
    if upgraded:
        used = by_value
    base = sum(buckets[k] * r for k, r in zip(MARGIN_BANDS, MARGIN_RATES[used]))
    tv = float(target_value or 0)
    pct = round(counted * 100 / tv, 1) if tv > 0 else None
    if tv <= 0:
        payable, rule = None, "Value target not set"
    elif pct >= 100:
        payable, rule = round(base), "100% achieved: full margin"
    elif pct >= 90:
        payable, rule = round(base * pct / 100), f"{pct}% achieved: margin paid at {pct}%"
    else:
        payable, rule = 0, "Below 90% of value target: no margin yet"
    return {
        "club_assigned": assigned, "club_used": used, "upgraded": upgraded,
        "counted_value": round(counted), "t_series_value": round(t_val), "t_series_counted": round(counted_t),
        "target_value": round(tv) if tv > 0 else None, "achievement_pct": pct,
        "base_margin": round(base), "payable": payable, "rule": rule,
        "value_to_90": round(max(0.9 * tv - counted, 0)) if tv > 0 else None,
        "value_to_100": round(max(tv - counted, 0)) if tv > 0 else None,
        "eligible_value": round(sum(buckets.values())),
        "unknown_value_units": int(data.get("unknown_value_units") or 0),
    }


def _shopboy(value, slabs):
    got = None
    for floor, amount in slabs:
        if value >= floor:
            got = (floor, amount)
    nxt = next(((f, a) for f, a in slabs if value < f), None)
    return {"amount": got[1] if got else 0, "slab_from": got[0] if got else None,
            "next_from": nxt[0] if nxt else None, "next_amount": nxt[1] if nxt else None,
            "value_more": round(nxt[0] - value) if nxt else None}


def shopboy(data):
    value = float((data or {}).get("non_t_value") or 0)
    return {"value": round(value), "core": _shopboy(value, SHOPBOY_CORE), "uniform": _shopboy(value, SHOPBOY_UNIFORM)}


def periods(today):
    def p(start, end):
        return {"start": start.isoformat(), "end": end.isoformat(), "closed": today > end,
                "days_left": max((end - today).days + 1, 0) if today >= start else None}
    return {"booster": p(BOOSTER_START, BOOSTER_END), "models": p(MODEL_START, MODEL_END), "month": p(MONTH_START, MONTH_END)}


def for_retailer(club, target_value, data, today):
    data = data or {}
    models = data.get("models") or {}
    b = booster(club, data.get("booster"))
    stock = data.get("stock") if isinstance(data.get("stock"), dict) else None
    f = _model_lines(models, FOCUS, stock)
    c = _model_lines(models, CLEARANCE, stock)
    a = _model_lines(models, ADDITIONAL, stock)
    bs = back_support(club, target_value, data.get("month"))
    total = sum(int(x or 0) for x in (b.get("payout"), f["payout"], c["payout"], a["payout"], bs.get("payable")))
    out = {"month": "2026-11", "periods": periods(today), "booster": b, "focus": f, "clearance": c,
           "additional": a, "back_support": bs, "shopboy": shopboy(data.get("month")), "total": total}
    if stock is not None:
        out["stock_extra"] = f["stock_extra"] + c["stock_extra"] + a["stock_extra"]
        out["stock_units"] = sum(int(v or 0) for k, v in stock.items() if k in {**FOCUS, **CLEARANCE, **ADDITIONAL})
    return out
