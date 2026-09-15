"""Durable account invitation recovery."""
from alembic import op
import sqlalchemy as sa
revision = "b72d5306ef01"
down_revision = "a61c42f5de90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("account_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("employee_id", sa.String(100)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)))
    op.create_index("ix_account_invitations_customer_id", "account_invitations", ["customer_id"])


def downgrade():
    op.drop_table("account_invitations")
