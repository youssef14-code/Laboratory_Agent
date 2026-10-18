"""add result_requests

Revision ID: 04e8cdbbed40
Revises: d2f01e1a7fca
Create Date: 2026-10-15 23:27:53.556460

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04e8cdbbed40'
down_revision = 'd2f01e1a7fca'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('result_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_identity', sa.String(length=150), nullable=False),
    sa.Column('laboratory_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'DONE', 'NO_SHOW', name='status'), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['laboratory_id'], ['laboratory.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('result_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_result_requests_user_identity'), ['user_identity'], unique=False)


def downgrade():
    with op.batch_alter_table('result_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_result_requests_user_identity'))

    op.drop_table('result_requests')