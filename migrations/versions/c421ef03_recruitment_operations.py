"""Recruitment identity reviews, talent pools, activity, reports and work signals."""
from alembic import op
import sqlalchemy as sa
revision = "c421ef03"
down_revision = "b321de02"
branch_labels = None
depends_on = None


def base():
    return [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("customer_id", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False)]


def actor(nullable=False):
    return sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=nullable)


def upgrade():
    op.create_table("candidate_identity_links", *base(),
        sa.Column("left_id", sa.Integer(), nullable=False), sa.Column("right_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False), actor(), sa.Column("note", sa.String(1000), nullable=False),
        sa.UniqueConstraint("customer_id", "left_id", "right_id", name="uq_candidate_link_pair"))
    op.create_table("talent_pools", *base(), sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False), actor(),
        sa.UniqueConstraint("customer_id", "name", name="uq_talent_pool_name"))
    op.create_table("talent_pool_members", *base(),
        sa.Column("pool_id", sa.String(36), sa.ForeignKey("talent_pools.id"), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False), sa.Column("contact_preference", sa.String(30), nullable=False),
        sa.Column("review_at", sa.DateTime(timezone=True), nullable=False), actor(),
        sa.UniqueConstraint("pool_id", "candidate_id", name="uq_talent_pool_member"))
    op.create_table("recruitment_activity", *base(), actor(True), sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False), sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("from_stage", sa.String(50)), sa.Column("to_stage", sa.String(50)))
    op.create_index("ix_recruitment_activity_candidate_id", "recruitment_activity", ["candidate_id"])
    op.create_table("recruitment_reports", *base(), actor(), sa.Column("title", sa.String(150), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False), sa.Column("sections", sa.JSON(), nullable=False))
    op.create_table("recruitment_signals", *base(), sa.Column("signal_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("message", sa.String(300), nullable=False),
        sa.Column("href", sa.String(200), nullable=False),
        sa.UniqueConstraint("customer_id", "signal_key", name="uq_recruitment_signal"))
    op.create_table("recruitment_costs", *base(), actor(), sa.Column("voided", sa.Boolean(), nullable=False), sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("category", sa.String(40), nullable=False), sa.Column("note", sa.String(500), nullable=False),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_recruitment_costs_customer_id", "recruitment_costs", ["customer_id"])
    op.create_table("interview_reservations", *base(), sa.Column("interview_id", sa.Integer(), nullable=False),
        sa.Column("slot_ref", sa.String(50), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "interview_id", "slot_ref", "reviewer_id", name="uq_interview_reservation"))
    op.create_index("ix_interview_reservations_reviewer_id", "interview_reservations", ["reviewer_id"])
    op.create_index("ix_interview_reservations_customer_id", "interview_reservations", ["customer_id"])
    for table in ("candidate_identity_links", "talent_pools", "talent_pool_members", "recruitment_activity", "recruitment_reports", "recruitment_signals"):
        op.create_index(f"ix_{table}_customer_id", table, ["customer_id"])


def downgrade():
    for table in ("recruitment_costs", "interview_reservations", "recruitment_signals", "recruitment_reports", "recruitment_activity", "talent_pool_members", "talent_pools", "candidate_identity_links"):
        op.drop_table(table)
