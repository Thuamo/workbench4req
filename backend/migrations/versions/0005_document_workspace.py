"""Independent rich-text working copies and human-confirmed AI proposals."""
from alembic import op
import sqlalchemy as sa
import json, uuid
from datetime import datetime

revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None

def identity():
    return [sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False)]

def fk(name,target,nullable=True):
    return sa.Column(name,sa.String(36),sa.ForeignKey(target),nullable=nullable)

def upgrade():
    op.create_table('document_workspaces',*identity(),fk('owner_id','users.id',False),sa.Column('origin_key',sa.String(90),nullable=False),fk('run_id','agent_runs.id'),fk('document_id','knowledge_documents.id'),fk('version_id','document_versions.id'),fk('requirement_id','requirements.id'),sa.Column('title',sa.String(300),nullable=False),sa.Column('label',sa.String(80),nullable=False),fk('base_id','knowledge_bases.id'),fk('folder_id','knowledge_folders.id'),sa.Column('content_json',sa.JSON()),sa.Column('content',sa.Text(),nullable=False),sa.Column('change_note',sa.Text(),nullable=False),sa.Column('sources',sa.JSON(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('confirmed_revision',sa.Integer()),sa.Column('updated_at',sa.DateTime(),nullable=False),sa.UniqueConstraint('owner_id','origin_key'))
    op.create_table('document_assistant_messages',*identity(),fk('workspace_id','document_workspaces.id',False),sa.Column('role',sa.String(20),nullable=False),sa.Column('mode',sa.String(20),nullable=False),sa.Column('content',sa.Text(),nullable=False),sa.Column('detail',sa.JSON(),nullable=False))
    op.create_index('ix_document_assistant_messages_workspace_id','document_assistant_messages',['workspace_id'])
    op.create_table('document_proposals',*identity(),fk('workspace_id','document_workspaces.id',False),sa.Column('base_revision',sa.Integer(),nullable=False),sa.Column('before_content',sa.Text(),nullable=False),sa.Column('suggested_content',sa.Text(),nullable=False),sa.Column('preview_json',sa.JSON()),sa.Column('status',sa.String(20),nullable=False),sa.Column('detail',sa.JSON(),nullable=False))
    op.create_index('ix_document_proposals_workspace_id','document_proposals',['workspace_id'])
    op.create_table('document_changes',*identity(),fk('workspace_id','document_workspaces.id',False),fk('actor_id','users.id',False),fk('proposal_id','document_proposals.id'),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('before_json',sa.JSON()),sa.Column('after_json',sa.JSON(),nullable=False),sa.Column('before_content',sa.Text(),nullable=False),sa.Column('after_content',sa.Text(),nullable=False),sa.UniqueConstraint('proposal_id'))
    op.create_index('ix_document_changes_workspace_id','document_changes',['workspace_id'])
    # Repair only the identified imported SRS skill. Runs retain their immutable version.
    conn=op.get_bind()
    for row in conn.execute(sa.text('SELECT s.id,s.current_version_id,v.config,v.creator_id FROM skills s JOIN skill_versions v ON v.id=s.current_version_id WHERE s.name=:name'),{'name':'软需生成V1'}).mappings().all():
        config=json.loads(row['config']) if isinstance(row['config'],str) else row['config']
        if config.get('workflow')!='qa' or '软需转化 Skill' not in config.get('system_prompt',''): continue
        vid=str(uuid.uuid4());config={**config,'workflow':'specification','human_confirmation':True,'package_metadata':{**config.get('package_metadata',{}),'workflow_repaired_from':row['current_version_id']}}
        table=sa.table('skill_versions',sa.column('id'),sa.column('created_at'),sa.column('skill_id'),sa.column('creator_id'),sa.column('config',sa.JSON()))
        conn.execute(table.insert().values(id=vid,created_at=datetime.utcnow(),skill_id=row['id'],creator_id=row['creator_id'],config=config))
        conn.execute(sa.text('UPDATE skills SET current_version_id=:vid WHERE id=:id'),{'vid':vid,'id':row['id']})

def downgrade():
    for name in ['document_changes','document_proposals','document_assistant_messages','document_workspaces']: op.drop_table(name)
