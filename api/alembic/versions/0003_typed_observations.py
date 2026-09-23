"""Preserve typed observations and guard values at the database boundary."""
from alembic import op
import sqlalchemy as sa
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None
CHECK="(value_type = 'number' AND value IS NOT NULL AND text_value IS NULL AND boolean_value IS NULL) OR (value_type = 'text' AND value IS NULL AND text_value IS NOT NULL AND boolean_value IS NULL AND ref_low IS NULL AND ref_high IS NULL) OR (value_type = 'boolean' AND value IS NULL AND text_value IS NULL AND boolean_value IS NOT NULL AND ref_low IS NULL AND ref_high IS NULL)"
def upgrade():
    op.add_column('concepts',sa.Column('value_type',sa.String(),nullable=False,server_default='number'))
    op.add_column('observations',sa.Column('value_type',sa.String(),nullable=False,server_default='number'))
    op.add_column('observations',sa.Column('text_value',sa.Text(),nullable=True))
    op.add_column('observations',sa.Column('boolean_value',sa.Boolean(),nullable=True))
    op.alter_column('observations','value',nullable=True)
    op.create_check_constraint('ck_observation_type','observations',CHECK)
    op.execute('UPDATE projection_checkpoints SET sequence = -1')
def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM observations WHERE value_type <> 'number'")).scalar():
        raise RuntimeError('Cannot remove typed observation columns while nonnumeric facts exist; restore the pre-release backup instead')
    op.drop_constraint('ck_observation_type','observations',type_='check')
    op.alter_column('observations','value',nullable=False)
    for column in ('value_type','text_value','boolean_value'):op.drop_column('observations',column)
    op.drop_column('concepts','value_type')
