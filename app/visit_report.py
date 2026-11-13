"""Visit report: outlets each TL / SS / KAM visited, with their remarks, and TLs' outlets per day."""
import collections
from datetime import date, timedelta

from .alignment import alignment, canonical_name

PLACEHOLDERS = {"VBM-Vacant", "Vacant-Zone A", "SS Direct (NPO)"}


def _area_kam(name: str, role: str) -> str:
    """The KAM whose area a TL / SS works in (most of their outlets), or the KAM themselves."""
    if role == "KAM":
        return name
    key = {"TL": "tl", "SS": "ss"}.get(role)
    if not key:
        return ""
    kams = collections.Counter(r.get("kam") for r in alignment.rows if canonical_name(r.get(key)) == name and r.get("kam"))
    return kams.most_common(1)[0][0] if kams else ""


def _team_of(name: str, role: str) -> dict:
    key = {"TL": "tl", "SS": "ss"}.get(role)
    rows = [r for r in alignment.rows if canonical_name(r.get(key)) == name] if key else []
    ss = collections.Counter(r.get("ss") for r in rows if r.get("ss"))
    return {"ss": ss.most_common(1)[0][0] if role == "TL" and ss else ""}


def build(visits: list, users: list, date_from: date, date_to: date, kam_scope: str = "") -> dict:
    """kam_scope: limit to that KAM's area (people working in it and visits to its outlets)."""
    people = {}
    for u in users:
        name = canonical_name(u["name"])
        if name in PLACEHOLDERS:
            continue
        people[name] = {"name": name, "role": u["role"], "kam": canonical_name(_area_kam(name, u["role"])),
                        **_team_of(name, u["role"]), "visits": []}
    in_area = None
    if kam_scope:
        in_area = {str(r["retailer_code"]).upper() for r in alignment.rows if canonical_name(r.get("kam")) == kam_scope}
        in_area |= {str(r["store_code"]).upper() for r in alignment.rows if canonical_name(r.get("kam")) == kam_scope}
    for v in visits:
        who = canonical_name(v.get("submitted_by"))
        if not who or who in PLACEHOLDERS:
            continue
        p = people.get(who)
        if p is None:
            role = str(v.get("submitted_role") or "").upper()
            p = people[who] = {"name": who, "role": role, "kam": canonical_name(_area_kam(who, role)), **_team_of(who, role), "visits": []}
        p["visits"].append({"retailer": v["retailer"], "code": v.get("retailer_code"), "town": v.get("town_name"),
                            "date": str(v["visit_date"])[:10], "feedback": v.get("feedback") or "",
                            "follow_up": v.get("suggestions") or "", "photos": int(v.get("photo_count") or 0)})
    out = []
    for p in people.values():
        if kam_scope and p["kam"] != kam_scope and p["name"] != kam_scope:
            continue
        vs = p["visits"]
        if in_area is not None:
            vs = [v for v in vs if not v["code"] or str(v["code"]).upper() in in_area]
        p["visits"] = vs
        p["visit_count"] = len(vs)
        p["outlets"] = len({v["retailer"] for v in vs})
        p["days_active"] = len({v["date"] for v in vs})
        p["last_visit"] = max((v["date"] for v in vs), default=None)
        p["with_remarks"] = sum(1 for v in vs if v["feedback"].strip() or v["follow_up"].strip())
        out.append(p)
    out.sort(key=lambda p: (-p["outlets"], p["name"]))

    days = [(date_from + timedelta(days=i)).isoformat() for i in range((date_to - date_from).days + 1)]
    tl_daily = []
    for p in out:
        if p["role"] != "TL":
            continue
        per = collections.defaultdict(set)
        for v in p["visits"]:
            per[v["date"]].add(v["retailer"])
        counts = [len(per.get(d, ())) for d in days]
        tl_daily.append({"name": p["name"], "kam": p["kam"], "ss": p.get("ss", ""), "days": counts, "total": p["outlets"],
                         "zero_days": sum(1 for c in counts if c == 0)})
    tl_daily.sort(key=lambda t: (-t["total"], t["name"]))
    totals = [sum(t["days"][i] for t in tl_daily) for i in range(len(days))]
    return {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "dates": days, "people": out,
            "tl_daily": tl_daily, "tl_daily_totals": totals,
            "kams": sorted({p["kam"] for p in out if p["kam"]})}
