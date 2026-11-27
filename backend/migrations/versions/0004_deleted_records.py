"""Keep deletion tombstones without breaking document and audit references."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('deleted_records',sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('resource_type',sa.String(40),nullable=False),sa.Column('resource_id',sa.String(36),nullable=False),sa.Column('owner_id',sa.String(36),sa.ForeignKey('users.id')),sa.Column('deleted_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('reason',sa.Text(),nullable=False),sa.UniqueConstraint('resource_type','resource_id'))

def downgrade():
    op.drop_table('deleted_records')
