"""Offline DB faults/retirement Stub policy; not production exit evidence."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import SecretStr
from app.core.errors import AppError
from app.services.sandbox_maintenance import (MaintenancePrincipal, require_open, public_state)
from app.sandbox.retirement import RetirementObservation, assess_retirement


class Session:
    def __init__(self, row=None, error=None): self.row, self.error = row, error
    async def scalars(self, _):
        if self.error: raise self.error
        return self
    def one_or_none(self): return self.row


@pytest.mark.parametrize('row', [None, SimpleNamespace(epoch=0, state='OPEN'),
    SimpleNamespace(epoch=1, state='CORRUPT')])
async def test_missing_or_corrupt_state_refuses(row):
    with pytest.raises(AppError, match='SANDBOX_MAINTENANCE_UNAVAILABLE'):
        await require_open(Session(row))


@pytest.mark.parametrize('state', ['DRAINING', 'FROZEN'])
async def test_environment_cannot_override_persistent_freeze(monkeypatch, state):
    monkeypatch.setenv('AGENTFORGE_SANDBOX_FROZEN', 'false')
    monkeypatch.setenv('AGENTFORGE_SKIP_GUARD', '1')
    row = SimpleNamespace(epoch=2, state=state, deployment_id=uuid4(), daemon_id='stub')
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await require_open(Session(row))


async def test_policy_unavailable_is_closed_without_echoing_exception():
    class Broken:
        def sessions(self): raise OSError('synthetic-secret-only')
    result = await public_state(Broken())
    assert result == {'state': 'UNVERIFIED', 'epoch': None, 'admission_open': False}
    assert 'synthetic-secret-only' not in str(result)


def test_principal_repr_never_contains_private_proof():
    principal = MaintenancePrincipal(uuid4(), SecretStr('synthetic-control-proof-only'))
    assert 'synthetic-control-proof-only' not in repr(principal)


def observation():
    return RetirementObservation('stub-daemon', 'a'*64, 'sha256:'+'b'*64, '2026-10-18', 0,
        False, 0, 'no', 0, 0, 0, 0, 0, True, True)


@pytest.mark.parametrize('change,code', [({'running': True}, 'OLD_PROCESS_NOT_EXITED'),
    ({'pid': 123}, 'OLD_PROCESS_NOT_EXITED'), ({'restart_policy': 'unless-stopped'}, 'OLD_RESTART_PATH_OPEN'),
    ({'restart_sources_reviewed': False}, 'OLD_RESTART_PATH_OPEN'), ({'active_executions': 1}, 'EXECUTION_NOT_DRAINED'),
    ({'dispatch_windows': 1}, 'EXECUTION_NOT_DRAINED'), ({'control_processes': 1}, 'CONTROL_PROCESS_UNRESOLVED'),
    ({'old_database_connections': 1}, 'CONTROL_PROCESS_UNRESOLVED'), ({'unclassified_resources': 1}, 'RESOURCE_UNVERIFIED'),
    ({'admission_closed': False}, 'ADMISSION_NOT_CLOSED'), ({'container_id': 'c'*64}, 'TARGET_CHANGED')])
def test_old_runner_restart_and_unknown_observations_block(change, code):
    first = observation()
    result = assess_retirement(first, replace(first, observed_at=61, **change))
    assert result['offline_checklist'] == 'BLOCKED' and code in result['reasons']
    assert not result['deployment_authorized'] and not result['physical_exit_proven']


def test_two_quiet_samples_cannot_authorize_actual_retirement():
    first = observation()
    assert assess_retirement(first, replace(first, observed_at=2))['offline_checklist'] == 'BLOCKED'
    result = assess_retirement(first, replace(first, observed_at=61))
    assert result['offline_checklist'] == 'SATISFIED'
    assert result['deployment_authorized'] is result['physical_exit_proven'] is False


@pytest.mark.parametrize('change', [{'observed_at': float('nan')}, {'observed_at': float('inf')},
    {'container_id': 'forged'}, {'image_id': 'latest'}, {'observed_at': True}])
def test_untrusted_retirement_evidence_never_passes(change):
    assert assess_retirement(observation(), replace(observation(), **change))['offline_checklist'] == 'BLOCKED'
