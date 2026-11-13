"""Punched (uploaded) sales by person, from the tertiary sales dashboard.

V-Work's live sales feed does not say who uploaded a sale; the dashboard's "Raw" sheet does (one row
per IMEI with the uploader's name, post and type). This reads that sheet, plus the VBA and FVBA sheets
for each one's targets, into per-person totals. IMEIs are not kept.
"""
import collections
import re
from datetime import date, datetime

from .alignment import alignment, canonical_name

_n = lambda s: re.sub(r"\s+", " ", str(s or "").strip())


def _kind(post: str, emp_type: str) -> str:
    p, t = post.upper(), emp_type.upper()
    if p.startswith("FVBA") or t.replace(" ", "") == "FVBA":
        return "FVBA"
    if p.startswith("RVBA"):
        return "RVBA"
    if p.startswith("VBA") or t == "VBA":
        return "VBA"
    if "TEAM" in p and "LEADER" in p:
        return "TL"
    if "SUPERVISOR" in p:
        return "SS"
    return "Other"


def _header_index(header, *names):
    low = [str(h or "").strip().lower() for h in header]
    for name in names:
        if name.lower() in low:
            return low.index(name.lower())
    raise ValueError(f"Column '{names[0]}' not found")


def parse_workbook(path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Raw" not in wb.sheetnames:
        raise ValueError("The file has no 'Raw' sheet (one row per IMEI).")
    rows = wb["Raw"].iter_rows(values_only=True)
    h = next(rows)
    ix = {k: _header_index(h, *v) for k, v in {
        "store": ("Store code",), "retailer": ("Retailer code",), "uploader": ("Uploader name",),
        "uid": ("Emp Code 2",), "post": ("Uploader post",), "etype": ("Emp Type 2",),
        "model": ("Updated Model", "Models"), "date": ("Upload date",), "qty": ("Quantity",), "mop": ("MOP",),
    }.items()}
    agg = collections.defaultdict(lambda: [0, 0])
    people = {}
    last = None
    for r in rows:
        if not r or r[ix["qty"]] in (None, ""):
            continue
        d = r[ix["date"]]
        d = d.date() if isinstance(d, datetime) else (d if isinstance(d, date) else None)
        if d is None:
            continue
        last = max(last or d, d)
        uid = _n(r[ix["uid"]]).upper() or _n(r[ix["uploader"]])
        kind = _kind(_n(r[ix["post"]]), _n(r[ix["etype"]]))
        people.setdefault(uid, {"name": canonical_name(_n(r[ix["uploader"]])), "kind": kind})
        qty = int(r[ix["qty"]] or 0)
        key = (d.isoformat(), uid, _n(r[ix["store"]]).upper(), _n(r[ix["retailer"]]).upper(), _n(r[ix["model"]]))
        agg[key][0] += qty
        agg[key][1] += qty * float(r[ix["mop"]] or 0)
    if last is None:
        raise ValueError("The 'Raw' sheet has no sales rows.")

    vbas = []
    # Column positions differ: the FVBA sheet has no "VBA Type" or "VBA Band" column.
    cols = {"VBA": dict(uid=2, vw=3, name=4, vtype=6, store=8, sname=9, ret=10, tl=13, ss=14, status=17, vol=18, val=19),
            "FVBA": dict(uid=1, vw=2, name=3, vtype=None, store=7, sname=8, ret=9, tl=12, ss=13, status=15, vol=16, val=17)}
    for sheet, c in cols.items():
        if sheet not in wb.sheetnames:
            continue
        for r in wb[sheet].iter_rows(min_row=6, values_only=True):
            if len(r) <= c["val"] or not _n(r[c["name"]]) or _n(r[c["status"]]) != "Active":
                continue
            vtype = "FVBA" if sheet == "FVBA" else ("RVBA" if "RVBA" in _n(r[c["vtype"]]).upper() else "VBA")
            vbas.append({"uid": _n(r[c["uid"]]).upper(), "vwork_code": _n(r[c["vw"]]), "name": canonical_name(_n(r[c["name"]])),
                         "type": vtype, "store_code": _n(r[c["store"]]).upper(), "store_name": _n(r[c["sname"]]).replace(" (Store)", ""),
                         "retailer_code": _n(r[c["ret"]]).upper(), "tl": _n(r[c["tl"]]), "ss": _n(r[c["ss"]]),
                         "vol_target": int(r[c["vol"]] or 0), "val_target": int(r[c["val"]] or 0)})
    return {"month": last.strftime("%Y-%m"), "as_of": last.isoformat(), "people": people,
            "sales": [[*k, v[0], round(v[1])] for k, v in sorted(agg.items())], "vbas": vbas}


# ---------------- storage ----------------
def _file(month: str):
    from pathlib import Path
    return Path(__file__).parent / f"punched_{month}.json"


def load(month: str):
    """The latest dashboard for the month: an upload in the database, else the file shipped with the app."""
    import json
    from . import database
    try:
        with database.get_conn() as conn:
            row = conn.execute("SELECT data FROM punched_uploads WHERE month = %s", (month,)).fetchone()
        if row:
            return json.loads(row["data"])
    except Exception:
        pass
    f = _file(month)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(data: dict, by: str):
    import json
    from . import database
    with database.get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS punched_uploads (month TEXT PRIMARY KEY, as_of TEXT, data TEXT, uploaded_by TEXT, uploaded_at TIMESTAMPTZ DEFAULT now())")
        conn.execute("""INSERT INTO punched_uploads (month, as_of, data, uploaded_by) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (month) DO UPDATE SET as_of = EXCLUDED.as_of, data = EXCLUDED.data,
                        uploaded_by = EXCLUDED.uploaded_by, uploaded_at = now()""",
                     (data["month"], data["as_of"], json.dumps(data, ensure_ascii=False), by))


# ---------------- view ----------------
def _in_scope(store: str, retailer: str, scope: dict) -> bool:
    if not scope:
        return True
    row = alignment.stores.get(store)
    if row:
        return alignment.matches(row, scope)
    return bool(alignment.assignments(retailer, scope))


def view(data: dict, scope: dict) -> dict:
    tl_names = {canonical_name(r.get("tl")) for r in alignment.rows}
    ss_names = {canonical_name(r.get("ss")) for r in alignment.rows}
    people = data["people"]

    def kind(uid):
        p = people.get(uid) or {}
        if p.get("kind") in ("TL", "SS"):   # the post in the file can be out of date; go by today's mapping
            n = p.get("name")
            return "TL" if n in tl_names else "SS" if n in ss_names else p["kind"]
        return p.get("kind") or "Other"

    totals = collections.defaultdict(lambda: [0, 0])
    by_uid = collections.defaultdict(lambda: {"units": 0, "value": 0, "days": set(), "stores": set(), "last": None})
    area = collections.defaultdict(lambda: [0, 0])          # all punches at a TL's / SS's outlets
    for d, uid, store, retailer, model, qty, value in data["sales"]:
        if not _in_scope(store, retailer, scope):
            continue
        k = kind(uid)
        totals[k][0] += qty; totals[k][1] += value
        u = by_uid[uid]
        u["units"] += qty; u["value"] += value; u["days"].add(d); u["stores"].add(store)
        u["last"] = max(u["last"] or d, d)
        row = alignment.stores.get(store) or {}
        for key in ("tl", "ss"):
            if row.get(key):
                area[(key, canonical_name(row[key]))][0] += qty
                area[(key, canonical_name(row[key]))][1] += value
    all_units = sum(v[0] for v in totals.values()) or 0

    vbas, seen = [], set()
    for v in data["vbas"]:
        row = alignment.stores.get(v["store_code"])
        if scope and not (alignment.matches(row, scope) if row else _in_scope(v["store_code"], v["retailer_code"], scope)):
            continue
        u = by_uid.get(v["uid"]) or {"units": 0, "value": 0, "days": set(), "last": None}
        seen.add(v["uid"])
        vbas.append({"name": v["name"], "type": v["type"], "store": v["store_name"], "store_code": v["store_code"],
                     "tl": (row or {}).get("tl") or v["tl"], "ss": (row or {}).get("ss") or v["ss"],
                     "kam": (row or {}).get("kam") or "", "vol_target": v["vol_target"], "val_target": v["val_target"],
                     "units": u["units"], "value": round(u["value"]), "days": len(u["days"]), "last": u["last"],
                     "pct": round(u["units"] * 100 / v["vol_target"], 1) if v["vol_target"] else None})
    for uid, u in by_uid.items():                              # punched as VBA but not on the VBA / FVBA sheets
        if uid not in seen and kind(uid) in ("VBA", "RVBA", "FVBA"):
            st = alignment.stores.get(next(iter(u["stores"]), "")) or {}
            vbas.append({"name": people[uid]["name"], "type": kind(uid), "store": (st.get("store_name") or "").replace(" (Store)", ""),
                         "store_code": st.get("store_code"), "tl": st.get("tl") or "", "ss": st.get("ss") or "", "kam": st.get("kam") or "",
                         "vol_target": 0, "val_target": 0, "units": u["units"], "value": round(u["value"]),
                         "days": len(u["days"]), "last": u["last"], "pct": None, "not_on_list": True})
    vbas.sort(key=lambda x: (x["pct"] if x["pct"] is not None else 999, x["units"]))

    kam_of = {}
    for r in alignment.rows:
        for key in ("tl", "ss"):
            if r.get(key) and r.get("kam"):
                kam_of.setdefault((key.upper(), canonical_name(r[key])), r["kam"])
    own = []
    for uid, u in by_uid.items():
        k = kind(uid)
        if k not in ("TL", "SS"):
            continue
        name = people[uid]["name"]
        a = area.get(("tl" if k == "TL" else "ss", name), [0, 0])
        own.append({"name": name, "role": k, "kam": kam_of.get((k, name), ""), "units": u["units"], "value": round(u["value"]), "outlets": len(u["stores"]),
                    "days": len(u["days"]), "last": u["last"], "area_units": a[0],
                    "share": round(u["units"] * 100 / a[0], 1) if a[0] else None})
    # TLs / SSs of the area who punched nothing themselves
    if scope.get("tl"):
        names = {("TL", canonical_name(scope["tl"]))}
    else:
        names = {("TL", canonical_name(r["tl"])) for r in alignment.rows if r.get("tl") and r["tl"] not in ("VBM-Vacant", "SS Direct (NPO)") and (not scope or alignment.matches(r, scope))}
        names |= {("SS", canonical_name(r["ss"])) for r in alignment.rows if r.get("ss") and r["ss"] != "Vacant-Zone A" and (not scope or alignment.matches(r, scope))}
    have = {(o["role"], o["name"]) for o in own}
    for role, name in sorted(names - have):
        a = area.get(("tl" if role == "TL" else "ss", name), [0, 0])
        own.append({"name": name, "role": role, "kam": kam_of.get((role, name), ""), "units": 0, "value": 0, "outlets": 0, "days": 0, "last": None,
                    "area_units": a[0], "share": 0.0 if a[0] else None})
    own.sort(key=lambda x: (-x["units"], x["name"]))

    order = ["VBA", "RVBA", "FVBA", "SS", "TL", "Other"]
    return {"as_of": data["as_of"], "month": data["month"],
            "totals": [{"kind": k, "units": totals[k][0], "value": round(totals[k][1]),
                        "share": round(totals[k][0] * 100 / all_units, 1) if all_units else 0} for k in order if k in totals],
            "total_units": all_units, "vbas": vbas, "own": own,
            "kams": sorted({x["kam"] for x in vbas + own if x.get("kam")})}
