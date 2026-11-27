"""Store specification comments and images alongside document workspaces."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'document_comments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('document_workspaces.id')),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('document_versions.id')),
        sa.Column('author_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.CheckConstraint('(workspace_id IS NULL) <> (version_id IS NULL)', name='ck_document_comment_scope'),
    )
    op.create_index('ix_document_comments_workspace_id', 'document_comments', ['workspace_id'])
    op.create_index('ix_document_comments_version_id', 'document_comments', ['version_id'])
    op.create_table(
        'document_images',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('document_workspaces.id'), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('filename', sa.String(300), nullable=False),
        sa.Column('media_type', sa.String(30), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
    )
    op.create_index('ix_document_images_workspace_id', 'document_images', ['workspace_id'])


def downgrade():
    op.drop_table('document_images')
    op.drop_table('document_comments')
