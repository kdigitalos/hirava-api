"""Persistent employee claims using shared identity, documents and audit."""
from alembic import op
import sqlalchemy as sa

revision = "f19a20c4d611"
down_revision = "e4b82170ac19"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("expense_claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("expense_type", sa.String(150), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("documents.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("decision_reason", sa.Text()))
    op.create_index("ix_expense_claims_customer_id", "expense_claims", ["customer_id"])


def downgrade():
    op.drop_table("expense_claims")
