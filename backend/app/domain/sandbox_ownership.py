"""Private control-plane records. None of these fields are public request input."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class SandboxRunnerIdentity(Base):
    __tablename__ = 'sandbox_runner_identities'
    runner_instance_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(index=True)
    runner_generation: Mapped[int] = mapped_column(BigInteger)
    sandbox_namespace: Mapped[UUID] = mapped_column(unique=True)
    daemon_id: Mapped[str] = mapped_column(String(128))
    proof_hash: Mapped[str] = mapped_column(String(64))
    compatibility_evidence_id: Mapped[UUID | None] = mapped_column()
    compatibility_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('runner_generation > 0', name='ck_runner_generation'),)


class SandboxOwnership(Base):
    __tablename__ = 'sandbox_ownership'
    execution_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_executions.id'), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey('agent_tasks.id'))
    ownership_protocol_version: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[UUID] = mapped_column()
    runner_instance_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_runner_identities.runner_instance_id'))
    runner_generation: Mapped[int] = mapped_column(BigInteger)
    sandbox_namespace: Mapped[UUID] = mapped_column()
    container_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    image_id: Mapped[str] = mapped_column(String(80))
    worker_owner: Mapped[str] = mapped_column(String(64))
    worker_fence: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24))
    __table_args__ = (
        CheckConstraint('ownership_protocol_version = 1 AND runner_generation > 0', name='ck_ownership_protocol'),
        CheckConstraint("state IN ('INTENT','CREATE_COMMITTED','CREATED','CLEANUP_INTENT','REMOVED','UNKNOWN')", name='ck_ownership_state'),
    )


class SandboxOwnershipAudit(Base):
    __tablename__ = 'sandbox_ownership_audit'
    id: Mapped[UUID] = mapped_column(primary_key=True)
    runner_instance_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_runner_identities.runner_instance_id'))
    runner_generation: Mapped[int] = mapped_column(BigInteger)
    execution_id: Mapped[UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(32))
    resource: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
