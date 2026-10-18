"""Fixed Coder test permits. Short transactions bracket, never span, model HTTP."""
import asyncio
from datetime import timedelta
from decimal import Decimal
import secrets
from time import monotonic
from uuid import UUID, uuid4
from sqlalchemy import select, func, text
from sqlalchemy.exc import SQLAlchemyError
from app.core.errors import AppError
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation, Outbox
from app.domain.permits import ExecutionPermit, TrustedModelWorker, PermitAudit
from app.providers.base import ProviderFailure
from app.providers.deepseek import DeepSeek
from app.providers.router import ModelRouter, price_for, price_matches_snapshot
from app.schemas.models import ModelConfig
from app.services.context import content_hash, redact
from app.services.tasks import TERMINAL, event, check_lease
from app.services.permit_authority import (WorkerIdentity, mint_worker_identity, require_issuer,
    mint_dispatch_lease, require_dispatch)

PROMPT = '请只回答 connected'
BUDGET = Decimal('.005')
ACTIVE = {'ISSUED', 'CLAIMED', 'DISPATCH_COMMITTED'}


def policy_hash(settings):
    return content_hash({name: getattr(settings, name) for name in
        ('single_use_permits_enabled', 'real_worker_mode', 'real_calls_enabled', 'real_max_retries',
         'real_test_max_calls', 'real_daily_token_limit', 'allowed_model_hosts', 'model_credential_hosts',
         'model_prices', 'permit_ttl_seconds')} | {
        'daily_usd': str(settings.real_daily_budget_usd), 'test_usd': str(settings.real_test_budget_usd),
        'env_only': settings.model_credentials_env_only})


def request_body(config):
    return DeepSeek().request_body(config, [{'role': 'user', 'content': PROMPT}])


def operation_id(permit):
    return 'permit:' + str(permit.execution_id)


async def clock(session):
    return await session.scalar(select(func.clock_timestamp()))


async def audit(session, permit, previous, name, details=None):
    last = await session.scalar(select(PermitAudit).where(PermitAudit.permit_id == permit.permit_id)
        .order_by(PermitAudit.sequence.desc()).limit(1))
    sequence, previous_hash = (last.sequence + 1, last.event_hash) if last else (1, '0' * 64)
    data = {'permit_id': str(permit.permit_id), 'execution_id': str(permit.execution_id), 'sequence': sequence,
        'previous_status': previous, 'status': permit.status, 'event': name, 'details': details or {}, 'previous_hash': previous_hash}
    session.add(PermitAudit(audit_id=uuid4(), permit_id=permit.permit_id, execution_id=permit.execution_id,
        sequence=sequence, previous_status=previous, status=permit.status, event=name, details=details or {},
        previous_hash=previous_hash, event_hash=content_hash(data), created_at=await clock(session)))
    await session.flush()


class PermitService:
    def __init__(self, connections, settings):
        self.connections, self.settings = connections, settings

    async def require_schema(self):
        try:
            async with self.connections.engine.connect() as connection:
                revision = await connection.scalar(text('SELECT version_num FROM alembic_version'))
                if revision not in {'0008_execution_permits','0009_sandbox_ownership','0010_sandbox_maintenance'}:
                    raise AppError('PERMIT_MIGRATION_REQUIRED', 'Reviewed permit migration must be deployed first', 503)
                await connection.execute(text('SELECT permit_id,status,claim_count,dispatch_attempts,reserved_cost FROM execution_permits LIMIT 0'))
                await connection.execute(text('SELECT identity,proof_hash,policy_hash FROM trusted_model_workers LIMIT 0'))
                await connection.execute(text('SELECT sequence,previous_hash,event_hash FROM permit_audit LIMIT 0'))
                valid = await connection.scalar(text("""SELECT
                    (SELECT count(*)=5 FROM pg_constraint WHERE conrelid='execution_permits'::regclass
                     AND contype='c' AND convalidated AND conname IN
                     ('ck_permit_credential','ck_permit_profile','ck_permit_status','ck_permit_counts','ck_permit_limits'))
                    AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='execution_permits'::regclass
                     AND tgname='execution_permit_guard' AND NOT tgisinternal AND tgenabled IN ('O','A'))
                    AND (SELECT count(*)=2 FROM pg_index WHERE indexrelid IN
                     (to_regclass('uq_permit_active_tenant'),to_regclass('uq_permit_audit_sequence'))
                     AND indisunique AND indisvalid AND indisready)"""))
                if not valid:
                    raise AppError('PERMIT_MIGRATION_REQUIRED', 'Reviewed permit safety structure is required', 503)
        except SQLAlchemyError:
            raise AppError('PERMIT_MIGRATION_REQUIRED', 'Reviewed permit schema unavailable', 503) from None

    def _policy(self):
        s = self.settings
        if not s.single_use_permits_enabled or not s.real_calls_enabled:
            raise AppError('PERMIT_POLICY_DISABLED', 'Fresh single-use permit policy must be explicitly enabled', 409)
        if (s.real_worker_mode != 'permit_only' or s.real_max_retries != 0 or s.real_test_max_calls != 1
                or s.real_daily_token_limit != 8256 or s.real_daily_budget_usd != BUDGET
                or s.real_test_budget_usd != BUDGET or not s.model_credentials_env_only
                or s.model_hosts != frozenset({'api.deepseek.com'})
                or s.model_credential_hosts.get('AGENTFORGE_MODEL_CODER_KEY') != ['api.deepseek.com']):
            raise AppError('PERMIT_POLICY_INVALID', 'Exact single-use limits and audience are required', 409)

    async def register_worker(self, owner):
        self._policy()
        identity = mint_worker_identity(uuid4(), owner)
        import os
        async with self.connections.sessions() as session, session.begin():
            stamp = await clock(session)
            session.add(TrustedModelWorker(identity=identity.identity, tenant_id=UUID(self.settings.tenant_id),
                lease_owner=owner, proof_hash=identity.proof_hash(), policy_hash=policy_hash(self.settings), mode='permit_only',
                credential_present='AGENTFORGE_MODEL_CODER_KEY' in os.environ,
                revoked=False, created_at=stamp, expires_at=stamp + timedelta(seconds=20)))
        return identity

    async def _worker(self, session, identity, stamp):
        if type(identity) is not WorkerIdentity:
            raise AppError('PERMIT_WORKER_FORBIDDEN', 'Public worker identifiers confer no authority', 403)
        row = await session.get(TrustedModelWorker, identity.identity)
        if (not row or row.revoked or row.expires_at <= stamp or row.lease_owner != identity.owner
                or str(row.tenant_id) != self.settings.tenant_id or row.mode != 'permit_only'
                or row.policy_hash != policy_hash(self.settings) or not row.credential_present
                or not secrets.compare_digest(row.proof_hash, identity.proof_hash())):
            raise AppError('PERMIT_WORKER_FORBIDDEN', 'Trusted process identity is unavailable or changed', 403)
        return row

    async def heartbeat(self, identity, *, revoke=False):
        if identity is None: return
        async with self.connections.sessions() as session, session.begin():
            row = await self._worker(session, identity, await clock(session))
            row.revoked = revoke
            if not revoke: row.expires_at = await clock(session) + timedelta(seconds=20)

    async def _profile(self, session, permit=None):
        rows = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == UUID(self.settings.tenant_id)))).all()
        if len(rows) != 4 or any(row.enabled for row in rows if row.role != 'coder'):
            raise AppError('PERMIT_SLOT_INVALID', 'Only the fixed Coder slot may be enabled', 409)
        coder = next(row for row in rows if row.role == 'coder')
        config = {name: getattr(coder, name) for name in ModelConfig.model_fields}
        if (not coder.enabled or coder.provider != 'openai_compatible' or coder.model != 'deepseek-flash'
                or coder.base_url != 'https://api.deepseek.com' or coder.max_tokens != 64 or coder.timeout != 30
                or coder.thinking_mode != 'disabled' or coder.credential_reference != 'env:AGENTFORGE_MODEL_CODER_KEY'):
            raise AppError('PERMIT_SLOT_INVALID', 'Slot does not match the reviewed fixed test', 409)
        ModelConfig.model_validate(config)
        price = price_for(config, self.settings)
        if (price.input_upper_bound != 8192 or price.token_parameter != 'max_tokens'
                or price.cost(8192, 64) > BUDGET or price.output_upper_bound < 64):
            raise AppError('PERMIT_PRICE_INVALID', 'Registered conservative reservation does not fit the permit', 409)
        if permit and (coder.version != permit.slot_version or content_hash(request_body(config)) != permit.request_fingerprint
                or permit.policy_hash != policy_hash(self.settings)):
            raise AppError('PERMIT_CONFIGURATION_CHANGED', 'Permit configuration is stale', 409)
        return config | {'config_version': coder.version, 'price': price.model_dump(mode='json')}, price

    async def issue(self, authority):
        require_issuer(authority, self.settings)
        self._policy()
        await self.require_schema()
        async with self.connections.sessions() as session, session.begin():
            await session.execute(text('SELECT pg_advisory_xact_lock(472902)'))
            stamp = await clock(session)
            if await session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.status.not_in(TERMINAL))):
                raise AppError('PERMIT_TASKS_OUTSTANDING', 'All other pending work must be stopped', 409)
            workers = (await session.scalars(select(TrustedModelWorker).where(TrustedModelWorker.tenant_id == UUID(self.settings.tenant_id),
                TrustedModelWorker.mode == 'permit_only', TrustedModelWorker.revoked.is_(False), TrustedModelWorker.expires_at > stamp,
                TrustedModelWorker.credential_present.is_(True), TrustedModelWorker.policy_hash == policy_hash(self.settings)))).all()
            if len(workers) != 1:
                raise AppError('PERMIT_WORKER_UNAVAILABLE', 'Exactly one trusted dedicated worker must be available', 409)
            if await session.scalar(select(func.count()).select_from(ExecutionPermit).where(
                    ExecutionPermit.tenant_id == UUID(self.settings.tenant_id), ExecutionPermit.status.in_(ACTIVE))):
                raise AppError('PERMIT_ACTIVE', 'An active permit already exists', 409)
            from app.services.orchestration.real_runtime import real_usage
            quota = await real_usage(session, UUID(self.settings.tenant_id), stamp.date())
            if quota.test_calls or quota.cost_used or quota.cost_reserved or quota.tokens_used or quota.tokens_reserved:
                raise AppError('PERMIT_QUOTA_UNAVAILABLE', 'Prior usage or unknown reservations cannot be reset', 409)
            config, price = await self._profile(session)
            permit_id, task_id, execution_id = uuid4(), uuid4(), uuid4()
            expiration = stamp + timedelta(seconds=self.settings.permit_ttl_seconds)
            fingerprint = content_hash(request_body(config))
            task = AgentTask(id=task_id, tenant_id=UUID(self.settings.tenant_id), idempotency_key=uuid4(), request_hash=fingerprint,
                goal=PROMPT, options={'workflow': 'permit_test', 'model_test': True, 'permit_id': str(permit_id), 'execution_id': str(execution_id)},
                status='queued', is_mock=False, model_snapshot={'coder': config}, deadline=expiration,
                token_limit=8256, call_limit=1, iteration_limit=1, budget_limit=BUDGET, created_at=stamp, updated_at=stamp,
                event_seq=0, version=1, fence=0, attempts=0, iterations=0, tokens_used=0, tokens_reserved=0,
                calls_used=0, cost_used=Decimal(0), cost_reserved=Decimal(0))
            session.add(task)
            await session.flush()
            permit = ExecutionPermit(permit_id=permit_id, tenant_id=task.tenant_id, task_id=task_id, execution_id=execution_id,
                role='coder', provider='openai_compatible', model='deepseek-flash', slot_version=config['config_version'],
                endpoint='api.deepseek.com', credential_reference=config['credential_reference'], request_fingerprint=fingerprint,
                authorized_worker_identity=workers[0].identity, policy_hash=policy_hash(self.settings), max_attempts=1,
                max_output_tokens=64, input_upper_bound=8192, max_budget_usd=BUDGET, expiration=expiration,
                status='ISSUED', claim_count=0, dispatch_attempts=0, issued_at=stamp, reserved_tokens=0,
                reserved_cost=Decimal(0), usage_status='not_dispatched')
            session.add(permit)
            await audit(session, permit, None, 'issued', {'actor': 'independent_issuer', 'slot_version': config['config_version']})
            event(session, task, 'permit_issued', {'permit_id': str(permit_id), 'execution_id': str(execution_id)})
            session.add(Outbox(id=uuid4(), task_id=task_id))
        return await self.get(permit_id)

    async def _locked(self, session, permit_id):
        p = await session.scalar(select(ExecutionPermit).where(ExecutionPermit.permit_id == permit_id,
            ExecutionPermit.tenant_id == UUID(self.settings.tenant_id)).with_for_update())
        if not p: raise AppError('PERMIT_NOT_FOUND', 'Permit not found', 404)
        task = await session.scalar(select(AgentTask).where(AgentTask.id == p.task_id).with_for_update())
        return p, task

    async def claim(self, permit_id, identity, fence):
        self._policy()
        async with self.connections.sessions() as session, session.begin():
            p, task = await self._locked(session, permit_id)
            stamp = await clock(session)
            await self._worker(session, identity, stamp)
            if p.authorized_worker_identity != identity.identity:
                raise AppError('PERMIT_WORKER_FORBIDDEN', 'Permit is bound to another trusted worker', 403)
            if p.status != 'ISSUED' or p.claim_count:
                raise AppError('PERMIT_CONSUMED', 'Permit cannot be claimed again', 409)
            if p.expiration <= stamp: raise AppError('PERMIT_EXPIRED', 'Permit expired', 409)
            check_lease(task, identity.owner, fence)
            config, price = await self._profile(session, p)
            if (task.options != {'workflow': 'permit_test', 'model_test': True, 'permit_id': str(p.permit_id), 'execution_id': str(p.execution_id)}
                    or task.goal != PROMPT or set(task.model_snapshot) != {'coder'} or task.call_limit != 1
                    or task.token_limit != 8256 or task.budget_limit != BUDGET or task.deadline != p.expiration
                    or not price_matches_snapshot(price, task.model_snapshot['coder']['price'])
                    or task.model_snapshot['coder'] != config):
                raise AppError('PERMIT_REQUEST_CHANGED', 'Stored request is not the authorized request', 409)
            from app.services.orchestration.real_runtime import real_usage
            quota = await real_usage(session, task.tenant_id, stamp.date())
            cost = price.cost(8192, 64)
            if (task.calls_used or quota.test_calls >= 1 or task.tokens_reserved + task.tokens_used + 8256 > task.token_limit
                    or quota.tokens_used + quota.tokens_reserved + 8256 > self.settings.real_daily_token_limit
                    or quota.cost_used + quota.cost_reserved + cost > BUDGET
                    or quota.test_cost_used + quota.test_cost_reserved + cost > BUDGET):
                raise AppError('PERMIT_BUDGET_BLOCKED', 'Atomic single-use quota is exhausted', 409)
            p.status, p.claim_count, p.claimed_at = 'CLAIMED', 1, stamp
            p.reservation_day, p.reserved_tokens, p.reserved_cost, p.usage_status = stamp.date(), 8256, cost, 'pending'
            task.calls_used, task.tokens_reserved, task.cost_reserved = 1, 8256, cost
            quota.test_calls += 1
            quota.tokens_reserved += 8256
            quota.cost_reserved += cost
            quota.test_cost_reserved += cost
            session.add(ModelOperation(task_id=task.id, operation_id=operation_id(p), role='coder', provider=p.provider, model=p.model,
                is_mock=False, state='reserved', input_tokens=0, output_tokens=0, reserved_tokens=8256, reserved_cost=cost, cost=0,
                price_version=price.version, request_hash=p.request_fingerprint, fence=fence, usage_status='pending', reservation_day=stamp.date()))
            await audit(session, p, 'ISSUED', 'claimed_and_budget_reserved', {'reserved_tokens': 8256, 'reserved_cost_usd': str(cost)})
            event(session, task, 'node_started', {'role': 'coder', 'permit_id': str(p.permit_id), 'execution_id': str(p.execution_id),
                'retry_policy': 'none', 'call_limit': 1, 'output_limit': 64, 'token_limit': 8256, 'budget_limit_usd': str(BUDGET)})
        return mint_dispatch_lease(self, permit_id, identity, fence)

    async def commit_dispatch(self, lease, config, body):
        require_dispatch(lease)
        self._policy()
        async with self.connections.sessions() as session, session.begin():
            p, task = await self._locked(session, lease.permit_id)
            stamp = await clock(session)
            await self._worker(session, lease.identity, stamp)
            if p.authorized_worker_identity != lease.identity.identity or p.status != 'CLAIMED' or p.dispatch_attempts:
                raise AppError('PERMIT_CONSUMED', 'Dispatch intent is single-use', 409)
            if p.expiration <= stamp: raise AppError('PERMIT_EXPIRED', 'Permit expired before dispatch', 409)
            check_lease(task, lease.identity.owner, lease.fence)
            reviewed, _ = await self._profile(session, p)
            if (content_hash(body) != p.request_fingerprint or body != request_body(reviewed)
                    or any(config.get(name) != reviewed[name] for name in ModelConfig.model_fields if name != 'timeout')
                    or config.get('token_parameter') != 'max_tokens' or not 0 < config['timeout'] <= 30):
                raise AppError('PERMIT_REQUEST_CHANGED', 'Wire request differs from the authorized fingerprint', 409)
            p.status, p.dispatch_attempts, p.dispatch_committed_at = 'DISPATCH_COMMITTED', 1, stamp
            row = await session.get(ModelOperation, (task.id, operation_id(p)))
            row.state = 'pending'
            await audit(session, p, 'CLAIMED', 'dispatch_intent_committed', {'attempt_upper_bound': 1})
            event(session, task, 'dispatch_committed', {'permit_id': str(p.permit_id), 'execution_id': str(p.execution_id),
                'attempt_upper_bound': 1, 'wire_outcome': 'possibly_sent'})

    async def _settle(self, session, p, task, reply=None, failure=None, *, abort=False):
        from app.services.orchestration.real_runtime import real_usage
        previous = p.status
        row = await session.get(ModelOperation, (task.id, operation_id(p)))
        quota = await real_usage(session, task.tenant_id, p.reservation_day)
        known = bool(reply and reply.input_tokens is not None)
        if abort or known:
            task.tokens_reserved -= p.reserved_tokens
            task.cost_reserved -= p.reserved_cost
            quota.tokens_reserved -= p.reserved_tokens
            quota.cost_reserved -= p.reserved_cost
            quota.test_cost_reserved -= p.reserved_cost
        if known:
            price = price_for(task.model_snapshot['coder'], self.settings)
            p.settled_cost = price.cost(reply.input_tokens, reply.output_tokens)
            row.input_tokens, row.output_tokens, row.total_tokens, row.cost = reply.input_tokens, reply.output_tokens, reply.total_tokens, p.settled_cost
            task.tokens_used += reply.total_tokens
            task.cost_used += p.settled_cost
            quota.tokens_used += reply.total_tokens
            quota.cost_used += p.settled_cost
            quota.test_cost_used += p.settled_cost
            p.usage_status = row.usage_status = 'reported_estimate'
            if reply.total_tokens > p.reserved_tokens or p.settled_cost > p.reserved_cost:
                failure = ProviderFailure('MODEL_USAGE_EXCEEDS_BOUND')
        else:
            p.usage_status = row.usage_status = 'not_dispatched' if abort else 'unknown'
        if abort:
            p.status, row.state = 'ABORTED', 'failed'
            task.status = 'failed'
        elif reply:
            clean = redact(reply.text, self.settings)
            if clean.strip() != 'connected' and failure is None: failure = ProviderFailure('MODEL_ACCEPTANCE_MISMATCH')
            p.status, row.state = ('FAILED', 'failed') if failure else ('SUCCEEDED', 'completed')
            row.result = {'summary': clean, 'is_mock': False, 'role': 'coder', 'operation_id': operation_id(p)}
            task.result, task.status = row.result, 'failed' if failure else 'succeeded'
            p.http_status, p.sse_complete, p.usage_details = reply.http_status, reply.sse_complete, reply.usage_details
            row.first_token_ms, row.latency_ms = reply.first_token_ms, reply.latency_ms
            event(session, task, 'model_delta', {'role': 'coder', 'text': clean, 'source': 'completed_redacted_stream'})
        else:
            # A response status proves HTTP failure; transport/stream/cancellation outcomes remain UNKNOWN.
            definite = isinstance(failure, ProviderFailure) and failure.status is not None and failure.status != 200
            p.status, row.state, task.status = ('FAILED', 'failed', 'failed') if definite else ('UNKNOWN', 'pending', 'needs_reconciliation')
            p.http_status = getattr(failure, 'status', None)
        p.error_code = row.error_code = getattr(failure, 'code', None) or ('PERMIT_ABORTED' if abort else None)
        row.http_status = p.http_status
        p.finished_at = row.finished_at = await clock(session)
        task.error_code, task.owner, task.lease_until = p.error_code, None, None
        await audit(session, p, previous, 'settled' if reply else ('aborted_before_dispatch' if abort else 'outcome_retained'),
            {'usage_status': p.usage_status, 'http_status': p.http_status, 'sse_complete': p.sse_complete,
             'error_code': p.error_code, 'estimated_cost_usd': str(p.settled_cost) if known else None,
             'reservation_retained': not abort and not known})
        event(session, task, 'status', {'status': task.status, 'permit_status': p.status, 'usage_status': p.usage_status})

    async def execute(self, permit_id, identity, fence):
        lease = await self.claim(permit_id, identity, fence)
        reply, failure = None, None
        started = monotonic()
        try:
            async with self.connections.sessions() as session:
                p = await session.get(ExecutionPermit, permit_id)
                task = await session.get(AgentTask, p.task_id)
                config = task.model_snapshot['coder']
                remaining = max(.001, (p.expiration - await clock(session)).total_seconds())
            adapter, credential, price = ModelRouter(self.settings).resolve(config)
            async def delta(part):
                # Progress is live; raw fragments/reasoning are never persisted or broadcast.
                async with self.connections.sessions() as session, session.begin():
                    p, task = await self._locked(session, permit_id)
                    if p.status == 'DISPATCH_COMMITTED':
                        event(session, task, 'model_stream_progress', {'role': 'coder', 'characters': len(part)})
            async with asyncio.timeout(remaining):
                reply = await adapter.complete(config | {'timeout': min(30, remaining), 'token_parameter': price.token_parameter},
                    [{'role': 'user', 'content': PROMPT}], credential, delta, dispatch=lease)
        except (ProviderFailure, AppError, TimeoutError, asyncio.CancelledError) as exc:
            failure = exc if isinstance(exc, (ProviderFailure, AppError)) else ProviderFailure('MODEL_TIMEOUT' if isinstance(exc, TimeoutError) else 'MODEL_INTERRUPTED')
        except Exception:
            failure = ProviderFailure('MODEL_EXECUTION_UNKNOWN')
        async with self.connections.sessions() as session, session.begin():
            p, task = await self._locked(session, permit_id)
            if p.status not in {'CLAIMED', 'DISPATCH_COMMITTED'}: return await self.get(permit_id)
            await self._settle(session, p, task, reply, failure, abort=p.status == 'CLAIMED')
            row = await session.get(ModelOperation, (task.id, operation_id(p)))
            if row.latency_ms is None: row.latency_ms = int((monotonic() - started) * 1000)
        return await self.get(permit_id)

    async def recover(self):
        async with self.connections.sessions() as session, session.begin():
            rows = (await session.scalars(select(ExecutionPermit).where(ExecutionPermit.tenant_id == UUID(self.settings.tenant_id),
                ExecutionPermit.status.in_(ACTIVE)).with_for_update(skip_locked=True))).all()
            for p in rows:
                stamp = await clock(session)
                task = await session.scalar(select(AgentTask).where(AgentTask.id == p.task_id).with_for_update())
                worker = await session.get(TrustedModelWorker, p.authorized_worker_identity)
                dead = not worker or worker.revoked or worker.expires_at <= stamp
                if p.status == 'ISSUED':
                    if p.expiration <= stamp or dead:
                        p.status, p.finished_at = 'EXPIRED', stamp
                        task.status, task.error_code, task.owner, task.lease_until = 'timed_out', 'PERMIT_EXPIRED', None, None
                        await audit(session, p, 'ISSUED', 'expired_without_claim')
                    continue
                if (dead or p.expiration <= stamp or task.owner != worker.lease_owner or not task.lease_until
                        or task.lease_until <= stamp or task.status != 'running'):
                    await self._settle(session, p, task, failure=ProviderFailure('WORKER_OUTCOME_UNKNOWN'), abort=p.status == 'CLAIMED')

    async def revoke(self, permit_id, authority):
        require_issuer(authority, self.settings)
        await self.require_schema()
        async with self.connections.sessions() as session, session.begin():
            p, task = await self._locked(session, permit_id)
            if p.status == 'ISSUED':
                p.status, p.finished_at = 'REVOKED', await clock(session)
                task.status, task.owner, task.lease_until = 'cancelled', None, None
                await audit(session, p, 'ISSUED', 'revoked_by_independent_issuer')
            elif p.status == 'CLAIMED':
                await self._settle(session, p, task, failure=ProviderFailure('PERMIT_REVOKED'), abort=True)
            else:
                raise AppError('PERMIT_NOT_REVOCABLE', 'Committed or terminal permits cannot be reset', 409)
        return await self.get(permit_id)

    async def get(self, permit_id):
        await self.require_schema()
        async with self.connections.sessions() as session:
            p = await session.get(ExecutionPermit, permit_id)
            if not p or str(p.tenant_id) != self.settings.tenant_id: raise AppError('PERMIT_NOT_FOUND', 'Permit not found', 404)
            names = ('permit_id','task_id','execution_id','role','provider','model','slot_version','endpoint','credential_reference',
                'request_fingerprint','authorized_worker_identity','max_attempts','max_output_tokens','input_upper_bound','max_budget_usd',
                'expiration','status','claim_count','dispatch_attempts','reserved_tokens','reserved_cost','settled_cost','usage_status',
                'http_status','sse_complete','usage_details','error_code','issued_at','claimed_at',
                'dispatch_committed_at','finished_at','reservation_day','policy_hash')
            result = {name: getattr(p, name) for name in names}
            rows = (await session.scalars(select(PermitAudit).where(PermitAudit.permit_id == permit_id).order_by(PermitAudit.sequence))).all()
            result['audit'] = [{'sequence': r.sequence, 'event': r.event, 'previous_status': r.previous_status, 'status': r.status,
                'previous_hash': r.previous_hash, 'event_hash': r.event_hash, 'details': r.details, 'created_at': r.created_at} for r in rows]
            operation = await session.get(ModelOperation, (p.task_id, operation_id(p)))
            result['result'] = operation.result if operation else None
            result['usage'] = {'input_tokens': operation.input_tokens if operation and operation.total_tokens is not None else None,
                'output_tokens': operation.output_tokens if operation and operation.total_tokens is not None else None,
                'total_tokens': operation.total_tokens if operation else None,
                'latency_ms': operation.latency_ms if operation else None, 'first_token_ms': operation.first_token_ms if operation else None}
            return result
