from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ModelSlot(Base):
    __tablename__ = "model_slots"
    __table_args__ = (
        CheckConstraint("role IN ('planner','coder','researcher','reviewer')", name="ck_model_role"),
        CheckConstraint("timeout BETWEEN 1 AND 300", name="ck_model_timeout"),
        CheckConstraint("max_tokens BETWEEN 1 AND 131072", name="ck_model_tokens"),
        CheckConstraint("temperature BETWEEN 0 AND 2", name="ck_model_temperature"),
        CheckConstraint("thinking_mode IN ('disabled','enabled')", name='ck_model_thinking'),
        CheckConstraint("reasoning_effort IN ('low','high','max')", name='ck_model_effort'),
    )
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(512))
    model: Mapped[str | None] = mapped_column(String(128))
    credential_reference: Mapped[str | None] = mapped_column(String(128))
    temperature: Mapped[float] = mapped_column(Float, default=0.2, server_default="0.2")
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, server_default="4096")
    timeout: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    thinking_mode: Mapped[str] = mapped_column(String(8), default='disabled', server_default='disabled')
    reasoning_effort: Mapped[str] = mapped_column(String(8), default='high', server_default='high')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
