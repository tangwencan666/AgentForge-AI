"""UTC daily Mock reservation/settlement ledger, explicitly separate from real costs."""
import sqlalchemy as sa
from alembic import op
revision="0003_tenant_limits"
down_revision="0002_workflows"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("tenant_mock_usage",sa.Column("tenant_id",sa.Uuid(),primary_key=True),sa.Column("day",sa.Date(),primary_key=True),
        sa.Column("tokens_used",sa.Integer(),nullable=False),sa.Column("tokens_reserved",sa.Integer(),nullable=False),
        sa.Column("cost_used",sa.Numeric(16,8),nullable=False),sa.Column("cost_reserved",sa.Numeric(16,8),nullable=False))
    op.add_column("model_operations",sa.Column("reservation_day",sa.Date(),nullable=False,server_default=sa.func.current_date()))


def downgrade():
    op.drop_column("model_operations","reservation_day")
    op.drop_table("tenant_mock_usage")
