import os
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
from contextlib import contextmanager
from fastapi.testclient import TestClient
from app.main import app
from app import crud
from app.auth import require_admin_key


def test_rds_pin_login_is_included_and_duplicate_matches_fail(monkeypatch):
    class Conn:
        def execute(self, sql):
            assert "'RDS'" in sql
            return self
        def fetchall(self):
            return [{"role": "RDS", "name": "Distributor", "pin_hash": "saved"}]
    @contextmanager
    def connection():
        yield Conn()
    monkeypatch.setattr(crud.database, "get_conn", connection)
    monkeypatch.setattr(crud, "verify_password", lambda pin, hashed: True)
    assert crud.get_user_by_pin("1234")["role"] == "RDS"


def test_missing_pins_preserve_existing_and_avoid_collisions(monkeypatch):
    import secrets
    from app import auth
    updates = []
    class Conn:
        def execute(self, sql, params=None):
            if sql.startswith("UPDATE"):
                updates.append(params)
            return self
        def fetchall(self):
            return [
                {"id": 1, "role": "TL", "name": "TL", "username": "tl", "pin_hash": "existing"},
                {"id": 2, "role": "RDS", "name": "RDS", "username": "rds", "pin_hash": None},
                {"id": 3, "role": "RDS", "name": "RDS Existing", "username": "rds2", "pin_hash": "existing2"},
            ]
    @contextmanager
    def connection():
        yield Conn()
    candidates = iter([111, 222])
    monkeypatch.setattr(crud.database, "get_conn", connection)
    monkeypatch.setattr(secrets, "randbelow", lambda _: next(candidates))
    monkeypatch.setattr(crud, "verify_password", lambda pin, hashed: pin == "1111")
    monkeypatch.setattr(auth, "hash_password", lambda pin: "hashed:" + pin)
    assert crud.create_missing_rds_pins() == [{"name": "RDS", "username": "rds", "pin": "1222"}]
    assert updates == [("hashed:1222", 2)]


def test_provisioning_requires_admin_and_returns_private_download(monkeypatch):
    client = TestClient(app)
    assert client.post("/admin/users/rds/create-missing-pins").status_code == 401
    monkeypatch.setattr(crud, "create_missing_rds_pins", lambda: [])
    app.dependency_overrides[require_admin_key] = lambda: None
    try:
        response = client.post("/admin/users/rds/create-missing-pins")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-pins-created"] == "0"
        assert response.text.strip() == "RDS,Username,PIN"
    finally:
        app.dependency_overrides.pop(require_admin_key, None)
