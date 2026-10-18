"""Ownership protocol v1: labels discover; authenticated durable records authorize.

Provisioning is an internal deployment operation, not a public/model endpoint.
New identities are BLOCKED until a reviewed compatibility record is persisted.
"""
import asyncio
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
from contextlib import contextmanager
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from app.domain.sandbox import SandboxExecution
from app.domain.tasks import AgentTask, TaskApproval
from app.domain.sandbox_ownership import SandboxOwnership, SandboxOwnershipAudit, SandboxRunnerIdentity
from app.sandbox.policy import PolicyViolation, verify_container, validate_execution
from app.schemas.sandbox import POLICY_VERSION
from app.services.tasks import now, check_lease
from app.services.sandbox_maintenance import require_open, dispatch_window
from app.sandbox.history import require_replayable

PROTOCOL = 1
PREFIX = 'ai.agentforge.sandbox.'
FIELDS = ('ownership_protocol_version', 'project_id', 'runner_instance_id', 'runner_generation',
          'sandbox_namespace', 'task_id', 'execution_id', 'policy_version', 'created_at')
ID = re.compile(r'[0-9a-f]{64}\Z')


def require(value, code='SANDBOX_OWNERSHIP_UNVERIFIED'):
    if not value:
        raise PolicyViolation(code)


def labels(record):
    result = {PREFIX + field: str(getattr(record, field)) for field in FIELDS}
    result[PREFIX + 'created_at'] = record.created_at.isoformat()
    return result


async def provision_identity(session, daemon_id, *, project_id=None):
    """Trusted deployment-only primitive; caller owns an administrative DB transaction.

    No clearance parameter or issuance HTTP/CLI is provided. Secret is returned
    as SecretStr, never logged. No existing registration/record is adopted.
    """
    require(isinstance(daemon_id, str) and 1 <= len(daemon_id) <= 128)
    proof = SecretStr(secrets.token_urlsafe(48))
    row = SandboxRunnerIdentity(runner_instance_id=uuid4(), project_id=project_id or uuid4(),
        runner_generation=1, sandbox_namespace=uuid4(), daemon_id=daemon_id,
        proof_hash=hashlib.sha256(proof.get_secret_value().encode()).hexdigest(),
        retired=False, created_at=now())
    session.add(row)
    await session.flush()
    return row, proof


@dataclass(frozen=True)
class Scope:
    project_id: UUID
    runner_instance_id: UUID
    runner_generation: int
    sandbox_namespace: UUID
    daemon_id: str

    def filters(self):
        return [f'{PREFIX}ownership_protocol_version={PROTOCOL}',
                *(PREFIX + name + '=' + str(getattr(self, name)) for name in
                  ('project_id', 'runner_instance_id', 'runner_generation', 'sandbox_namespace'))]


class OwnershipCoordinator:
    def __init__(self, connections, settings, owner):
        self.connections, self.settings, self.owner = connections, settings, owner
        self.scope = None

    async def _identity(self, session, *, claim=False):
        identity = getattr(self.settings, 'sandbox_identity_id', None)
        proof = getattr(self.settings, 'sandbox_identity_proof', None)
        generation = getattr(self.settings, 'sandbox_identity_generation', None)
        require(identity and proof and generation, 'SANDBOX_IDENTITY_NOT_CONFIGURED')
        row = await session.get(SandboxRunnerIdentity, identity, with_for_update=True)
        require(row and not row.retired and hmac.compare_digest(row.proof_hash,
            hashlib.sha256(proof.get_secret_value().encode()).hexdigest()), 'SANDBOX_RUNNER_IDENTITY_INVALID')
        require(row.compatibility_evidence_id and row.compatibility_cleared_at,
                'SANDBOX_COMPATIBILITY_BLOCKED')
        require(row.runner_generation == generation, 'SANDBOX_RUNNER_GENERATION_CHANGED')
        scope = Scope(row.project_id, row.runner_instance_id, row.runner_generation,
                      row.sandbox_namespace, row.daemon_id)
        if self.scope is not None:
            require(scope == self.scope, 'SANDBOX_RUNNER_GENERATION_CHANGED')
        if claim:
            require(not row.lease_until or row.lease_until <= now() or row.process_owner == self.owner,
                    'SANDBOX_RUNNER_ALREADY_ACTIVE')
        else:
            require(row.process_owner == self.owner and row.lease_until and row.lease_until > now(),
                    'SANDBOX_RUNNER_AUTHORITY_EXPIRED')
        return row, scope

    def audit(self, session, action, execution_id=None, container_id=None):
        # Only exact resource identifiers/static actions, never exceptions, code,
        # environment, proofs or arbitrary Docker metadata.
        session.add(SandboxOwnershipAudit(id=uuid4(), runner_instance_id=self.scope.runner_instance_id,
            runner_generation=self.scope.runner_generation, execution_id=execution_id,
            action=action, resource={'container_id': container_id}, created_at=now()))

    async def claim(self):
        async with self.connections.sessions() as session, session.begin():
            row, scope = await self._identity(session, claim=True)
            self.scope = scope
            row.process_owner, row.lease_until = self.owner, now() + timedelta(seconds=30)
            self.audit(session, 'RUNNER_CLAIMED')

    async def refresh(self):
        async with self.connections.sessions() as session, session.begin():
            row, _ = await self._identity(session)
            row.lease_until = now() + timedelta(seconds=30)

    async def release(self):
        async with self.connections.sessions() as session, session.begin():
            row, _ = await self._identity(session)
            row.lease_until = now()
            self.audit(session, 'RUNNER_RELEASED')

    def matches(self, record):
        return self.scope and all(getattr(record, key) == getattr(self.scope, key) for key in
            ('project_id', 'runner_instance_id', 'runner_generation', 'sandbox_namespace'))

    async def issue(self, session, execution):
        await require_open(session)
        await require_replayable(session, execution)
        identity, _ = await self._identity(session)
        # A fresh deployment never adopts pending executions from before its
        # registration/compatibility clearance. They require a new request and
        # approval; migration does not manufacture ownership for old rows.
        require(execution.created_at and execution.created_at >= max(
            identity.created_at, identity.compatibility_cleared_at), 'SANDBOX_LEGACY_EXECUTION_NOT_ADOPTED')
        require(await session.get(SandboxOwnership, execution.id) is None, 'SANDBOX_OWNERSHIP_ALREADY_ISSUED')
        task = await session.get(AgentTask, execution.task_id)
        require(task and task.owner and task.fence > 0)
        record = SandboxOwnership(execution_id=execution.id, task_id=execution.task_id,
            ownership_protocol_version=PROTOCOL, **{key: getattr(self.scope, key) for key in
            ('project_id', 'runner_instance_id', 'runner_generation', 'sandbox_namespace')},
            policy_version=execution.policy_version, image_id=self.settings.sandbox_image_id,
            worker_owner=task.owner, worker_fence=task.fence,
            created_at=now(), state='INTENT')
        session.add(record)
        self.audit(session, 'INTENT_COMMITTED', execution.id)

    async def records(self):
        async with self.connections.sessions() as session:
            await self._identity(session)
            return list((await session.scalars(select(SandboxOwnership).where(
                SandboxOwnership.runner_instance_id == self.scope.runner_instance_id,
                SandboxOwnership.runner_generation == self.scope.runner_generation,
                SandboxOwnership.project_id == self.scope.project_id,
                SandboxOwnership.sandbox_namespace == self.scope.sandbox_namespace,
                SandboxOwnership.state != 'REMOVED'))).all())

    async def refuse_resource(self, execution_id, container_id):
        async with self.connections.sessions() as session, session.begin():
            await self._identity(session)
            self.audit(session, 'RESOURCE_REFUSED', execution_id,
                       container_id if isinstance(container_id, str) and ID.fullmatch(container_id) else None)

    async def action(self, action, execution_id, attrs=None, *, operation_hash=None):
        try:
            return await self._action(action, execution_id, attrs, operation_hash=operation_hash)
        except Exception:
            if self.scope is not None:
                # Rejected boundaries roll back. Persist a separate, minimal
                # refusal record; it never grants a Docker capability.
                async with self.connections.sessions() as session, session.begin():
                    cid = attrs.get('Id') if isinstance(attrs, dict) else None
                    self.audit(session, 'BOUNDARY_REFUSED', execution_id,
                               cid if isinstance(cid, str) and ID.fullmatch(cid) else None)
            raise

    async def _action(self, action, execution_id, attrs=None, *, operation_hash=None):
        """Commit one boundary before external IO. Never hold locks during Docker IO."""
        require(action in {'create', 'bind', 'start', 'inject', 'stop', 'remove', 'removed', 'unknown', 'inspect', 'absent'})
        async with self.connections.sessions() as session, session.begin():
            await self._identity(session)
            record = await session.get(SandboxOwnership, execution_id, with_for_update=True)
            require(record and self.matches(record) and record.ownership_protocol_version == PROTOCOL)
            execution = await session.get(SandboxExecution, execution_id)
            require(execution and execution.task_id == record.task_id and execution.launch_claimed_at
                    and execution.policy_version == record.policy_version == POLICY_VERSION
                    and execution.image_id == record.image_id == self.settings.sandbox_image_id)
            require(execution.container_id in (None, record.container_id), 'SANDBOX_CONTAINER_ID_MISMATCH')
            if action in {'create', 'start', 'inject'}:
                await require_open(session)
                require(operation_hash == execution.operation_hash, 'SANDBOX_INPUT_MISMATCH')
                task = await session.get(AgentTask, record.task_id)
                require(task and task.deadline > now() and task.status in {'running', 'queued'})
                check_lease(task, record.worker_owner, record.worker_fence)
                validate_execution(execution, await session.get(TaskApproval, execution.approval_reference),
                                   task, self.settings)
            if action == 'create':
                require(record.state == 'INTENT' and record.container_id is None,
                        'SANDBOX_CREATE_ALREADY_COMMITTED')
                require(execution.runner_owner == self.owner and execution.runner_lease_until
                        and execution.runner_lease_until > now())
                record.state = 'CREATE_COMMITTED'
            elif action == 'unknown':
                require(record.state != 'REMOVED')
                record.state = 'UNKNOWN'
            elif action in {'inspect', 'absent'}:
                require(attrs and record.container_id and record.container_id == attrs.get('Id'),
                        'SANDBOX_CONTAINER_ID_MISMATCH')
                if action == 'absent':
                    record.state = 'REMOVED'
            else:
                require(isinstance(attrs, dict) and ID.fullmatch(attrs.get('Id', '')))
                cid = attrs['Id']
                require(all((attrs.get('Config', {}).get('Labels') or {}).get(k) == v
                            for k, v in labels(record).items()))
                require(attrs.get('Name', '').lstrip('/') == 'agentforge-p3-exec-' + execution_id.hex)
                verify_container(attrs, record.image_id, execution.resource_limits, execution_id)
                if action == 'bind':
                    require(record.state == 'CREATE_COMMITTED' and record.container_id is None,
                            'SANDBOX_CONTAINER_ALREADY_BOUND')
                    record.container_id, record.state = cid, 'CREATED'
                else:
                    require(record.container_id == cid, 'SANDBOX_CONTAINER_ID_MISMATCH')
                    require(record.state in {'CREATED', 'CLEANUP_INTENT', 'UNKNOWN'})
                    if action in {'start', 'inject'}:
                        require(record.state == 'CREATED' and execution.runner_owner == self.owner
                                and execution.runner_lease_until and execution.runner_lease_until > now())
                    elif action == 'removed':
                        record.state = 'REMOVED'
                    else:
                        record.state = 'CLEANUP_INTENT'
            self.audit(session, action.upper(), execution_id, record.container_id)
            return labels(record)


class ThreadAuthority:
    """Private bridge from the synchronous SDK thread to the trusted DB service."""
    def __init__(self, coordinator, loop):
        require(coordinator.scope is not None)
        self.coordinator, self.loop = coordinator, loop
        self.scope = coordinator.scope

    @contextmanager
    def window(self):
        boundary = dispatch_window(self.coordinator.connections)
        future = asyncio.run_coroutine_threadsafe(boundary.__aenter__(), self.loop)
        try:
            future.result(timeout=10)
        except Exception:
            future.cancel()
            raise PolicyViolation('SANDBOX_MAINTENANCE_BOUNDARY_REFUSED') from None
        try:
            yield
        finally:
            closing = asyncio.run_coroutine_threadsafe(boundary.__aexit__(None, None, None), self.loop)
            try:
                closing.result(timeout=10)
            except Exception:
                closing.cancel()
                raise PolicyViolation('SANDBOX_MAINTENANCE_BOUNDARY_UNCERTAIN') from None

    def refuse(self, container_id):
        future = asyncio.run_coroutine_threadsafe(
            self.coordinator.refuse_resource(None, container_id), self.loop)
        try:
            future.result(timeout=10)
        except Exception:
            future.cancel()
            raise PolicyViolation('SANDBOX_OWNERSHIP_AUDIT_UNAVAILABLE') from None

    def before(self, action, execution_id, attrs=None, *, operation_hash=None):
        future = asyncio.run_coroutine_threadsafe(self.coordinator.action(
            action, execution_id, attrs, operation_hash=operation_hash), self.loop)
        try:
            return future.result(timeout=10)
        except Exception:
            future.cancel()
            raise PolicyViolation('SANDBOX_OWNERSHIP_BOUNDARY_UNCERTAIN') from None
