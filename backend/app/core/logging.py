"""Allowlist structured logs; never serialize exception values or request bodies."""
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
ALLOWED_FIELDS = {"method", "status", "duration_ms", "dependency", "error_type"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Dynamic message text can contain credentials; only static event IDs are accepted.
        event = record.msg if isinstance(record.msg, str) and record.msg in {
            "request_completed", "request_failed", "dependency_failed", "application_started", "application_stopped"
        } else "log_event"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname, "event": event,
            "request_id": request_id_var.get(),
        }
        for key in ALLOWED_FIELDS:
            if key in record.__dict__:
                value = record.__dict__[key]
                if key == "method":
                    value = value if value in {"GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"} else "OTHER"
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("sqlalchemy.engine", "sqlalchemy.pool", "asyncpg", "httpx", "httpcore", "redis"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # Uvicorn access logs include user-controlled URL/query strings.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").handlers = [handler]
    logging.getLogger("uvicorn.error").propagate = False
    return logging.getLogger("agentforge")
