from app.alignment import Alignment, alignment, canonical_name


def test_master_is_unique_at_store_grain_and_retains_shared_retailers():
    assert len(alignment.stores) == 707
    assert len(alignment.retailers) == 574
    shared = [code for code in alignment.retailers if len({(r["kam"], r["ss"], r["tl"]) for r in alignment.assignments(code)}) > 1]
    assert len(shared) == 41
    assert len(alignment.assignments("NER177087", {"tl": "Krishna Bhowmick"})) == 4
    assert len(alignment.assignments("NER177087", {"tl": "VBM-Vacant"})) == 3


def test_sales_are_assigned_by_store_without_duplicating_the_record():
    sale = alignment.enrich({"store_code": "NED123598", "retailer_code": "wrong", "sales_cnt": 5})
    assert sale["retailer_code"] == "NER177087"
    assert sale["tl"] == "VBM-Vacant"
    assert sale["kam"] == "Biswajit Bania"
    assert sale["sales_cnt"] == 5
    assert not alignment.matches(sale, {"tl": "Krishna Bhowmick"})
    assert alignment.matches(sale, {"tl": "VBM-Vacant"})


def test_unknown_code_never_falls_back_to_a_store_name():
    row = alignment.enrich({"store_code": "UNKNOWN", "store_name": "Alibaba-Beltola (Store)"})
    assert row["alignment_status"] == "UNMAPPED"


def test_retailer_only_records_never_choose_a_tl_for_shared_retailer():
    row = alignment.enrich({"retailer_code": "NER177087", "sales_cnt": 10})
    assert row["tl"] is None
    assert not alignment.matches(row, {"tl": "VBM-Vacant"})
    assert row["ss"] == "Naba Jyoti Bora"
    assert canonical_name("Sujeet Sinha") == "Sujit Sinha"
