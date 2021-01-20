"""empty message

Revision ID: 0f076aac7649
Revises: 1ffe35d8c935
Create Date: 2021-01-20 01:03:22.587149

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0f076aac7649'
down_revision = '1ffe35d8c935'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('games', sa.Column('supports_acc', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('games', sa.Column('supports_gyro', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('games', sa.Column('supports_key', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('games', sa.Column('supports_touch', sa.Boolean(), server_default='true', nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('games', 'supports_touch')
    op.drop_column('games', 'supports_key')
    op.drop_column('games', 'supports_gyro')
    op.drop_column('games', 'supports_acc')
    # ### end Alembic commands ###
