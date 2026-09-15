"""Human-reviewed employee improvement plans."""
from alembic import op
import sqlalchemy as sa

revision = "a61c42f5de90"
down_revision = "f19a20c4d611"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("improvement_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("milestones", sa.JSON(), nullable=False),
        sa.Column("reviews", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text()))
    op.create_index("ix_improvement_plans_customer_id", "improvement_plans", ["customer_id"])


def downgrade():
    op.drop_table("improvement_plans")
