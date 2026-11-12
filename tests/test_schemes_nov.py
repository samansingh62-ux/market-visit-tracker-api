from datetime import date

from app import schemes_nov as sn

TODAY = date(2026, 11, 12)


def test_booster_po_and_npo():
    seg = {"segments": {"20K-25K": 6, "25K-35K": 3, "35K-50K": 1, "50K+": 0}}
    po = sn.booster("Gold", seg)          # 10 units -> 10-15 slab: 150/250/400/400
    assert po["type"] == "PO" and po["slab"] == "10-15 units"
    assert po["payout"] == 6 * 150 + 3 * 250 + 1 * 400
    npo = sn.booster("Non-Club", seg)     # 10 units -> 10-14 slab: 500/600/700/800
    assert npo["type"] == "NPO" and npo["payout"] == 6 * 500 + 3 * 600 + 700
    small = sn.booster("Platinum", {"segments": {"20K-25K": 4}})
    assert small["payout"] == 0 and small["slab"] is None   # PO starts at 5 units
    assert sn.booster(None, seg)["payout"] is None


def test_focus_lines_and_next_slab():
    f = sn._model_lines({"Y21": 3, "S2 FE": 2, "Y11": 1, "V80": 13}, sn.FOCUS)
    by = {x["series"]: x for x in f["lines"]}
    assert by["Y21 5G"]["payout"] == 3 * 300 and by["Y21 5G"]["next"] == {"units_more": 1, "rate": 600, "payout": 2400}
    assert by["S2 FE"]["payout"] == 2 * 1000
    assert by["Y11 5G"]["payout"] == 0 and by["Y11 5G"]["next"]["units_more"] == 1   # Y11 starts at 2
    assert by["V80"]["payout"] == 13 * 2000 and by["V80"]["next"] is None
    assert f["payout"] == 900 + 2000 + 26000


def test_clearance_and_additional():
    c = sn._model_lines({"X300 Ultra": 2, "V70 FE": 5, "Y51 Pro": 16}, sn.CLEARANCE)
    assert c["payout"] == 2 * 5000 + 5 * 2000 + 16 * 1800
    a = sn._model_lines({"Y05": 1, "X Fold6": 1, "X300 FE": 5}, sn.ADDITIONAL)
    assert a["payout"] == 0 + 3000 + 5 * 4000


def test_back_support_rules():
    data = {"non_t_value": 900000, "t_series_value": 300000,
            "margin_buckets": {"20K-25K": 400000, "25K-30K": 200000, "30K-50K": 200000, "50K+": 0}}
    # T counted only up to 10% of achievement: 900000/9 = 100000
    full = sn.back_support("Gold", 1000000, data)
    assert full["counted_value"] == 1000000 and full["achievement_pct"] == 100.0
    # 10 lakh is Platinum value, so the Platinum rates apply (higher club payout)
    assert full["club_used"] == "Platinum" and full["upgraded"]
    base = 400000 * .016 + 200000 * .017 + 200000 * .019
    assert full["payable"] == round(base)
    part = sn.back_support("Platinum", 1080000, data)   # 92.6%
    assert part["payable"] == round(base * part["achievement_pct"] / 100) and part["payable"] > 0
    low = sn.back_support("Platinum", 2000000, data)
    assert low["payable"] == 0 and low["value_to_90"] == 800000
    assert sn.back_support("Gold", None, data)["payable"] is None


def test_shopboy_and_total():
    sb = sn.shopboy({"non_t_value": 450000})
    assert sb["core"]["amount"] == 14000 and sb["core"]["value_more"] == 150000
    assert sb["uniform"]["amount"] == 7000 and sb["uniform"]["next_amount"] == 10000
    out = sn.for_retailer("Gold", None, {"booster": {"segments": {"20K-25K": 5}}, "models": {"Y21": 1}}, TODAY)
    assert out["total"] == 5 * 100 + 300
    assert out["periods"]["booster"]["closed"] and out["periods"]["models"]["days_left"] == 4
