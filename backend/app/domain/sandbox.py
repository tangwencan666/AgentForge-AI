"""Private bounded code is persisted separately from audit DTOs and graph state."""
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base

class SandboxExecution(Base):
    __tablename__ = "sandbox_executions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), unique=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    language: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64))
    operation_hash: Mapped[str] = mapped_column(String(64))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    resource_limits: Mapped[dict] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(32))
    approval_reference: Mapped[UUID] = mapped_column(ForeignKey("task_approvals.id"))
    requester: Mapped[str] = mapped_column(String(32), default="local-admin")
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval", index=True)
    container_name: Mapped[str | None] = mapped_column(String(80))
    container_id: Mapped[str | None] = mapped_column(String(64))
    image_id: Mapped[str | None] = mapped_column(String(80))
    launch_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runner_owner: Mapped[str | None] = mapped_column(String(64))
    runner_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_summary: Mapped[str] = mapped_column(Text, default="")
    stderr_summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    resource_usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    cleanup_status: Mapped[str] = mapped_column(String(32), default="not_created")
    budget_day: Mapped[date] = mapped_column(Date)
    reserved_cpu_seconds: Mapped[Decimal] = mapped_column(Numeric(12,3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SandboxDailyUsage(Base):
    __tablename__ = "sandbox_daily_usage"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    cpu_seconds_reserved: Mapped[Decimal] = mapped_column(Numeric(12,3), default=Decimal(0))
    cpu_seconds_used: Mapped[Decimal] = mapped_column(Numeric(12,3), default=Decimal(0))
