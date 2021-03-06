"""empty message

Revision ID: 1ffe35d8c935
Revises: d98e5383b2b0
Create Date: 2021-01-18 17:52:14.957245

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1ffe35d8c935'
down_revision = 'd98e5383b2b0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('games', sa.Column('has_reporting', sa.Boolean(), server_default='true', nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('games', 'has_reporting')
    # ### end Alembic commands ###
