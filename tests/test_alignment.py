from app.alignment import Alignment, alignment, canonical_name


def test_master_is_unique_at_store_grain_and_retains_shared_retailers():
    assert len(alignment.stores) == 730
    assert len(alignment.retailers) == 589
    shared = [code for code in alignment.retailers if len({(r["kam"], r["ss"], r["tl"]) for r in alignment.assignments(code)}) > 1]
    assert len(shared) == 43
    assert len(alignment.assignments("NER177087", {"tl": "Krishna Bhowmick"})) == 4
    assert len(alignment.assignments("NER177087", {"tl": "SS Direct (NPO)"})) == 3


def test_npo_outlets_sit_under_the_ss_not_a_tl():
    rows = alignment.rows
    # NPO outlets go to the TL named in the file; only those without one sit directly under the SS.
    assert all(r["tl"] == r["area_tl"] for r in rows if r["outlet_type"] == "PO")
    assert all(r["tl"] == ("SS Direct (NPO)" if r["area_tl"] == "VBM-Vacant" else r["area_tl"]) for r in rows if r["outlet_type"] == "NPO")
    assert all(not r["tl_id"] for r in rows if r["tl"] == "SS Direct (NPO)")
    polash_tl = alignment.store_codes(scope={"tl": "Polash Roy"})
    assert polash_tl and all(alignment.stores[c]["area_tl"] == "Polash Roy" for c in polash_tl)
    ss = alignment.store_codes(scope={"ss": "Avisek Das"})
    assert {alignment.stores[c]["outlet_type"] for c in ss} == {"PO", "NPO"}
    assert set(ss) <= set(alignment.store_codes(scope={"kam": "Sailen Das"}))


def test_sales_are_assigned_by_store_without_duplicating_the_record():
    sale = alignment.enrich({"store_code": "NED123598", "retailer_code": "wrong", "sales_cnt": 5})
    assert sale["retailer_code"] == "NER177087"
    assert sale["tl"] == "SS Direct (NPO)"
    assert sale["kam"] == "Biswajit Bania"
    assert sale["sales_cnt"] == 5
    assert not alignment.matches(sale, {"tl": "Krishna Bhowmick"})
    assert alignment.matches(sale, {"ss": "Naba Jyoti Bora"})


def test_unknown_code_never_falls_back_to_a_store_name():
    row = alignment.enrich({"store_code": "UNKNOWN", "store_name": "Alibaba-Beltola (Store)"})
    assert row["alignment_status"] == "UNMAPPED"


def test_retailer_only_records_never_choose_a_tl_for_shared_retailer():
    row = alignment.enrich({"retailer_code": "NER177087", "sales_cnt": 10})
    assert row["tl"] is None
    assert not alignment.matches(row, {"tl": "SS Direct (NPO)"})
    assert row["ss"] == "Naba Jyoti Bora"
    assert canonical_name("Sujeet Sinha") == "Sujit Sinha"
