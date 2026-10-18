"""Add isolated Runner identities and immutable execution ownership; adopt nothing."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009_sandbox_ownership'
down_revision = '0008_execution_permits'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sandbox_runner_identities',
        sa.Column('runner_instance_id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('runner_generation', sa.BigInteger(), nullable=False),
        sa.Column('sandbox_namespace', sa.Uuid(), nullable=False, unique=True),
        sa.Column('daemon_id', sa.String(128), nullable=False),
        sa.Column('proof_hash', sa.String(64), nullable=False),
        sa.Column('compatibility_evidence_id', sa.Uuid()),
        sa.Column('compatibility_cleared_at', sa.DateTime(timezone=True)),
        sa.Column('process_owner', sa.String(64)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('retired', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('runner_generation > 0', name='ck_runner_generation'))
    op.create_index('ix_sandbox_runner_identities_project_id', 'sandbox_runner_identities', ['project_id'])
    op.create_table('sandbox_ownership',
        sa.Column('execution_id', sa.Uuid(), sa.ForeignKey('sandbox_executions.id'), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('agent_tasks.id'), nullable=False),
        sa.Column('ownership_protocol_version', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('runner_instance_id', sa.Uuid(), sa.ForeignKey('sandbox_runner_identities.runner_instance_id'), nullable=False),
        sa.Column('runner_generation', sa.BigInteger(), nullable=False),
        sa.Column('sandbox_namespace', sa.Uuid(), nullable=False),
        sa.Column('container_id', sa.String(64), unique=True),
        sa.Column('policy_version', sa.String(32), nullable=False),
        sa.Column('image_id', sa.String(80), nullable=False),
        sa.Column('worker_owner', sa.String(64), nullable=False),
        sa.Column('worker_fence', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.CheckConstraint('ownership_protocol_version = 1 AND runner_generation > 0', name='ck_ownership_protocol'),
        sa.CheckConstraint("state IN ('INTENT','CREATE_COMMITTED','CREATED','CLEANUP_INTENT','REMOVED','UNKNOWN')", name='ck_ownership_state'))
    op.create_table('sandbox_ownership_audit',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('runner_instance_id', sa.Uuid(), sa.ForeignKey('sandbox_runner_identities.runner_instance_id'), nullable=False),
        sa.Column('runner_generation', sa.BigInteger(), nullable=False),
        sa.Column('execution_id', sa.Uuid()),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('resource', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    # Never erase identities, unknown outcomes or the cleanup audit to roll back.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM sandbox_runner_identities) OR "
               "EXISTS (SELECT 1 FROM sandbox_ownership) OR EXISTS (SELECT 1 FROM sandbox_ownership_audit) "
               "THEN RAISE EXCEPTION 'SANDBOX_OWNERSHIP_HISTORY_PRESENT'; END IF; END $$")
    op.drop_table('sandbox_ownership_audit')
    op.drop_table('sandbox_ownership')
    op.drop_index('ix_sandbox_runner_identities_project_id', table_name='sandbox_runner_identities')
    op.drop_table('sandbox_runner_identities')
