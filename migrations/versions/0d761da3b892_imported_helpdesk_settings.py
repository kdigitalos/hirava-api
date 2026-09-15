"""Make existing helpdesk settings storage explicit instead of CREATE on GET."""
from alembic import op
import sqlalchemy as sa

revision = '0d761da3b892'
down_revision = 'b72d5306ef01'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    table = sa.Table('ask_me_helpdesk_settings', sa.MetaData(),
        sa.Column('id', sa.Text(), primary_key=True), sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema='public' if bind.dialect.name == 'postgresql' else None)
    table.create(bind, checkfirst=True)


def downgrade():
    # The table may predate this migration and contain existing customer settings.
    # Retain it rather than destroy data owned by the imported application.
    pass
