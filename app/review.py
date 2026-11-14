"""One-page performance review of a TL, SS or KAM: counters, flags and an action plan.

Built from the same live dashboard the app uses, scoped to that person."""
import math

FOCUS_SERIES = ["Y11 5G", "Y21 5G", "Y31t 5G", "S2", "S2 FE", "V80"]
PLACEHOLDERS = {"VBM-Vacant", "SS Direct (NPO)", "Vacant-Zone A", "Unassigned"}


def _counters(perf):
    """Chain stores folded into their retailer (stock for chains is held at the retailer)."""
    parents = {p["code"]: p for p in perf.get("chain_parents") or []}
    out, seen = [], set()
    for r in perf.get("retailers") or []:
        cp = r.get("chain_parent")
        if cp and cp in parents:
            if cp in seen:
                continue
            seen.add(cp)
            p = parents[cp]
            stores = [x for x in perf["retailers"] if x.get("chain_parent") == cp]
            out.append({**p, "name": (p.get("name") or "").replace("-Main (Retailer)", "").replace(" (Retailer)", "") + (f" ×{len(stores)}" if len(stores) > 1 else ""),
                        "club": r.get("club"), "chain": True,
                        "back_support_achievement_pct": max((x.get("back_support_achievement_pct") or 0) for x in stores),
                        "back_support_payable": sum(int(x.get("back_support_payable") or 0) for x in stores)})
        else:
            out.append({**r, "name": (r.get("name") or "").replace(" (Retailer)", ""), "chain": False})
    return out


def _models(c):
    sc = c.get("schemes") or {}
    return {l["series"]: l["units"] for part in ("focus", "clearance", "additional")
            for l in ((sc.get(part) or {}).get("lines") or [])}


def build(perf, role, name, team_rows=None):
    s, P = perf["summary"], perf["period"]
    left = max(int(P.get("days_remaining") or 1), 1)
    cs = _counters(perf)
    for c in cs:
        t = int(c.get("target") or 0)
        c["pct"] = round(c["sales"] * 100 / t, 1) if t else None
        c["gap"] = max(t - int(c.get("sales") or 0), 0)
        c["need"] = math.ceil(c["gap"] / left) if t else 0
    cs.sort(key=lambda c: -(c.get("sales") or 0))
    total = sum(c.get("sales") or 0 for c in cs) or 0
    flags, actions = [], []

    # concentration
    if len(cs) >= 5 and total:
        top = cs[:2]
        share = sum(c["sales"] for c in top) * 100 / total
        if share >= 50:
            rest = cs[2:]
            rs, rt = sum(c["sales"] for c in rest), sum(int(c.get("target") or 0) for c in rest)
            flags.append({"kind": "bad", "text": f"{' + '.join(c['name'] for c in top)} = {round(share)}% of the sale. "
                          f"The other {len(rest)} counters have sold {rs} of {rt}" + (f" ({round(rs * 100 / rt)}%)" if rt else "") + "."})

    behind = sorted([c for c in cs if c["gap"] > 0 and c.get("target")], key=lambda c: -c["gap"])
    if role == "TL" and behind:
        b = behind[0]
        ss = next((x for x in [b.get("ss")] if x and x not in PLACEHOLDERS), None)
        actions.append({"title": f"{b['name']}: " + (f"joint visit with {ss}" if ss else "visit this week"),
                        "text": f"{b['gap']} units short, needs {b['need']} a day. Biggest gap."})
    elif behind:
        actions.append({"title": "Biggest counter gaps", "text": "; ".join(f"{c['name']} {c['gap']}" for c in behind[:4]) + " units short."})

    heavy = sorted([c for c in cs if (c.get("dos") or 0) >= 45 and (c.get("stock") or 0) >= 10], key=lambda c: -(c.get("dos") or 0))
    if heavy:
        u = sum(int(c["stock"] or 0) for c in heavy)
        names = ", ".join(c["name"] for c in heavy[:4]) + (f" +{len(heavy) - 4} more" if len(heavy) > 4 else "")
        actions.append({"title": f"Clear stuck stock: {names}",
                        "text": f"{u} units at {round(min(c['dos'] for c in heavy))}–{round(max(c['dos'] for c in heavy))} days of stock. Demo, counter offer, VBA push."})

    near = [c for c in cs if 40 <= (c.get("back_support_achievement_pct") or 0) < 90]
    if near:
        actions.append({"title": "Back margin unlocks at 90% of value target",
                        "text": ", ".join(f"{c['name']} {round(c['back_support_achievement_pct'])}%" for c in sorted(near, key=lambda c: -c['back_support_achievement_pct'])[:4]) + ": push them over the line."})

    mp = (P.get("model_end") or "2026-11-15")
    for c in cs[:3]:
        m = _models(c)
        miss = [f for f in FOCUS_SERIES if not m.get(f)]
        if c["sales"] >= 30 and miss:
            actions.append({"title": f"Push {', '.join(miss[:2])} at {c['name']}",
                            "text": f"Sells {round(c.get('avg_daily_sales') or 0)} a day but none of {' / '.join(miss[:2])}. Focus slabs run till {mp[8:]} Nov."})
            break

    stale = [c for c in cs if c.get("days_since_visit") is None or c["days_since_visit"] >= 20]
    never = sum(1 for c in stale if c.get("days_since_visit") is None)
    if stale:
        actions.append({"title": "Visit and log every counter",
                        "text": f"{len(stale) - never} counter{'s' if len(stale) - never != 1 else ''} not visited in 20+ days, {never} never visited (as logged in the app)."})
    zero = [c for c in cs if not c.get("sales")]
    if zero:
        flags.append({"kind": "warn", "text": f"{len(zero)} counter{'s' if len(zero) > 1 else ''} with no sale this month."})

    t_target = int(s.get("target") or 0)
    sold_before = int(s.get("sales") or 0) - int(s.get("ftd_sales") or 0)
    return {
        "role": role, "name": name, "period": P,
        "parents": _parents(perf, role),
        "summary": {"sales": s.get("sales"), "target": t_target, "pct": s.get("achievement_pct"),
                    "gap": max(t_target - int(s.get("sales") or 0), 0), "need": math.ceil(max(t_target - sold_before, 0) / left) if t_target else 0,
                    "ftd": s.get("ftd_sales"), "ftd_value": s.get("ftd_sales_value"),
                    "ftd_counters": sum(1 for c in cs if c.get("ftd_sales")), "counters": len(cs), "stock": s.get("stock")},
        "flags": flags, "actions": actions[:5],
        "team": team_rows or [],
        "counters": [{k: c.get(k) for k in ("code", "name", "club", "town_name", "target", "sales", "pct", "gap", "need", "ftd_sales",
                                            "stock", "dos", "days_since_visit", "chain", "tl")} for c in cs],
    }


def _parents(perf, role):
    rs = perf.get("retailers") or []
    def common(key):
        vals = {r.get(key) for r in rs if r.get(key)}
        return next(iter(vals)) if len(vals) == 1 else ""
    towns = {}
    for r in rs:
        if r.get("town_name"):
            towns[r["town_name"]] = towns.get(r["town_name"], 0) + 1
    return {"ss": common("ss") if role == "TL" else "", "kam": common("kam") if role in ("TL", "SS", "RDS") else "",
            "towns": [t for t, _ in sorted(towns.items(), key=lambda x: -x[1])[:3]]}
