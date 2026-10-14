"""P2 task state, events, outbox, approvals, usage and graph checkpoints."""
from alembic import op
from app.domain.entities import Base
import app.domain.tasks  # register P2 metadata

revision = "0002_workflows"
down_revision = "0001_model_slots"
branch_labels = None
depends_on = None
TABLES = ["agent_tasks", "task_events", "task_outbox", "task_approvals", "model_operations", "graph_checkpoints", "graph_writes"]


def upgrade():
    # Frozen column declarations in this revision; no create_all/runtime table creation.
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    op.create_table("agent_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False), sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("model_snapshot", postgresql.JSONB(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False), sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("owner", sa.String(64)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in ["fence","version","event_seq","attempts","iterations","token_limit","call_limit","iteration_limit","tokens_used","tokens_reserved","calls_used"]],
        *[sa.Column(name, sa.Numeric(16,8), nullable=False) for name in ["budget_limit","cost_used","cost_reserved"]],
        sa.Column("plan_hash", sa.String(64)), sa.Column("result", postgresql.JSONB()), sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_task_idempotency"))
    for name in ["tenant_id", "status", "deadline"]:
        op.create_index("ix_agent_tasks_" + name, "agent_tasks", [name])
    op.create_table("task_events", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True), sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("task_outbox", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_task_outbox_task_id", "task_outbox", ["task_id"])
    op.create_table("task_approvals", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("decided_by", sa.String(64)), sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.create_index("ix_task_approvals_tenant_id", "task_approvals", ["tenant_id"])
    op.create_table("model_operations", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("operation_id", sa.String(80), primary_key=True), sa.Column("role", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False), sa.Column("model", sa.String(64), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False), sa.Column("state", sa.String(24), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in ["input_tokens","reserved_tokens","output_tokens","fence"]],
        *[sa.Column(name, sa.Numeric(16,8), nullable=False) for name in ["reserved_cost","cost"]],
        sa.Column("price_version", sa.String(32), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB()), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("latency_ms", sa.Integer()))
    op.create_table("graph_checkpoints", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("namespace", sa.String(512), primary_key=True), sa.Column("checkpoint_id", sa.String(80), primary_key=True),
        sa.Column("parent_id", sa.String(80)), sa.Column("data_type", sa.String(32), nullable=False), sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("meta_type", sa.String(32), nullable=False), sa.Column("meta", sa.LargeBinary(), nullable=False))
    op.create_table("graph_writes", sa.Column("task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("namespace", sa.String(512), primary_key=True), sa.Column("checkpoint_id", sa.String(80), primary_key=True),
        sa.Column("write_task_id", sa.String(80), primary_key=True), sa.Column("idx", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(128), nullable=False), sa.Column("data_type", sa.String(32), nullable=False), sa.Column("data", sa.LargeBinary(), nullable=False))


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
