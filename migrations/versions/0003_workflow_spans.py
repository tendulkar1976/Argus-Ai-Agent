from alembic import op
from argus.workflows import spans

revision = "0003"
down_revision = "0002"


def upgrade():
    spans.create(op.get_bind())


def downgrade():
    spans.drop(op.get_bind())
