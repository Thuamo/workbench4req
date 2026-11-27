"""Separate processing tasks from requirement assets; retain all historical identities."""
import json,uuid
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('processing_task_contexts',sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('run_id',sa.String(36),sa.ForeignKey('agent_runs.id'),nullable=False),sa.Column('requirement_id',sa.String(36),sa.ForeignKey('requirements.id')),sa.Column('legacy_requirement_id',sa.String(36),sa.ForeignKey('requirements.id')),sa.Column('legacy_hidden',sa.Boolean(),nullable=False),sa.Column('needs_review',sa.Boolean(),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.UniqueConstraint('run_id'))
    op.create_index('ix_processing_task_contexts_requirement_id','processing_task_contexts',['requirement_id'])
    op.create_table('processing_task_documents',sa.Column('id',sa.String(36),primary_key=True),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('run_id',sa.String(36),sa.ForeignKey('agent_runs.id'),nullable=False),sa.Column('version_id',sa.String(36),sa.ForeignKey('document_versions.id'),nullable=False),sa.Column('role',sa.String(20),nullable=False),sa.UniqueConstraint('run_id','version_id','role'))
    op.create_index('ix_processing_task_documents_run_id','processing_task_documents',['run_id'])
    c=op.get_bind()
    def rows(sql,**params):return c.execute(sa.text(sql),params).mappings().all()
    def obj(v):return json.loads(v) if isinstance(v,str) else v or {}
    requirements={r['id']:r for r in rows('SELECT * FROM requirements')}
    contexts={r['requirement_id']:r for r in rows('SELECT * FROM requirement_contexts')}
    manual={r['resource_id'] for r in rows("SELECT resource_id FROM audit_logs WHERE action IN ('requirement.create','requirement.edit')")}
    reviewed={r['requirement_id'] for r in rows('SELECT d.requirement_id FROM review_requests r JOIN document_versions v ON v.id=r.version_id JOIN knowledge_documents d ON d.id=v.document_id')}
    confirmed_questions={r['requirement_id'] for r in rows("SELECT requirement_id FROM clarification_questions WHERE status='confirmed'")}
    confirmed_relations={value for r in rows("SELECT source_id,target_id FROM requirement_relations WHERE status='confirmed'") for value in (r['source_id'],r['target_id'])}
    parents={r['parent_id'] for r in contexts.values() if r['parent_id']}
    versions={r['id']:r for r in rows('SELECT v.*,d.owner_id,d.requirement_id FROM document_versions v JOIN knowledge_documents d ON d.id=v.document_id')}
    linked=set()
    ct=sa.table('processing_task_contexts',*[sa.column(n) for n in ['id','created_at','run_id','requirement_id','legacy_requirement_id','legacy_hidden','needs_review','revision']])
    dt=sa.table('processing_task_documents',*[sa.column(n) for n in ['id','created_at','run_id','version_id','role']])
    for run in rows('SELECT * FROM agent_runs'):
        inputs=obj(run['inputs']);result=obj(run['result']);rid=inputs.get('requirement_id');req=requirements.get(rid);ctx=contexts.get(rid,{})
        legacy=bool(req and req['owner_id']==run['owner_id'] and ctx.get('origin_run_id')==run['id'] and req['number']=='TASK-'+run['id'][:8])
        hidden=legacy and rid not in manual and rid not in reviewed and rid not in parents and rid not in confirmed_questions and rid not in confirmed_relations and not req['acceptance'].strip() and not obj(req['tags'])
        c.execute(ct.insert().values(id=str(uuid.uuid4()),created_at=datetime.utcnow(),run_id=run['id'],requirement_id=rid if req and req['owner_id']==run['owner_id'] and not hidden else None,legacy_requirement_id=rid if legacy else None,legacy_hidden=hidden,needs_review=legacy and not hidden,revision=1))
        if legacy and not hidden:
            c.execute(sa.text("UPDATE requirement_contexts SET kind='business' WHERE requirement_id=:rid AND kind='working'"),{'rid':rid})
        output=set(result.get('saved_version_ids',[]))
        if result.get('saved_version_id'):output.add(result['saved_version_id'])
        output.update(v['id'] for v in versions.values() if obj(v['provenance']).get('agent_run_id')==run['id'] and v['owner_id']==run['owner_id'])
        for role,ids in [('input',inputs.get('source_version_ids',[])),('sample',inputs.get('sample_version_ids',[])),('output',output)]:
            for vid in ids:
                if vid not in versions or (run['id'],vid,role) in linked:continue
                if role=='output' and versions[vid]['owner_id']!=run['owner_id']:continue
                c.execute(dt.insert().values(id=str(uuid.uuid4()),created_at=datetime.utcnow(),run_id=run['id'],version_id=vid,role=role));linked.add((run['id'],vid,role))
        if hidden:
            # Only current working-copy metadata and unreviewed output asset links change.
            # Raw inputs, old requirement IDs, version content, reviews and citations stay intact.
            c.execute(sa.text('UPDATE document_workspaces SET requirement_id=NULL,confirmed_revision=CASE WHEN confirmed_revision=revision THEN revision+1 ELSE confirmed_revision END,revision=revision+1 WHERE run_id=:run AND requirement_id=:rid'),{'run':run['id'],'rid':rid})
            for vid in output:
                v=versions.get(vid)
                if v and v['owner_id']==run['owner_id'] and v['requirement_id']==rid:
                    c.execute(sa.text('UPDATE knowledge_documents SET requirement_id=NULL WHERE id=:id AND requirement_id=:rid'),{'id':v['document_id'],'rid':rid})

def downgrade():
    # Reconnect hidden legacy assets before removing their mapping, without modifying content.
    c=op.get_bind()
    for r in c.execute(sa.text('SELECT * FROM processing_task_contexts WHERE legacy_hidden=true')).mappings().all():
        c.execute(sa.text('UPDATE document_workspaces SET requirement_id=:rid WHERE run_id=:run AND requirement_id IS NULL'),{'rid':r['legacy_requirement_id'],'run':r['run_id']})
        c.execute(sa.text("UPDATE knowledge_documents SET requirement_id=:rid WHERE requirement_id IS NULL AND id IN (SELECT v.document_id FROM document_versions v JOIN processing_task_documents t ON t.version_id=v.id WHERE t.run_id=:run AND t.role='output')"),{'rid':r['legacy_requirement_id'],'run':r['run_id']})
    op.drop_table('processing_task_documents')
    op.drop_table('processing_task_contexts')
