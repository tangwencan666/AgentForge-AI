"""Private persistent Sandbox freeze; no adoption, credentials or OPEN defaults."""
from alembic import op
import sqlalchemy as sa

revision = '0010_sandbox_maintenance'
down_revision = '0009_sandbox_ownership'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sandbox_maintenance',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('deployment_id', sa.Uuid(), nullable=False),
        sa.Column('daemon_id', sa.String(128), nullable=False),
        sa.Column('epoch', sa.BigInteger(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id=1 AND epoch>0 AND state IN ('FROZEN','DRAINING','OPEN')", name='ck_maintenance_state'))
    op.create_table('sandbox_maintenance_authorities',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('deployment_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('proof_hash', sa.String(64), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.CheckConstraint("kind IN ('operator','approver')", name='ck_maintenance_authority'))
    op.create_table('sandbox_thaw_grants',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('deployment_id', sa.Uuid(), nullable=False),
        sa.Column('freeze_epoch', sa.BigInteger(), nullable=False),
        sa.Column('operator_id', sa.Uuid(), sa.ForeignKey('sandbox_maintenance_authorities.id'), nullable=False),
        sa.Column('approver_id', sa.Uuid(), sa.ForeignKey('sandbox_maintenance_authorities.id'), nullable=False),
        sa.Column('runner_instance_id', sa.Uuid(), sa.ForeignKey('sandbox_runner_identities.runner_instance_id'), nullable=False),
        sa.Column('runner_generation', sa.BigInteger(), nullable=False),
        sa.Column('daemon_id', sa.String(128), nullable=False),
        sa.Column('evidence_id', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('ISSUED','USED')", name='ck_thaw_status'))
    op.create_table('sandbox_maintenance_audit',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('deployment_id', sa.Uuid(), nullable=False),
        sa.Column('epoch', sa.BigInteger(), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('actor_id', sa.Uuid()),
        sa.Column('grant_id', sa.Uuid()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM sandbox_maintenance) OR "
        "EXISTS (SELECT 1 FROM sandbox_maintenance_authorities) OR EXISTS (SELECT 1 FROM sandbox_thaw_grants) OR "
        "EXISTS (SELECT 1 FROM sandbox_maintenance_audit) THEN RAISE EXCEPTION 'SANDBOX_MAINTENANCE_HISTORY_PRESENT'; END IF; END $$")
    for table in ('sandbox_maintenance_audit', 'sandbox_thaw_grants', 'sandbox_maintenance_authorities', 'sandbox_maintenance'):
        op.drop_table(table)
