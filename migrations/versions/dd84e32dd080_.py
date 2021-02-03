"""empty message

Revision ID: dd84e32dd080
Revises: 0f076aac7649
Create Date: 2021-02-03 17:29:33.476462

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'dd84e32dd080'
down_revision = '0f076aac7649'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('players', 'created', new_column_name='created_at')
    op.alter_column('games', 'created', new_column_name='created_at')
    op.alter_column('game_plays', 'created', new_column_name='created_at')
    op.alter_column('ratings', 'created', new_column_name='created_at')


def downgrade():
    op.alter_column('players', 'created_at', new_column_name='created')
    op.alter_column('games', 'created_at', new_column_name='created')
    op.alter_column('game_plays', 'created_at', new_column_name='created')
    op.alter_column('ratings', 'created_at', new_column_name='created')
