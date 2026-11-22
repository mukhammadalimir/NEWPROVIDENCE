"""wikt_pairs: переводы ru/uz ↔ zh из Wiktionary

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'wikt_pairs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lang', sa.String(length=4), nullable=False),
        sa.Column('term', sa.String(length=64), nullable=False),
        sa.Column('zh', sa.String(length=16), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_wikt_lang_term', 'wikt_pairs', ['lang', 'term'])
    op.create_index('ix_wikt_lang_zh', 'wikt_pairs', ['lang', 'zh'])


def downgrade() -> None:
    op.drop_index('ix_wikt_lang_zh', table_name='wikt_pairs')
    op.drop_index('ix_wikt_lang_term', table_name='wikt_pairs')
    op.drop_table('wikt_pairs')
