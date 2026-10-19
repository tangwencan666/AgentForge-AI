"""Explicit clock/identity stubs: expiry at consume, no native process actions."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import lifecycle_v2 as v2


@pytest.mark.parametrize('wall_offset', [61, -61])
def test_approval_expiring_during_identity_reconciliation_is_never_consumed(tmp_path, monkeypatch, wall_offset):
    clock = SimpleNamespace(offset=0)
    monkeypatch.setattr(v2, 'time', SimpleNamespace(time=lambda: 1000 + (wall_offset if clock.offset else 0),
                                                 monotonic=lambda: 100 + clock.offset))
    monkeypatch.setattr(v2, 'operation_lock', lambda _: nullcontext())
    actor = dict(pid=1, created=2, executable=str(tmp_path / 'python.exe'),
                 user_sid='S-1-5-21-1', logon_sid='S-1-5-5-1-2', session_id=1)
    monkeypatch.setattr(v2, 'actor_identity', lambda: actor)
    manager = object.__new__(v2.LifecycleManagerV2)
    manager.directory = tmp_path
    manager.backend = SimpleNamespace(is_test=True)
    state = {'generation': 1, 'entries': {}}
    manager._preflight_format = lambda: None
    manager._load = lambda: state
    entry = dict(role='worker', instance_id='00000000-0000-0000-0000-000000000001',
                 generation=1, pid=1, created=2, status='running')
    calls = []
    def reconcile(*_):
        calls.append('reconcile')
        if len(calls) == 2:
            clock.offset = 61
        return [entry]
    manager._manual_candidates = reconcile
    manager._audit = lambda *args: None
    manager._stop_entries = lambda *args: pytest.fail('Expired scope reached process stop')
    with pytest.raises(v2.LifecycleError, match='APPROVAL_REQUIRED'):
        manager.manual_stop(confirmation=lambda scope: scope['challenge'])
    records = list((tmp_path / 'approvals').glob('*.json'))
    assert len(records) == 1
    assert json.loads(records[0].read_text())['status'] == 'EXPIRED'


@pytest.mark.parametrize('failure,reason', [
    (v2.LifecycleError('PROCESS_DISCOVERY_FAILED'), 'PROCESS_DISCOVERY_FAILED'),
    (RuntimeError('EXPLICIT-FAKE-CREDENTIAL-DO-NOT-LOG'), 'LIFECYCLE_OPERATION_FAILED')])
def test_failed_start_preserves_recovery_and_only_audits_normalized_reason(monkeypatch, failure, reason):
    manager = object.__new__(v2.LifecycleManagerV2)
    actor = {'pid': 123, 'created': 456}
    spec = {'role': 'backend', 'instance_id': '00000000-0000-0000-0000-000000000001', 'creator': actor}
    manager._spec = lambda *_: spec
    def failed_launch(_):
        raise failure
    manager.backend = SimpleNamespace(launch=failed_launch)
    manager._save = lambda _: None
    records = []
    manager._audit = lambda action, entries, **options: records.append({'action': action, **options})
    state = {'entries': {}}
    with pytest.raises(v2.LifecycleError, match='START_UNCERTAIN'):
        manager._start_roles(state, ['backend'], 'mock')
    assert state['entries']['backend']['status'] == 'unknown'
    assert records[-1] == {'action': 'start_failed', 'reason': reason}
    assert 'EXPLICIT-FAKE-CREDENTIAL' not in json.dumps(records)
