"""empty message

Revision ID: 07d625c1ae4c
Revises: 72dad04d15af
Create Date: 2021-01-16 00:54:59.323795

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '07d625c1ae4c'
down_revision = '72dad04d15af'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('log_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('msg_type', sa.String(length=32), nullable=False),
    sa.Column('msg', sa.String(length=256), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_log_messages_msg_type'), 'log_messages', ['msg_type'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_log_messages_msg_type'), table_name='log_messages')
    op.drop_table('log_messages')
    # ### end Alembic commands ###
