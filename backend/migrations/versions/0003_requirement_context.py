"""Add business requirement, working draft and structured detail hierarchy."""
import json
import uuid
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    table=op.create_table('requirement_contexts',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('requirement_id',sa.String(36),sa.ForeignKey('requirements.id'),nullable=False,unique=True),
        sa.Column('kind',sa.String(20),nullable=False),
        sa.Column('parent_id',sa.String(36),sa.ForeignKey('requirements.id')),
        sa.Column('origin_run_id',sa.String(36),sa.ForeignKey('agent_runs.id')))
    op.create_index('ix_requirement_contexts_parent_id','requirement_contexts',['parent_id'])
    connection=op.get_bind()
    def obj(value):
        return json.loads(value) if isinstance(value,str) else value or {}
    requirements={row['id']:row for row in connection.execute(sa.text('SELECT id,owner_id,number FROM requirements')).mappings()}
    runs={row['id']:row for row in connection.execute(sa.text('SELECT id,owner_id,inputs,result FROM agent_runs')).mappings()}
    contexts={}
    for run in runs.values():
        rid=obj(run['inputs']).get('requirement_id')
        requirement=requirements.get(rid)
        if requirement and requirement['owner_id']==run['owner_id'] and requirement['number']=='TASK-'+run['id'][:8]:
            saved=connection.execute(sa.text("SELECT id FROM knowledge_documents WHERE requirement_id=:rid AND kind='specification'"),{'rid':rid}).first()
            contexts[rid]={'kind':'business' if saved else 'working','parent_id':None,'origin_run_id':run['id']}
    for event in connection.execute(sa.text("SELECT resource_id,detail FROM audit_logs WHERE action='agent.confirm_requirement_candidate' ORDER BY created_at")).mappings():
        run=runs.get(obj(event['detail']).get('run_id'))
        child=requirements.get(event['resource_id'])
        parent_id=obj(run['inputs']).get('requirement_id') if run else None
        parent=requirements.get(parent_id)
        if child and parent and child['id']!=parent_id and child['owner_id']==parent['owner_id']==run['owner_id']:
            contexts[child['id']]={'kind':'detail','parent_id':parent_id,'origin_run_id':run['id']}
    for rid,context in contexts.items():
        connection.execute(table.insert().values(id=str(uuid.uuid4()),created_at=datetime.utcnow(),requirement_id=rid,**context))


def downgrade():
    op.drop_index('ix_requirement_contexts_parent_id',table_name='requirement_contexts')
    op.drop_table('requirement_contexts')
