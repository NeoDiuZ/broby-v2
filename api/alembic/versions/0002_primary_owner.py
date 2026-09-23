"""Preserve the primary contact while supporting multiple owners."""
from alembic import op
import sqlalchemy as sa
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('owner_patients', sa.Column('is_primary', sa.Boolean(), server_default=sa.false(), nullable=False))
    # Rebuild only derived projections; original records/events are retained.
    op.execute('DELETE FROM projection_checkpoints')

def downgrade():
    op.drop_column('owner_patients', 'is_primary')
