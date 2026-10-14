from time import perf_counter
from uuid import UUID, uuid4
import logging
from app.core.logging import request_id_var

logger = logging.getLogger("agentforge")


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        raw = dict(scope.get("headers", [])).get(b"x-request-id", b"")
        try:
            request_id = str(UUID(raw.decode("ascii")))
        except (ValueError, UnicodeError):
            request_id = str(uuid4())
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        start, status = perf_counter(), 500

        async def safe_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id.encode()), (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"),
                ]
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        finally:
            logger.info("request_completed", extra={"method": scope["method"], "status": status,
                                                    "duration_ms": round((perf_counter() - start) * 1000, 2)})
            request_id_var.reset(token)
