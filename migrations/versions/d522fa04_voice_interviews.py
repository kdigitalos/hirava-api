"""Bounded L1 voice interview sessions; no candidate audio storage."""
from alembic import op
import sqlalchemy as sa
revision = "d522fa04"
down_revision = "c421ef03"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("voice_interviews",
        sa.Column("id",sa.String(36),primary_key=True),sa.Column("customer_id",sa.String(100),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("interview_id",sa.Integer(),nullable=False),sa.Column("candidate_id",sa.Integer(),nullable=False),
        sa.Column("actor_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),sa.Column("token_hash",sa.String(64),unique=True,nullable=False),
        sa.Column("title",sa.String(200),nullable=False),sa.Column("job_description",sa.Text(),nullable=False),
        sa.Column("questions",sa.JSON(),nullable=False),sa.Column("answers",sa.JSON(),nullable=False),sa.Column("current_question",sa.Text(),nullable=False),
        sa.Column("question_index",sa.Integer(),nullable=False),sa.Column("followup",sa.Boolean(),nullable=False),sa.Column("allow_followups",sa.Boolean(),nullable=False),
        sa.Column("status",sa.String(30),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("started_at",sa.DateTime(timezone=True)),sa.Column("consent_at",sa.DateTime(timezone=True)),sa.Column("minutes",sa.Integer(),nullable=False),
        sa.Column("speech_calls",sa.Integer(),nullable=False),sa.Column("transcription_calls",sa.Integer(),nullable=False),
        sa.Column("lease",sa.String(36)),sa.Column("lease_until",sa.DateTime(timezone=True)),sa.Column("summary",sa.JSON()),sa.Column("summary_calls",sa.Integer(),nullable=False))
    op.create_index("ix_voice_interviews_customer_id","voice_interviews",["customer_id"])
    op.create_index("ix_voice_interviews_interview_id","voice_interviews",["interview_id"])

def downgrade():
    op.drop_table("voice_interviews")
