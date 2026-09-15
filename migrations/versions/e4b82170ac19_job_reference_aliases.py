"""Stable aliases for existing RMS candidate and interview references."""
from alembic import op
import sqlalchemy as sa

revision = 'e4b82170ac19'
down_revision = 'c37d9f21a640'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('job_references',
                    sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column('requisition_id', sa.String(36), sa.ForeignKey('requisitions.id'), nullable=False, unique=True))
    op.execute('INSERT INTO job_references (requisition_id) SELECT id FROM requisitions ORDER BY created_at, id')


def downgrade():
    op.drop_table('job_references')
