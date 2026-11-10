"""add total price to home visits

Revision ID: f1a9c7d2e6b4
Revises: d2f01e1a7fca
Create Date: 2026-10-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a9c7d2e6b4"
down_revision = "d2f01e1a7fca"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("homevisits", schema=None) as batch_op:
        batch_op.add_column(sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    with op.batch_alter_table("homevisits", schema=None) as batch_op:
        batch_op.drop_column("total_price")
