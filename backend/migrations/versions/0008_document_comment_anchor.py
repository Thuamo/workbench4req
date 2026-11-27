"""Keep positional context for document comments."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('document_comments', sa.Column('anchor', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('document_comments', 'anchor')
