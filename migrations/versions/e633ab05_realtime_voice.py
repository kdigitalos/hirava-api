"""Retain server-observed realtime interview transcripts."""
from alembic import op
import sqlalchemy as sa
revision = 'e633ab05'
down_revision = 'd522fa04'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('voice_interviews', sa.Column('realtime_call_id', sa.String(200), nullable=True))
    op.add_column('voice_interviews', sa.Column('realtime_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('voice_interviews', sa.Column('realtime_transcript', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('voice_interviews', sa.Column('realtime_error', sa.String(300), nullable=True))

def downgrade():
    for name in ['realtime_error','realtime_transcript','realtime_attempts','realtime_call_id']:
        op.drop_column('voice_interviews',name)
