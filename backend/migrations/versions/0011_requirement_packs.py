"""Add requirement packages and scoped document relationships."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('requirement_packs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('requirement_id', sa.String(36), sa.ForeignKey('requirements.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.UniqueConstraint('requirement_id','number'))
    op.create_index('ix_requirement_packs_requirement_id', 'requirement_packs', ['requirement_id'])
    op.create_table('requirement_pack_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('pack_id', sa.String(36), sa.ForeignKey('requirement_packs.id'), nullable=False),
        sa.Column('stage', sa.String(20), nullable=False),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('document_versions.id'), nullable=False),
        sa.UniqueConstraint('pack_id','stage','version_id'))
    op.create_index('ix_requirement_pack_documents_pack_id', 'requirement_pack_documents', ['pack_id'])
    op.create_table('requirement_pack_specifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('pack_id', sa.String(36), sa.ForeignKey('requirement_packs.id'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('knowledge_documents.id'), nullable=False, unique=True))
    op.create_index('ix_requirement_pack_specifications_pack_id', 'requirement_pack_specifications', ['pack_id'])


def downgrade():
    for table in ('requirement_pack_specifications','requirement_pack_documents','requirement_packs'):
        op.drop_table(table)
