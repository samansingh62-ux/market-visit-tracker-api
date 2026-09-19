"""Authentication and hierarchy-aware authorization."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

API_KEY = os.environ.get("API_KEY", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", API_KEY)
AUTH_SECRET = os.environ.get("AUTH_SECRET") or API_KEY

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, digest_b64 = stored.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


ddef create_token(user: dict, ttl_seconds: int = 12 * 3600) -> str:
    if not AUTH_SECRET:
        raise RuntimeError("AUTH_SECRET environment variable is not set")

    payload = {
        "sub": user["username"],
        "name": user["name"],
        "role": user["role"],
        "tl": user.get("tl"),
        "ss": user.get("ss"),
        "rds": user.get("rds"),
        "exp": int(time.time()) + ttl_seconds,
    }

    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(
        hmac.new(
            AUTH_SECRET.encode(),
            body.encode(),
            hashlib.sha256,
        ).digest()
    )

    return body + "." + sig


def decode_token(token: str) -> dict:
    if not AUTH_SECRET or "." not in token:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(AUTH_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Authentication token expired.")
    return payload


async def require_admin_key(x_api_key: str | None = Security(api_key_header)):
    if not ADMIN_API_KEY or x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid admin API key.")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer),
    x_api_key: str | None = Security(api_key_header),
):
    # Keep the existing manager/API-key path working.
    if x_api_key and API_KEY and hmac.compare_digest(x_api_key, API_KEY):
        return {"name": "Manager", "role": "MANAGER", "tl": None, "ss": None, "rds": None}
    if credentials:
        return decode_token(credentials.credentials)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")


def require_manager(user: dict):
    if user.get("role") != "MANAGER":
        raise HTTPException(status_code=403, detail="Manager access required.")
    return user
