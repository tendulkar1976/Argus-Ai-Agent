from alembic import context
from argus.db import engine
from argus.schema_v1 import metadata

with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=metadata)
    context.run_migrations()
