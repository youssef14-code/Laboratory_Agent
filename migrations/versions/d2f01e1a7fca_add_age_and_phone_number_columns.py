"""add age and phone_number columns

Revision ID: d2f01e1a7fca
Revises: aa24e168d0e6
Create Date: 2026-10-08

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd2f01e1a7fca'
down_revision = 'aa24e168d0e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('homevisits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('age', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('phone_number1', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('phone_number2', sa.String(length=50), nullable=True))
        batch_op.drop_column('phone_number')


def downgrade():
    with op.batch_alter_table('homevisits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone_number', sa.String(length=50), nullable=True))
        batch_op.drop_column('phone_number2')
        batch_op.drop_column('phone_number1')
        batch_op.drop_column('age')
