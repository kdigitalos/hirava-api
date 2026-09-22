"""Durable reviewer-triggered candidate screening."""
from alembic import op
import sqlalchemy as sa

revision = "f582be093dc1"
down_revision = "0d761da3b892"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("screening_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("active_slot", sa.String(150), unique=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("rubric", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    for column in ("customer_id", "candidate_id", "status"):
        op.create_index(f"ix_screening_jobs_{column}", "screening_jobs", [column])


def downgrade():
    op.drop_table("screening_jobs")
