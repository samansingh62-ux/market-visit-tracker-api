import os
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
import pytest
from app import database, crud
from app.alignment import alignment, canonical_name

@pytest.fixture(scope="module")
def initialized():
    if not os.getenv("ALIGNMENT_DB_TEST"):
        pytest.skip("Integration database unavailable")
    database.init_db()

def test_alignment_import_and_all_ownership_queries(initialized):
    with database.get_conn() as conn:
        result = conn.execute("SELECT COUNT(*) AS stores, COUNT(DISTINCT retailer_code) AS retailers FROM store_alignment").fetchone()
    assert dict(result) == {"stores": 707, "retailers": 574}
    assert len(crud.list_retailers()) == 574
    for field in ("tl", "ss", "kam", "rds"):
        for name in {canonical_name(r[field]) for r in alignment.rows}:
            expected = {r["retailer_code"] for r in alignment.rows if canonical_name(r[field]) == name}
            actual = crud.list_retailers(**{field: name})
            assert {r["code"] for r in actual} == expected
            assert {r["code"] for r in crud.get_performance_scope_rows("2026-10", **{field:name})} == expected
            assert crud.get_stats(**{field:name})["total_retailers_in_master"] == len(expected)
    assert len(crud.get_retailer_health(limit=2000)) == 574
    assert crud.list_users_admin()
    for group in ("tl", "ss", "rds"):
        assert crud.get_coverage(group)
    for kam in {canonical_name(r["kam"]) for r in alignment.rows}:
        assert crud.list_kam_whatsapp_recipients(kam) is not None
        assert crud.list_kam_area_users(kam) is not None
