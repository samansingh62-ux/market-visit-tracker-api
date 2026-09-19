"""
Simple API-key authentication.

Set API_KEY in the environment (see .env.example) to require callers to
send it in the `X-API-Key` header for every request. Set ADMIN_API_KEY
to require a separate, stronger key for destructive operations (deleting
visits); if ADMIN_API_KEY is not set, it falls back to API_KEY.

If API_KEY is left unset entirely, authentication is disabled - useful
for local development only. Always set API_KEY before deploying anywhere
reachable from outside your machine.
"""

import os

from fastapi import Header, HTTPException, status

API_KEY = os.environ.get("API_KEY", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", API_KEY)


async def require_api_key(x_api_key: str = Header(default="")):
    if not API_KEY:
        # No key configured - auth disabled (local dev only).
        return
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header.",
        )


async def require_admin_key(x_api_key: str = Header(default="")):
    if not ADMIN_API_KEY:
        return
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header for this admin action.",
        )
