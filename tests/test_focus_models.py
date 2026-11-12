from datetime import date

from app import focus_models as fm

T = fm.load_targets("2026-11")
V = "V80(8+256G)"


def test_targets_loaded_for_every_level():
    assert len(T["models"]) == 10 and T["ZONE"][V] == 650
    assert fm.scope_target(T, "TL", "Polash Roy", {"tl": "Polash Roy"})[V] == T["TL"]["Polash Roy"][V]
    assert fm.scope_target(T, "SS", "Sujit Sinha", {"ss": "Sujit Sinha"})[V] > 0       # sheet says "Sujit Sinha"
    assert fm.scope_target(T, "CEO", "Evan", {}) == T["ZONE"]


def test_summary_and_detail():
    live = {"as_of": "2026-11-12", "variants": {V: {"mtd": 3, "ftd": 1, "stock": 9}},
            "counters": [{"code": "NER202509", "name": "A", "variants": {V: {"mtd": 3, "ftd": 1, "stock": 4}}},
                         {"code": "NER179190", "name": "B", "variants": {V: {"mtd": 0, "ftd": 0, "stock": 5}}}],
            "stores": {"NED128748": {V: [3, 1]}}}
    scope = {"tl": "Polash Roy"}
    s = fm.summary(T, live, "TL", "Polash Roy", scope, date(2026, 11, 12))
    row = next(r for r in s["models"] if r["variant"] == V)
    assert row["mtd"] == 3 and row["target"] == T["TL"]["Polash Roy"][V] and s["days_left"] == 19
    d = fm.detail(T, live, V, scope)
    assert [x["code"] for x in d["not_moving"]][:1] == ["NER179190"]
    assert "NER202509" not in {x["code"] for x in d["not_moving"] + d["no_stock_with_target"]}
    assert d["vbas_in_area"] >= len(d["vbas_zero"])
    assert all(v["store_code"] != "NED128748" for v in d["vbas_zero"])
