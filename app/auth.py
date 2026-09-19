"""
Simple API-key authentication.

Set API_KEY in the environment to require callers to send it
in the X-API-Key header.

Set ADMIN_API_KEY to require a separate key for destructive
operations. If ADMIN_API_KEY is not set, it falls back to API_KEY.
"""

import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY = os.environ.get("API_KEY", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", API_KEY)

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


async def require_api_key(
    x_api_key: str | None = Security(api_key_header),
):
    if not API_KEY:
        # No key configured - auth disabled (local development only).
        return

    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header.",
        )


async def require_admin_key(
    x_api_key: str | None = Security(api_key_header),
):
    if not ADMIN_API_KEY:
        return

    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header for this admin action.",
        )
