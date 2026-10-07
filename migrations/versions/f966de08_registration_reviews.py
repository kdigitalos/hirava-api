"""Owner registration review, independent from account activation."""
from alembic import op
import sqlalchemy as sa

revision = 'f966de08'
down_revision = 'f855cd07'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('company_registration_reviews',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('registration_id', sa.String(100), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('reviewed_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requested_terms', sa.JSON(), nullable=False),
        sa.UniqueConstraint('customer_id', 'registration_id'))
    op.create_index('ix_company_registration_reviews_customer_id', 'company_registration_reviews', ['customer_id'])


def downgrade():
    op.drop_table('company_registration_reviews')
