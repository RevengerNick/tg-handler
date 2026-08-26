from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .routes import router


logger = logging.getLogger("telegram_reader.api")
logger.setLevel(logging.INFO)


class ReaderSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, runtime: Any):
        super().__init__(app)
        self.runtime = runtime
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > self.runtime.settings.body_limit_bytes:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413, headers={"X-Request-Id": request_id})
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400, headers={"X-Request-Id": request_id})
        body = await request.body()
        if len(body) > self.runtime.settings.body_limit_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413, headers={"X-Request-Id": request_id})
        identity = request.headers.get("CF-Access-Client-Id") or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        window = self.requests[identity]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self.runtime.settings.rate_limit_per_minute:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"X-Request-Id": request_id})
        window.append(now)
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        logger.info(json.dumps({
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }, separators=(",", ":")))
        return response


def attach_reader_api(app: Any, runtime: Any | None = None) -> Any:
    if getattr(app.state, "telegram_reader_attached", False):
        return app.state.telegram_reader
    if runtime is None:
        from ..runtime import get_runtime
        reader_runtime = get_runtime()
    else:
        reader_runtime = runtime
    app.state.telegram_reader = reader_runtime
    app.state.telegram_reader_attached = True
    app.add_middleware(ReaderSecurityMiddleware, runtime=reader_runtime)
    app.include_router(router)
    return reader_runtime
