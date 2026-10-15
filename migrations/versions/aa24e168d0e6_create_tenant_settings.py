"""create tenant_settings

Revision ID: aa24e168d0e6
Revises: 8a375d54f25a
Create Date: 2026-10-04 17:36:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa24e168d0e6'
down_revision = '8a375d54f25a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tenant_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('notification_email', sa.String(length=255), nullable=True),
        sa.Column('gmail_token_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id'),
    )


def downgrade():
    op.drop_table('tenant_settings')
