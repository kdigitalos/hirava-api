"""Durable external posting preparation and manual listing records."""
from alembic import op
import sqlalchemy as sa

revision = 'f744bc06'
down_revision = 'e633ab05'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('job_distributions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('requisition_id', sa.String(36), sa.ForeignKey('requisitions.id'), nullable=False),
        sa.Column('destination', sa.String(30), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('external_url', sa.String(2000)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.UniqueConstraint('requisition_id', 'destination'))
    op.create_index('ix_job_distributions_customer_id', 'job_distributions', ['customer_id'])


def downgrade():
    op.drop_index('ix_job_distributions_customer_id', table_name='job_distributions')
    op.drop_table('job_distributions')
