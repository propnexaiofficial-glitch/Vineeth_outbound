"""
auth_middleware.py — API key authentication middleware.

Validates X-API-Key or Authorization: Bearer <token> headers against
the api_keys table (SHA-256 hash lookup). Attaches tenant_id and role
to request.state on success.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import pg_db

logger = logging.getLogger(__name__)

# Paths that bypass authentication entirely
_SKIP_PATHS = {"/health", "/exoml", "/call-status", "/api/events/stream"}
_SKIP_PREFIX = ("/ws/", "/api/")  # skip auth for all /api/* routes


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via API key (header or Bearer token)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public / webhook / WebSocket paths
        if path in _SKIP_PATHS or path.startswith(_SKIP_PREFIX):
            return await call_next(request)

        raw_key = _extract_key(request)
        if not raw_key:
            return _unauthorized()

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        try:
            pool = pg_db.get_pool()
            record = pg_db.get_api_key_by_hash(pool, key_hash)
        except Exception:
            logger.exception("DB error during API key lookup")
            return _unauthorized()

        if not record:
            return _unauthorized()

        # Attach identity to request state
        request.state.tenant_id = record["tenant_id"]
        request.state.role = record["role"]

        # Fire-and-forget last_used update (best-effort, non-blocking)
        try:
            _update_last_used(record["key_id"])
        except Exception:
            logger.warning("Failed to update last_used for key %s", record["key_id"])

        return await call_next(request)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_key(request: Request) -> str | None:
    """Return the raw API key from X-API-Key or Authorization: Bearer."""
    key = request.headers.get("X-API-Key")
    if key:
        return key.strip()

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None

    return None


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Invalid or missing API key"},
    )


def _update_last_used(key_id: str) -> None:
    """Update the last_used timestamp for the given API key."""
    with pg_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE api_keys SET last_used = %s WHERE key_id = %s",
                (datetime.now(timezone.utc), key_id),
            )
