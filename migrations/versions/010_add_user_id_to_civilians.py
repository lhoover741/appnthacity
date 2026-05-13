"""Add nullable user ownership to civilian profiles.

Revision ID: 010_add_user_id_to_civilians
Revises: 009_config_unique_key_community
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = '010_add_user_id_to_civilians'
down_revision = '009_config_unique_key_community'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('civilians', schema=None) as batch_op:
        try:
            batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        except Exception:
            pass


def downgrade():
    with op.batch_alter_table('civilians', schema=None) as batch_op:
        try:
            batch_op.drop_column('user_id')
        except Exception:
            pass
