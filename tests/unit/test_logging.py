import json
import logging
import secrets
from app.core.logging import JsonFormatter, request_id_var


def test_dynamic_logs_and_exception_content_are_not_serialized():
    secret = secrets.token_hex(32)
    record = logging.LogRecord("driver", logging.ERROR, "test", 1, "failure " + secret, (), None)
    record.exc_text = "connection string " + secret
    rendered = JsonFormatter().format(record)
    assert secret not in rendered
    assert json.loads(rendered)["event"] == "log_event"


def test_structured_log_keeps_only_safe_fields():
    record = logging.LogRecord("agentforge", logging.INFO, "test", 1, "request_completed", (), None)
    record.status = 200
    record.authorization = "sensitive-header"
    token = request_id_var.set("unit-request")
    try:
        data = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert data["request_id"] == "unit-request"
    assert data["status"] == 200
    assert "authorization" not in data


def test_unknown_http_method_cannot_echo_a_secret_into_logs():
    secret=secrets.token_hex(32)
    record=logging.LogRecord('agentforge',logging.INFO,'test',1,'request_completed',(),None)
    record.method=secret
    rendered=JsonFormatter().format(record)
    assert secret not in rendered
    assert json.loads(rendered)['method']=='OTHER'
