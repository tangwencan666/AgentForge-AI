"""P4 tenant-scoped tool ledger and immutable declarative Skill versions."""
from datetime import date, datetime
from uuid import UUID
from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class ToolPermission(Base):
    __tablename__ = "tool_permissions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), primary_key=True)
    resource: Mapped[str] = mapped_column(String(64), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
    generation: Mapped[int] = mapped_column(Integer, default=1)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_tool_call_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    idempotency_key: Mapped[UUID]
    tool: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict] = mapped_column(JSONB)
    request_hash: Mapped[str] = mapped_column(String(64))
    operation_hash: Mapped[str] = mapped_column(String(64))
    permission_generation: Mapped[int] = mapped_column(Integer)
    skill: Mapped[dict | None] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(32))
    requester: Mapped[str] = mapped_column(String(32), default="local-admin")
    status: Mapped[str] = mapped_column(String(32), index=True)
    approval_id: Mapped[UUID | None]
    result: Mapped[dict | None] = mapped_column(JSONB)
    remote_result: Mapped[dict | None] = mapped_column(JSONB)
    task_context: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolDailyUsage(Base):
    __tablename__ = "tool_daily_usage"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)


class CapabilityApproval(Base):
    __tablename__ = "capability_approvals"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    target_id: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(32))
    operation_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32))
    requester: Mapped[str] = mapped_column(String(32), default="local-admin")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapabilityAudit(Base):
    __tablename__ = "capability_audit"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    target_id: Mapped[str] = mapped_column(String(160))
    event: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    version: Mapped[str] = mapped_column(String(24), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    approval_id: Mapped[UUID | None]
    installed_hash: Mapped[str | None] = mapped_column(String(64))
    enabled_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagedNote(Base):
    __tablename__ = "managed_notes"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
