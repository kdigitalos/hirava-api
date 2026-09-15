"""Preserve mixed job fields on the canonical requisition.

Revision ID: c37d9f21a640
Revises: 99a3ef1c2db4
"""
from alembic import op
import sqlalchemy as sa

revision = 'c37d9f21a640'
down_revision = '99a3ef1c2db4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('requisitions', sa.Column('job_details', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('requisitions', 'job_details')
