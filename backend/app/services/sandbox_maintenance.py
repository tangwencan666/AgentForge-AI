"""Fail-closed admission and private two-principal thaw authorization.

No public control endpoint/config override exists. Provisioning is deployment-only.
The DB/daemon administrator is trusted. Secrets never enter DTOs or audit records.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import hmac
import secrets
from functools import wraps
from uuid import UUID, uuid4
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from app.core.errors import AppError
from app.domain.sandbox import SandboxExecution
from app.domain.sandbox_ownership import SandboxOwnership, SandboxRunnerIdentity
from app.domain.sandbox_maintenance import (SandboxMaintenance, SandboxMaintenanceAuthority,
    SandboxMaintenanceAudit, SandboxThawGrant)
from app.services.tasks import now

DISPATCH_LOCK = 735031021
MAINTENANCE_ERRORS = frozenset({'SANDBOX_FROZEN', 'SANDBOX_MAINTENANCE_UNAVAILABLE'})


def require(value, code='SANDBOX_MAINTENANCE_FORBIDDEN'):
    if not value:
        raise AppError(code, 'Sandbox maintenance boundary refused', 503 if code in MAINTENANCE_ERRORS else 403)


async def state_row(session, *, write=False, admission=False):
    try:
        query = select(SandboxMaintenance).where(SandboxMaintenance.id == 1).execution_options(populate_existing=True)
        if write or admission:
            query = query.with_for_update(read=not write)
        row = (await session.scalars(query)).one_or_none()
        require(row and row.epoch > 0 and row.state in {'OPEN', 'DRAINING', 'FROZEN'}
                and row.deployment_id and row.daemon_id, 'SANDBOX_MAINTENANCE_UNAVAILABLE')
        return row
    except SQLAlchemyError:
        raise AppError('SANDBOX_MAINTENANCE_UNAVAILABLE', 'Sandbox maintenance state unavailable', 503) from None


async def require_open(session, *, lock=True):
    row = await state_row(session, admission=lock)
    require(row.state == 'OPEN', 'SANDBOX_FROZEN')
    return row.epoch


async def admission_available(session):
    try:
        await require_open(session)
        return True
    except AppError as error:
        if error.code in MAINTENANCE_ERRORS:
            return False
        raise


async def public_state(connections):
    try:
        async with connections.sessions() as session:
            row = await state_row(session)
            return {'state': row.state, 'epoch': row.epoch, 'admission_open': row.state == 'OPEN'}
    except Exception:
        return {'state': 'UNVERIFIED', 'epoch': None, 'admission_open': False}


@asynccontextmanager
async def dispatch_window(connections):
    """Bounded HTTP/create/start/send only, never whole execution/stream.

    The shared advisory transaction lock fences seal_freeze(), including the
    gap between authorization commit and external IO. No business row lock is
    held across IO. DRAINING refuses newcomers; FROZEN is sealed only after all
    admitted windows exit. An ambiguous Docker result still needs reconciliation.
    """
    async with connections.sessions() as session, session.begin():
        try:
            await session.execute(text("SET LOCAL statement_timeout='5s'"))
            await session.execute(text('SELECT pg_advisory_xact_lock_shared(:key)'), {'key': DISPATCH_LOCK})
            await require_open(session, lock=False)
        except SQLAlchemyError:
            raise AppError('SANDBOX_MAINTENANCE_UNAVAILABLE', 'Sandbox dispatch boundary unavailable', 503) from None
        yield


@dataclass(frozen=True)
class MaintenancePrincipal:
    identity: UUID
    proof: SecretStr = field(repr=False)


def audit(session, row, action, actor=None, grant=None):
    session.add(SandboxMaintenanceAudit(id=uuid4(), deployment_id=row.deployment_id,
        epoch=row.epoch, action=action, actor_id=actor, grant_id=grant, created_at=now()))


def audited_control(action):
    def decorate(function):
        @wraps(function)
        async def guarded(connections, *args, **kwargs):
            try:
                return await function(connections, *args, **kwargs)
            except (AppError, SQLAlchemyError) as error:
                # Refusal survives the rolled-back control transaction. An
                # unverified caller never supplies the actor/resource payload.
                try:
                    async with connections.sessions() as session, session.begin():
                        row = await state_row(session)
                        audit(session, row, action)
                except Exception:
                    pass  # Still refuse; an unavailable DB cannot grant admission.
                if isinstance(error, SQLAlchemyError):
                    raise AppError('SANDBOX_MAINTENANCE_UNAVAILABLE', 'Sandbox maintenance control unavailable', 503) from None
                raise
        return guarded
    return decorate


async def provision_maintenance(session, daemon_id):
    """Trusted install primitive. Empty DB control only; NEVER adopts main state."""
    require(isinstance(daemon_id, str) and 0 < len(daemon_id) <= 128)
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': DISPATCH_LOCK})
    require(await session.get(SandboxMaintenance, 1) is None)
    row = SandboxMaintenance(id=1, deployment_id=uuid4(), daemon_id=daemon_id,
        epoch=1, state='FROZEN', updated_at=now())
    session.add(row)
    principals = []
    for kind in ('operator', 'approver'):
        proof = SecretStr(secrets.token_urlsafe(48))
        identity = uuid4()
        session.add(SandboxMaintenanceAuthority(id=identity, deployment_id=row.deployment_id,
            kind=kind, proof_hash=hashlib.sha256(proof.get_secret_value().encode()).hexdigest(), revoked=False))
        principals.append(MaintenancePrincipal(identity, proof))
    audit(session, row, 'PROVISIONED_FROZEN')
    await session.flush()
    return row, tuple(principals)


async def authenticate(session, row, principal, kind):
    require(type(principal) is MaintenancePrincipal)
    authority = await session.get(SandboxMaintenanceAuthority, principal.identity, with_for_update=True)
    require(authority and not authority.revoked and authority.kind == kind
        and authority.deployment_id == row.deployment_id
        and hmac.compare_digest(authority.proof_hash, hashlib.sha256(principal.proof.get_secret_value().encode()).hexdigest()))


@audited_control('FREEZE_REFUSED')
async def freeze(connections, operator):
    async with connections.sessions() as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='5s'"))
        row = await state_row(session, write=True)
        await authenticate(session, row, operator, 'operator')
        # A fresh request invalidates every older thaw grant, even already frozen.
        row.epoch += 1
        row.state, row.updated_at = 'DRAINING', now()
        audit(session, row, 'FREEZE_REQUESTED', operator.identity)
    return await seal_freeze(connections, operator)


@audited_control('SEAL_REFUSED')
async def seal_freeze(connections, operator):
    async with connections.sessions() as session, session.begin():
        # Try, never wait holding state row against admitted IO.
        acquired = await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': DISPATCH_LOCK})
        row = await state_row(session, write=True)
        await authenticate(session, row, operator, 'operator')
        require(row.state in {'DRAINING', 'FROZEN'})
        if acquired:
            row.state, row.updated_at = 'FROZEN', now()
            audit(session, row, 'FREEZE_SEALED', operator.identity)
        return {'state': row.state, 'epoch': row.epoch,
                'dispatch_windows_drained': bool(acquired), 'runner_quiescence_proven': False}


async def target(session, row, identity, generation, evidence):
    runner = await session.get(SandboxRunnerIdentity, identity)
    require(runner and not runner.retired and runner.runner_generation == generation
        and runner.daemon_id == row.daemon_id and runner.compatibility_evidence_id == evidence
        and runner.compatibility_cleared_at is not None)
    # Review metadata is necessary, never a substitute for physical old-Runner exit.
    return runner


@audited_control('THAW_ISSUANCE_REFUSED')
async def issue_thaw(connections, approver, operator_id, runner_id, generation, *, ttl=60):
    require(type(ttl) is int and 0 < ttl <= 60)
    async with connections.sessions() as session, session.begin():
        row = await state_row(session, write=True)
        await authenticate(session, row, approver, 'approver')
        require(row.state == 'FROZEN')
        operator = await session.get(SandboxMaintenanceAuthority, operator_id)
        require(operator and not operator.revoked and operator.kind == 'operator'
                and operator.deployment_id == row.deployment_id and operator_id != approver.identity)
        runner = await session.get(SandboxRunnerIdentity, runner_id)
        require(runner is not None)
        await target(session, row, runner_id, generation, runner.compatibility_evidence_id)
        grant = SandboxThawGrant(id=uuid4(), deployment_id=row.deployment_id, freeze_epoch=row.epoch,
            operator_id=operator_id, approver_id=approver.identity, runner_instance_id=runner_id,
            runner_generation=generation, daemon_id=row.daemon_id,
            evidence_id=runner.compatibility_evidence_id, expires_at=now()+timedelta(seconds=ttl), status='ISSUED')
        session.add(grant)
        audit(session, row, 'THAW_AUTHORIZED', approver.identity, grant.id)
        return grant.id


@audited_control('THAW_REFUSED')
async def thaw(connections, operator, grant_id):
    async with connections.sessions() as session, session.begin():
        require(await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': DISPATCH_LOCK}))
        row = await state_row(session, write=True)
        await authenticate(session, row, operator, 'operator')
        grant = await session.get(SandboxThawGrant, grant_id, with_for_update=True)
        require(row.state == 'FROZEN' and grant and grant.status == 'ISSUED' and grant.expires_at > now()
            and grant.freeze_epoch == row.epoch and grant.deployment_id == row.deployment_id
            and grant.operator_id == operator.identity and grant.daemon_id == row.daemon_id)
        approver = await session.get(SandboxMaintenanceAuthority, grant.approver_id, with_for_update=True)
        require(approver and not approver.revoked and approver.kind == 'approver'
                and approver.deployment_id == row.deployment_id)
        await target(session, row, grant.runner_instance_id, grant.runner_generation, grant.evidence_id)
        unknown = await session.scalar(select(func.count()).select_from(SandboxExecution).where(
            (SandboxExecution.status == 'needs_reconciliation') | (SandboxExecution.cleanup_status == 'unconfirmed')))
        ambiguous = await session.scalar(select(func.count()).select_from(SandboxOwnership).where(
            SandboxOwnership.state.in_(['UNKNOWN', 'CREATE_COMMITTED', 'CLEANUP_INTENT'])))
        unbound_intent = await session.scalar(select(func.count()).select_from(SandboxExecution).outerjoin(
            SandboxOwnership, SandboxOwnership.execution_id == SandboxExecution.id).where(
            SandboxExecution.launch_claimed_at.is_not(None), SandboxExecution.container_id.is_(None),
            SandboxOwnership.execution_id.is_(None)))
        require(not unknown and not ambiguous and not unbound_intent, 'SANDBOX_HISTORY_UNRESOLVED')
        grant.status = 'USED'
        row.state, row.epoch, row.updated_at = 'OPEN', row.epoch+1, now()
        audit(session, row, 'THAW_CONSUMED', operator.identity, grant.id)
        return {'state': row.state, 'epoch': row.epoch}
