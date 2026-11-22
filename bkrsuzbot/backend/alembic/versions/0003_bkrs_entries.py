"""bkrs_entries: статьи 大БКРС (bkrs.info), китайско-русский словарь

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bkrs_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('headword', sa.String(length=255), nullable=False),
        sa.Column('pinyin', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('body', sa.Text(), nullable=False),
    )
    op.create_index('ix_bkrs_headword', 'bkrs_entries', ['headword'])


def downgrade() -> None:
    op.drop_index('ix_bkrs_headword', table_name='bkrs_entries')
    op.drop_table('bkrs_entries')
