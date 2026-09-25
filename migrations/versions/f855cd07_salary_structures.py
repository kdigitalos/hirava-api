"""Immutable salary structure definitions; no employee compensation changes."""
from alembic import op
import sqlalchemy as sa

revision = "f855cd07"
down_revision = "f744bc06"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("salary_structures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("customer_id", "code", "effective_from"))
    op.create_index("ix_salary_structures_customer_id", "salary_structures", ["customer_id"])


def downgrade():
    op.drop_index("ix_salary_structures_customer_id", table_name="salary_structures")
    op.drop_table("salary_structures")
