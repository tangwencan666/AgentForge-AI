"""Single-use model dispatch and trusted process registrations; no model keys."""
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import String, Integer, Numeric, DateTime, Date, Boolean, ForeignKey, CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class TrustedModelWorker(Base):
    __tablename__ = 'trusted_model_workers'
    identity: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    lease_owner: Mapped[str] = mapped_column(String(64), unique=True)
    proof_hash: Mapped[str] = mapped_column(String(64))
    policy_hash: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    credential_present: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class ExecutionPermit(Base):
    __tablename__ = 'execution_permits'
    __table_args__ = (
        CheckConstraint("role='coder' AND provider='openai_compatible' AND model='deepseek-flash' AND endpoint='api.deepseek.com'", name='ck_permit_profile'),
        CheckConstraint("credential_reference='env:AGENTFORGE_MODEL_CODER_KEY'", name='ck_permit_credential'),
        CheckConstraint('max_attempts=1 AND max_output_tokens=64 AND input_upper_bound=8192 AND max_budget_usd=0.005', name='ck_permit_limits'),
        CheckConstraint('claim_count BETWEEN 0 AND 1 AND dispatch_attempts BETWEEN 0 AND claim_count', name='ck_permit_counts'),
        CheckConstraint("status IN ('ISSUED','CLAIMED','DISPATCH_COMMITTED','SUCCEEDED','FAILED','UNKNOWN','ABORTED','EXPIRED','REVOKED')", name='ck_permit_status'),
        Index('uq_permit_active_tenant', 'tenant_id', unique=True, postgresql_where=text("status IN ('ISSUED','CLAIMED','DISPATCH_COMMITTED')")),
    )
    permit_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey('agent_tasks.id'), unique=True)
    execution_id: Mapped[UUID] = mapped_column(unique=True)
    role: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    slot_version: Mapped[int] = mapped_column(Integer)
    endpoint: Mapped[str] = mapped_column(String(64))
    credential_reference: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    authorized_worker_identity: Mapped[UUID] = mapped_column(ForeignKey('trusted_model_workers.identity'))
    policy_hash: Mapped[str] = mapped_column(String(64))
    max_attempts: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    input_upper_bound: Mapped[int] = mapped_column(Integer)
    max_budget_usd: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    expiration: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), index=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reservation_day: Mapped[date | None] = mapped_column(Date)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    settled_cost: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    usage_status: Mapped[str] = mapped_column(String(24), default='not_dispatched')
    http_status: Mapped[int | None] = mapped_column(Integer)
    sse_complete: Mapped[bool | None] = mapped_column(Boolean)
    usage_details: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))


class PermitAudit(Base):
    __tablename__ = 'permit_audit'
    audit_id: Mapped[UUID] = mapped_column(primary_key=True)
    permit_id: Mapped[UUID] = mapped_column(ForeignKey('execution_permits.permit_id'), index=True)
    execution_id: Mapped[UUID] = mapped_column(index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    previous_status: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    event: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (Index('uq_permit_audit_sequence', 'permit_id', 'sequence', unique=True),)
