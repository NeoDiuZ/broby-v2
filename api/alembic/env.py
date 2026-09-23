from alembic import context
from spine.database import engine
from spine.models import Base
if context.is_offline_mode():
    context.configure(url=str(engine().url),target_metadata=Base.metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
else:
    with engine().connect() as connection:
        context.configure(connection=connection,target_metadata=Base.metadata)
        with context.begin_transaction():context.run_migrations()
