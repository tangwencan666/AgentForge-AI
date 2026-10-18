"""Persist per-role DeepSeek thinking settings; no credential values."""
from alembic import op
import sqlalchemy as sa

revision = '0007_deepseek'
down_revision = '0006_real_models'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('model_slots', sa.Column('thinking_mode', sa.String(8), server_default='disabled', nullable=False))
    op.add_column('model_slots', sa.Column('reasoning_effort', sa.String(8), server_default='high', nullable=False))
    op.create_check_constraint('ck_model_thinking', 'model_slots', "thinking_mode IN ('disabled','enabled')")
    op.create_check_constraint('ck_model_effort', 'model_slots', "reasoning_effort IN ('low','high','max')")


def downgrade():
    op.drop_constraint('ck_model_effort', 'model_slots', type_='check')
    op.drop_constraint('ck_model_thinking', 'model_slots', type_='check')
    op.drop_column('model_slots', 'reasoning_effort')
    op.drop_column('model_slots', 'thinking_mode')
