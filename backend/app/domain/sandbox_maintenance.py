"""Private database-wide Sandbox admission control; never a model Permit."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.domain.entities import Base


class SandboxMaintenance(Base):
    __tablename__ = 'sandbox_maintenance'
    __table_args__ = (CheckConstraint("id=1 AND epoch>0 AND state IN ('FROZEN','DRAINING','OPEN')", name='ck_maintenance_state'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_id: Mapped[UUID]
    daemon_id: Mapped[str] = mapped_column(String(128))
    epoch: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SandboxMaintenanceAuthority(Base):
    __tablename__ = 'sandbox_maintenance_authorities'
    __table_args__ = (CheckConstraint("kind IN ('operator','approver')", name='ck_maintenance_authority'),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    deployment_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    proof_hash: Mapped[str] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean)


class SandboxThawGrant(Base):
    __tablename__ = 'sandbox_thaw_grants'
    __table_args__ = (CheckConstraint("status IN ('ISSUED','USED')", name='ck_thaw_status'),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    deployment_id: Mapped[UUID]
    freeze_epoch: Mapped[int] = mapped_column(BigInteger)
    operator_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_maintenance_authorities.id'))
    approver_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_maintenance_authorities.id'))
    runner_instance_id: Mapped[UUID] = mapped_column(ForeignKey('sandbox_runner_identities.runner_instance_id'))
    runner_generation: Mapped[int] = mapped_column(BigInteger)
    daemon_id: Mapped[str] = mapped_column(String(128))
    evidence_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))


class SandboxMaintenanceAudit(Base):
    __tablename__ = 'sandbox_maintenance_audit'
    id: Mapped[UUID] = mapped_column(primary_key=True)
    deployment_id: Mapped[UUID]
    epoch: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID | None]
    grant_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
