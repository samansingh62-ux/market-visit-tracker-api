from datetime import date

from app import visit_report


def v(who, role, retailer, code, day, fb="", fu=""):
    return {"submitted_by": who, "submitted_role": role, "retailer": retailer, "retailer_code": code,
            "visit_date": day, "feedback": fb, "suggestions": fu, "photo_count": 1, "town_name": "T"}


USERS = [{"name": "Bappan Das", "role": "TL"}, {"name": "Avisek Das", "role": "SS"}, {"name": "Sailen Das", "role": "KAM"},
         {"name": "Polash Roy", "role": "TL"}, {"name": "VBM-Vacant", "role": "TL"}]
VISITS = [
    v("Bappan Das", "TL", "Moon Light-1", "NED119923", "2026-11-12", "Good sale", "Send Y11"),
    v("Bappan Das", "TL", "Moon Light-1", "NED119923", "2026-11-12", "Again"),
    v("Bappan Das", "TL", "Salamiya Enterprise (Retailer)", "NED162610", "2026-11-13"),
    v("Avisek Das", "SS", "Moon Light-2", "NED00161836", "2026-11-13", "X300 branding"),
]


def test_people_counts_and_tl_daily():
    r = visit_report.build(VISITS, USERS, date(2026, 11, 12), date(2026, 11, 13))
    p = {x["name"]: x for x in r["people"]}
    assert "VBM-Vacant" not in p
    assert p["Bappan Das"]["visit_count"] == 3 and p["Bappan Das"]["outlets"] == 2 and p["Bappan Das"]["with_remarks"] == 2
    assert p["Polash Roy"]["outlets"] == 0                         # people with no visits still listed
    assert p["Bappan Das"]["kam"] == "Sailen Das" and p["Avisek Das"]["kam"] == "Sailen Das"
    t = {x["name"]: x for x in r["tl_daily"]}
    assert r["dates"] == ["2026-11-12", "2026-11-13"]
    assert t["Bappan Das"]["days"] == [1, 1] and t["Polash Roy"]["zero_days"] == 2


def test_kam_sees_only_their_area():
    r = visit_report.build(VISITS, USERS, date(2026, 11, 12), date(2026, 11, 13), kam_scope="Sailen Das")
    names = {x["name"] for x in r["people"]}
    assert {"Bappan Das", "Avisek Das", "Sailen Das"} <= names and "Polash Roy" not in names
