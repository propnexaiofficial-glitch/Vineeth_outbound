"""Rate limiting middleware using an in-memory sliding window per tenant."""
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self, limit: int = 100, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, tenant_id: str) -> bool:
        """Return True if the request is allowed, False if rate limit exceeded."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows[tenant_id]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.limit:
                return False
            window.append(now)
            return True

    def reset(self, tenant_id: str) -> None:
        with self._lock:
            self._windows[tenant_id] = deque()

    def seconds_until_reset(self, tenant_id: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows[tenant_id]
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                return 0
            oldest = window[0]
        return max(1, int((oldest + self.window_seconds) - now) + 1)


_SKIP_PATHS = {"/health", "/exoml", "/call-status"}
_UPLOAD_LIMITER = SlidingWindowRateLimiter(limit=10, window_seconds=60)
_DEFAULT_LIMITER = SlidingWindowRateLimiter(limit=100, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-tenant sliding window rate limits."""

    def __init__(self, app, default_limiter=None, upload_limiter=None) -> None:
        super().__init__(app)
        self._default = default_limiter or _DEFAULT_LIMITER
        self._upload = upload_limiter or _UPLOAD_LIMITER

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in _SKIP_PATHS or path.startswith("/ws/"):
            return await call_next(request)

        tenant_id: str = getattr(request.state, "tenant_id", None) or (
            request.client.host if request.client else "unknown"
        )

        is_upload = path.startswith("/upload") or (
            path.startswith("/api/campaigns") and request.method == "POST"
        )
        limiter = self._upload if is_upload else self._default

        if not limiter.check(tenant_id):
            retry_after = limiter.seconds_until_reset(tenant_id)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
