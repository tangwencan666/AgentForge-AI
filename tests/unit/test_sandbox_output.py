from time import perf_counter
from app.services.context import redact

def test_output_flood_redaction_is_bounded_and_preserves_credentials_filter(settings):
    content="x"*(1024*1024)+" https://private-user:private-value@host.test/path"
    started=perf_counter()
    clean=redact(content,settings)
    assert perf_counter()-started<3, "Bounded output must not monopolize the trusted Runner"
    assert clean.endswith("https://[REDACTED]@host.test/path")
    assert "private-value" not in clean
