"""Four disabled model slots for the configured local development tenant."""
from uuid import UUID
import sqlalchemy as sa
from alembic import op
from app.core.config import get_settings

revision = "0001_model_slots"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    slots = op.create_table(
        "model_slots",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64)), sa.Column("base_url", sa.String(512)),
        sa.Column("model", sa.String(128)), sa.Column("credential_reference", sa.String(128)),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="4096"),
        sa.Column("timeout", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "role"),
        sa.CheckConstraint("role IN ('planner','coder','researcher','reviewer')", name="ck_model_role"),
        sa.CheckConstraint("timeout BETWEEN 1 AND 300", name="ck_model_timeout"),
        sa.CheckConstraint("max_tokens BETWEEN 1 AND 131072", name="ck_model_tokens"),
        sa.CheckConstraint("temperature BETWEEN 0 AND 2", name="ck_model_temperature"),
    )
    tenant = UUID(get_settings().tenant_id)
    op.bulk_insert(slots, [{"tenant_id": tenant, "role": role} for role in ("planner", "coder", "researcher", "reviewer")])


def downgrade():
    op.drop_table("model_slots")
