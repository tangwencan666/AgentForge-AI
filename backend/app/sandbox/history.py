"""Derived quarantine from durable execution facts. Never changes an outcome.

There is deliberately no release flag or list supplied by clients. Legacy launch
intents have no new ownership authority even when their stored status is failed.
Read-only review does not authorize replay, cleanup, settlement or thaw.
"""
from sqlalchemy import select
from app.core.errors import AppError
from app.domain.sandbox import SandboxExecution
from app.domain.sandbox_ownership import SandboxOwnership


def replay_hold(execution, ownership=None):
    if execution is None:
        return 'EXECUTION_UNVERIFIED'
    if execution.status == 'needs_reconciliation' or execution.cleanup_status == 'unconfirmed':
        return 'OUTCOME_UNKNOWN'
    if execution.launch_claimed_at is not None and ownership is None:
        return 'LEGACY_LAUNCH_UNOWNED'
    if ownership is not None:
        if ownership.execution_id != execution.id or ownership.task_id != execution.task_id:
            return 'OWNERSHIP_MISMATCH'
        if ownership.state in {'UNKNOWN', 'CREATE_COMMITTED', 'CLEANUP_INTENT'}:
            return 'EXTERNAL_BOUNDARY_UNRESOLVED'
    return None


async def execution_replay_hold(session, execution):
    ownership = await session.get(SandboxOwnership, execution.id) if execution is not None else None
    return replay_hold(execution, ownership)


async def task_replay_allowed(session, task):
    if task.options.get('workflow') != 'sandbox':
        return True
    row = (await session.scalars(select(SandboxExecution).where(
        SandboxExecution.task_id == task.id))).one_or_none()
    return await execution_replay_hold(session, row) is None


async def require_replayable(session, execution):
    if await execution_replay_hold(session, execution):
        raise AppError('SANDBOX_HISTORY_QUARANTINED', 'Historical execution is held; replay is forbidden', 409)


def review_metadata(execution, ownership=None):
    """Bounded evidence fields only, no code/output/credentials or new authority."""
    hold = replay_hold(execution, ownership)
    if execution is None:
        return {'disposition': 'UNVERIFIED', 'replay_allowed': False}
    return {'execution_id': str(execution.id), 'task_id': str(execution.task_id),
        'stored_status': execution.status, 'stored_cleanup_status': execution.cleanup_status,
        'container_id': execution.container_id, 'disposition': 'QUARANTINED_NO_REPLAY' if hold else 'NO_HOLD_DERIVED',
        'hold_reason': hold, 'replay_allowed': hold is None,
        'missing_evidence': ['TRUSTED_RUNNER_IDENTITY', 'CREATE_AND_INJECTION_BOUNDARY', 'EXIT_AND_SETTLEMENT'] if hold else [],
        'outcome_resolution_authorized': False, 'cleanup_authorized': False}
