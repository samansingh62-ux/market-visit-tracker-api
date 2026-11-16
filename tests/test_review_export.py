import json
from pathlib import Path

from app import review, review_export


def _perf():
    rets = [{"code": "A", "name": "Alpha (Retailer)", "club": "Gold", "target": 50, "sales": 60, "ftd_sales": 3, "stock": 40, "dos": 12,
             "avg_daily_sales": 4, "days_since_visit": 2, "tl": "T One", "ss": "S One", "kam": "K One", "town_name": "Silchar",
             "back_support_achievement_pct": 120, "schemes": {"focus": {"lines": [{"series": "Y11 5G", "units": 0}]}}},
            {"code": "B", "name": "Beta (Retailer)", "club": "Gold", "target": 40, "sales": 2, "ftd_sales": 0, "stock": 30, "dos": 150,
             "days_since_visit": None, "tl": "T One", "ss": "S One", "kam": "K One", "back_support_achievement_pct": 60}]
    return {"summary": {"sales": 62, "target": 90, "achievement_pct": 68.9, "ftd_sales": 3, "ftd_sales_value": 90000, "stock": 70},
            "period": {"end": "2026-11-16", "days_remaining": 15}, "retailers": rets, "chain_parents": []}


def test_png_and_pptx_build():
    d = review.build(_perf(), "KAM", "K One", [{"name": "T One", "sales": 62, "target": 90, "pct": 68.9, "ftd": 3, "need": 2}])
    png = review_export.build_png(d)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20000
    ppt = review_export.build_pptx(d)
    assert ppt[:2] == b"PK" and len(ppt) > 20000
    assert review_export.file_name(d, "png") == "K One - KAM review 2026-11-16.png"


def test_indian_grouping():
    assert review_export._n(1234567) == "12,34,567"
    assert review_export._money(25000000) == "₹2.50 Cr"
