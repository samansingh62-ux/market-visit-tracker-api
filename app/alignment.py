"""October 2026 store and retailer alignment supplied by Management."""
import json
import re
from pathlib import Path
from contextvars import ContextVar

ALIASES = {"Bishwajit Bania": "Biswajit Bania", "Sujeet Sinha": "Sujit Sinha"}
FIELDS = ("kam", "ss", "tl", "rds")
request_scope = ContextVar("alignment_scope", default={})

def canonical_name(value):
    value = str(value or "").strip()
    return ALIASES.get(value, value)

def norm(value):
    return re.sub(r"\\s+", " ", str(value or "").strip()).casefold()

class Alignment:
    def __init__(self, rows):
        self.rows = rows
        self.stores = {}
        self.retailers = {}
        self.names = {}
        for row in rows:
            code = str(row["store_code"]).strip().upper()
            if code in self.stores:
                raise ValueError("Duplicate store code: " + code)
            self.stores[code] = row
            self.retailers.setdefault(row["retailer_code"], []).append(row)
            self.names.setdefault(norm(row["store_name"]), []).append(row)

    def assignments(self, code, scope=None):
        rows = self.retailers.get(str(code).strip().upper(), [])
        return [r for r in rows if self.matches(r, scope or {})]

    def matches(self, row, scope):
        return all(canonical_name(row.get(k)) == canonical_name(v) for k, v in scope.items())

    def store_codes(self, retailer_codes=None, scope=None):
        codes = None if retailer_codes is None else set(retailer_codes)
        return [r["store_code"] for r in self.rows
                if (codes is None or r["retailer_code"] in codes) and self.matches(r, scope or {})]

    def enrich(self, record):
        out = dict(record)
        code = str(record.get("store_code") or record.get("storeCode") or "").strip().upper()
        row = self.stores.get(code) if code else None
        # A supplied unknown code is never overridden by a similar name.
        if not code:
            candidates = self.names.get(norm(record.get("store_name") or record.get("storeName")), [])
            if len(candidates) == 1:
                row = candidates[0]
        if row:
            out.update({k: row.get(k) for k in ("store_code", "store_name", "retailer_code", "retailer_name", "ss_id", "tl_id")})
            out.update({k: canonical_name(row.get(k)) for k in FIELDS})
            out["alignment_status"] = "STORE_MATCHED"
        else:
            retailer = str(record.get("retailer_code") or "").strip().upper()
            assignments = self.retailers.get(retailer, [])
            out["alignment_status"] = "RETAILER_ONLY" if assignments else "UNMAPPED"
            if assignments:
                out["retailer_name"] = assignments[0]["retailer_name"]
                for k in FIELDS:
                    names = {canonical_name(r.get(k)) for r in assignments}
                    out[k] = next(iter(names)) if len(names) == 1 else None
                out["alignment_assignments"] = [
                    {k: canonical_name(r.get(k)) for k in FIELDS} for r in assignments
                ]
        return out

    def decorate_retailer(self, record, scope=None):
        out = dict(record)
        rows = self.assignments(record.get("code"), scope)
        if not rows:
            return out
        out["assignments"] = [{k: r.get(k) for k in ("store_code", "store_name", "kam", "ss", "ss_id", "tl", "tl_id", "rds")} for r in rows]
        for k in FIELDS:
            out[k] = " | ".join(sorted({canonical_name(r.get(k)) for r in rows}))
        return out

alignment = Alignment(json.loads((Path(__file__).parent / "alignment_2026-10.json").read_text()))
