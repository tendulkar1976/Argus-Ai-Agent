from alembic import op
from argus.judges import judges

revision = "0004"
down_revision = "0003"


def upgrade():
    judges.create(op.get_bind())


def downgrade():
    judges.drop(op.get_bind())
