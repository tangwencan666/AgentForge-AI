from datetime import date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class RealDailyUsage(Base):
    __tablename__ = 'tenant_real_usage'
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    cost_used: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    cost_reserved: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    test_cost_used: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    test_cost_reserved: Mapped[Decimal] = mapped_column(Numeric(16, 8), default=Decimal(0))
    test_calls: Mapped[int] = mapped_column(Integer, default=0)


class AgentToolOperation(Base):
    __tablename__ = 'agent_tool_operations'
    task_id: Mapped[UUID] = mapped_column(ForeignKey('agent_tasks.id', ondelete='CASCADE'), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    proposal: Mapped[dict] = mapped_column(JSONB)
    call_id: Mapped[UUID | None]
    sandbox_execution_id: Mapped[UUID | None]
    owner: Mapped[str | None] = mapped_column(String(64))
    fence: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSONB)
    permission_generation: Mapped[int | None] = mapped_column(Integer)
