"""S1 integration guard: only attested disposable service endpoints are allowed."""
import os
from pathlib import Path
import sys
import pytest
from app.core.config import ROOT

_allowed_endpoints = frozenset()


def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve() == (ROOT / '.env').resolve():
            raise RuntimeError('OFFLINE_PROJECT_ENV_READ_FORBIDDEN')
    if event == 'socket.connect' and sys.platform == 'win32':
        caller = sys._getframe(1).f_code
        if (caller.co_name == '_fallback_socketpair' and Path(caller.co_filename).name == 'socket.py'
                and args[1][0] in {'127.0.0.1', '::1'}):
            return
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        address = args[1] if event == 'socket.connect' else args[:2]
        if (not isinstance(address, tuple) or len(address) < 2
                or (address[0], address[1]) not in _allowed_endpoints):
            raise RuntimeError('S1_NETWORK_ENDPOINT_FORBIDDEN')


def verified_endpoints(verified):
    # Runner is deliberately excluded from the S1 network capability.
    return frozenset(('127.0.0.1', verified['ports'][name])
                     for name in ('postgres', 'redis', 'backend', 'frontend'))


def install_verified_guard(verified):
    """Called only after resource attestation; conftest also covers direct pytest."""
    global _allowed_endpoints
    _allowed_endpoints = verified_endpoints(verified)
    sys.addaudithook(audit)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    locator = os.environ.get('AGENTFORGE_S1_MANIFEST')
    if not locator:
        raise pytest.UsageError('S1_ISOLATION_MANIFEST_REQUIRED')
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        from s1_isolation import validate_isolation
        verified = validate_isolation(ROOT, Path(locator))
    except Exception:
        raise pytest.UsageError('S1_ISOLATION_UNVERIFIED') from None
    if (not os.environ.get('AGENTFORGE_SETTINGS_FILE')
            or Path(os.environ['AGENTFORGE_SETTINGS_FILE']).resolve() != Path(verified['settings_path']).resolve()
            or any(name in os.environ for name in ('AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL'))):
        raise pytest.UsageError('S1_SETTINGS_REFERENCE_MISMATCH')
    install_verified_guard(verified)


@pytest.fixture(autouse=True)
def allow_only_explicit_mock_transport_tests(request, monkeypatch):
    if request.node.path.name in {'test_model_adapter.py', 'test_deepseek.py'} and 'egress' not in request.node.name:
        monkeypatch.setattr('app.providers.openai_compatible.assert_model_egress', lambda: None)
