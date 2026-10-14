"""P2 persistent state. No credentials or raw tool payloads are stored here."""
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_task_idempotency"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB)
    model_snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fence: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    token_limit: Mapped[int] = mapped_column(Integer)
    call_limit: Mapped[int] = mapped_column(Integer)
    iteration_limit: Mapped[int] = mapped_column(Integer)
    budget_limit: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_used: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    cost_reserved: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))


class TaskEvent(Base):
    __tablename__ = "task_events"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Outbox(Base):
    __tablename__ = "task_outbox"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskApproval(Base):
    __tablename__ = "task_approvals"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), unique=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    operation_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32), default="p2-plan-v1")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelOperation(Base):
    __tablename__ = "model_operations"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    model: Mapped[str] = mapped_column(String(64))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(24), default="reserved")
    input_tokens: Mapped[int] = mapped_column(Integer)
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    cost: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    price_version: Mapped[str] = mapped_column(String(32), default="mock-usd-v1")
    request_hash: Mapped[str] = mapped_column(String(64))
    fence: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    reservation_day: Mapped[date] = mapped_column(Date, server_default=func.current_date())


class TenantUsage(Base):
    __tablename__ = "tenant_mock_usage"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    cost_used: Mapped[Decimal] = mapped_column(Numeric(16,8), default=Decimal(0))
    cost_reserved: Mapped[Decimal] = mapped_column(Numeric(16,8), default=Decimal(0))


class GraphCheckpoint(Base):
    __tablename__ = "graph_checkpoints"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(512), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(80))
    data_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    meta_type: Mapped[str] = mapped_column(String(32))
    meta: Mapped[bytes] = mapped_column(LargeBinary)


class GraphWrite(Base):
    __tablename__ = "graph_writes"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(512), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    write_task_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
