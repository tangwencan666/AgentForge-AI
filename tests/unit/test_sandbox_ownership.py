"""Offline protocol/entry checks; no real daemon, database or provider."""
from threading import Event
from queue import Queue
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.sandbox.driver import DockerDriver
from app.sandbox.ownership import Scope, PREFIX
from app.sandbox.policy import PolicyViolation, OWNER_LABEL, create_options
from app.schemas.sandbox import SandboxCreate, RunnerDispatch, POLICY_VERSION, ResourceLimits


def test_driver_without_durable_authority_refuses_before_client_access():
    driver = DockerDriver('sha256:' + 'a' * 64)
    driver.client = lambda: pytest.fail('An unbound driver must never access a Docker daemon')
    with pytest.raises(PolicyViolation, match='SANDBOX_OWNERSHIP_REQUIRED'):
        driver.owned()
    result = driver.run(uuid4(), 'print(1)', ResourceLimits().model_dump(), 1, Event(), Event(), Queue())
    assert result.failure_reason == 'SANDBOX_OWNERSHIP_REQUIRED' and result.cleanup_status == 'not_created'


@pytest.mark.parametrize('field', ['ownership_protocol_version', 'project_id', 'runner_instance_id',
    'runner_generation', 'sandbox_namespace', 'container_id', 'created_at'])
def test_public_and_worker_requests_cannot_supply_ownership(field):
    with pytest.raises(ValidationError):
        SandboxCreate(code='print(1)', **{field: 'forged'})
    with pytest.raises(ValidationError):
        RunnerDispatch(task_id=uuid4(), execution_id=uuid4(), owner='worker', fence=1, **{field: 'forged'})


def test_discovery_filter_binds_project_instance_generation_namespace():
    a = Scope(uuid4(), uuid4(), 1, uuid4(), 'stub-daemon')
    b = Scope(a.project_id, uuid4(), 2, uuid4(), 'stub-daemon')
    assert len(a.filters()) == 5 and a.filters() != b.filters()
    assert all(item.startswith(PREFIX) for item in a.filters())
    assert not any(item.startswith(OWNER_LABEL) for item in a.filters())


def test_legacy_global_filter_still_discovers_new_ownership_labels_coexistence_blocked():
    # Explicit reproduction of OLD Runner discovery, not a claim of coexistence.
    opts = create_options('sha256:' + 'a' * 64, uuid4(), ResourceLimits().model_dump())
    opts['labels'][PREFIX + 'ownership_protocol_version'] = '1'
    opts['labels'][PREFIX + 'runner_instance_id'] = str(uuid4())
    assert opts['labels'][OWNER_LABEL] == POLICY_VERSION
    # Thus new per-instance filters cannot restrict the old Runner's query.
    assert opts['network_mode'] == 'none' and opts['read_only'] and opts['cap_drop'] == ['ALL']


def test_identity_proof_is_hidden_and_redacted(settings):
    from pydantic import SecretStr
    from app.services.context import redact
    synthetic = 's3a-test-only-private-runner-proof'
    configured = settings.model_copy(update={'sandbox_identity_proof': SecretStr(synthetic)})
    assert synthetic not in repr(configured)
    assert synthetic not in redact('prefix ' + synthetic, configured)


async def test_missing_business_execution_fails_closed_with_explicit_db_stub(monkeypatch):
    """Corrupt/missing read fault; real PG normally prevents it with the FK.

    This is a DB Stub, not PostgreSQL deletion/constraint acceptance evidence.
    """
    from app.domain.sandbox_ownership import SandboxOwnership
    from app.sandbox.ownership import OwnershipCoordinator
    scope = Scope(uuid4(), uuid4(), 1, uuid4(), 'stub-daemon')
    record = SimpleNamespace(ownership_protocol_version=1, **{
        name: getattr(scope, name) for name in
        ('project_id', 'runner_instance_id', 'runner_generation', 'sandbox_namespace')})
    events = []

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def begin(self): return self
        async def get(self, model, *_args, **_kwargs):
            return record if model is SandboxOwnership else None
        def add(self, event): events.append(event)

    co = OwnershipCoordinator(SimpleNamespace(sessions=Session), SimpleNamespace(), 'stub-owner')
    co.scope = scope
    async def trusted_registration(*_args, **_kwargs): return None, scope
    monkeypatch.setattr(co, '_identity', trusted_registration)
    with pytest.raises(PolicyViolation):
        await co.action('stop', uuid4(), {'Id': 'a' * 64})
    assert [event.action for event in events] == ['BOUNDARY_REFUSED']
