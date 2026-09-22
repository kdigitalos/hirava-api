"""Individual interviewer feedback tasks with in-app reminder due dates."""
from alembic import op
import sqlalchemy as sa
revision = "b321de02"
down_revision = "a219bc01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("interview_panel_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("interview_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("slot_ref", sa.String(50), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()), sa.Column("rating", sa.Integer()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("customer_id", "interview_id", "slot_ref", "reviewer_id", name="uq_interview_panel_reviewer"))
    for column in ("customer_id", "interview_id", "reviewer_id"):
        op.create_index(f"ix_interview_panel_feedback_{column}", "interview_panel_feedback", [column])


def downgrade():
    op.drop_table("interview_panel_feedback")
