from alembic import op
from argus.cache import entries

revision = "0002"
down_revision = "0001"


def upgrade():
    entries.create(op.get_bind())


def downgrade():
    entries.drop(op.get_bind())
