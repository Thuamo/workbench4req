from collections import defaultdict
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select, func, or_

from ..models import (AgentRun, DeletedRecord, Document, DocumentVersion, Requirement, RequirementContext,
                      RequirementPack, RequirementPackDocument, RequirementPackSpecification, Outbox,
                      ProcessingTaskContext, ReviewRequest, TaskDocument)
from ..security import audit, can_version, owned
from ..serialize import record
from .deletion import active_filter, ensure_active, requirement_filter

Stage = Literal['clarification', 'specification', 'consolidation']
STAGES = ('clarification', 'specification', 'consolidation')


def workflow_stage(workflow):
    if workflow in ('specification', 'quality', 'uml'):
        return 'specification'
    if workflow in ('ppt_report', 'mind_map'):
        return 'consolidation'
    return 'clarification'


def lock_requirement(db, user, requirement_id):
    req = owned(db.scalar(select(Requirement).where(Requirement.id == requirement_id).with_for_update()), user)
    context = db.scalar(select(RequirementContext).where(RequirementContext.requirement_id == req.id))
    if context and context.kind != 'business' or not db.scalar(select(Requirement.id).where(
        Requirement.id == req.id, requirement_filter()
    )):
        raise HTTPException(422, '请选择有效业务需求')
    return req


def default_pack(requirement_id):
    return RequirementPack(id=requirement_id, requirement_id=requirement_id, number=1, name='默认需求包')


def pack_for(db, requirement_id, pack_id, *, persist=False):
    pack_id = pack_id or requirement_id
    pack = db.get(RequirementPack, pack_id)
    if not pack and pack_id == requirement_id:
        pack = default_pack(requirement_id)
        if persist:
            db.add(pack)
            db.flush()
    if not pack or pack.requirement_id != requirement_id:
        raise HTTPException(404, '需求包不存在或不属于当前需求')
    ensure_active(db,'requirement_pack',pack.id)
    return pack


def pack_record(pack):
    return {'id':pack.id, 'number':f'B{pack.number:02d}', 'name':pack.name}


def list_packs(db, requirement_id):
    packs = list(db.scalars(select(RequirementPack).where(RequirementPack.requirement_id == requirement_id)
                           .where(active_filter('requirement_pack',RequirementPack.id)).order_by(RequirementPack.number)))
    if not db.get(RequirementPack,requirement_id):
        packs.insert(0,default_pack(requirement_id))
    return packs


def create_pack(db, user, req, name):
    if not db.get(RequirementPack,req.id):
        pack_for(db, req.id, req.id, persist=True)
    number = db.scalar(select(func.max(RequirementPack.number)).where(RequirementPack.requirement_id == req.id))
    pack = RequirementPack(requirement_id=req.id, number=number + 1, name=name)
    db.add(pack)
    db.flush()
    audit(db, user, 'requirement.pack_create', pack.id, requirement_id=req.id, number=pack.number)
    return pack_record(pack)


def remove_pack(db,user,requirement,pack):
    from .processing_tasks import readable_tasks
    for run in db.scalars(readable_tasks(user,requirement.id).where(
        AgentRun.status.in_(('pending','running','awaiting_confirmation'))
    )):
        if run_pack_id(requirement.id,run.inputs)==pack.id:
            raise HTTPException(409,'该需求包有尚未结束的任务，请结束任务后再删除')
    home=RequirementPackSpecification
    reviewing=db.scalar(select(ReviewRequest.id).join(DocumentVersion,DocumentVersion.id==ReviewRequest.version_id)
        .join(Document,Document.id==DocumentVersion.document_id).outerjoin(home,home.document_id==Document.id)
        .where(Document.requirement_id==requirement.id,Document.kind=='specification',
               or_(home.pack_id==pack.id,home.pack_id.is_(None)) if pack.id==requirement.id else home.pack_id==pack.id,
               ReviewRequest.status.in_(('pending','in_review'))).limit(1))
    if reviewing:
        raise HTTPException(409,'该需求包有正在会签的版本，请完成会签后再删除')
    db.add(DeletedRecord(resource_type='requirement_pack',resource_id=pack.id,
                         owner_id=requirement.owner_id,deleted_by=user.id))
    audit(db,user,'requirement.pack_delete',pack.id,requirement_id=requirement.id,number=pack.number)


def attach_versions(db, user, pack, stage, versions):
    for version in versions:
        ensure_active(db, 'document', version.document_id)
        if not db.scalar(select(RequirementPackDocument.id).where(
            RequirementPackDocument.pack_id == pack.id, RequirementPackDocument.stage == stage,
            RequirementPackDocument.version_id == version.id
        )):
            db.add(RequirementPackDocument(pack_id=pack.id, stage=stage, version_id=version.id))
            audit(db, user, 'requirement.pack_attach_document', version.id, pack_id=pack.id,
                  requirement_id=pack.requirement_id, stage=stage)


def run_pack_id(requirement_id, inputs):
    return inputs.get('_requirement_pack_id') or requirement_id


def lock_active_run_pack(db, requirement_id, inputs):
    if requirement_id:
        db.scalar(select(Requirement.id).where(Requirement.id==requirement_id).with_for_update())
        ensure_active(db,'requirement_pack',run_pack_id(requirement_id,inputs))


def assign_specification(db, run, document):
    pack_id = run.inputs.get('_requirement_pack_id') if run else None
    if run and document.requirement_id:
        lock_active_run_pack(db,document.requirement_id,run.inputs)
    if not pack_id or not document.requirement_id:
        return
    pack = pack_for(db, document.requirement_id, pack_id)
    existing = db.scalar(select(RequirementPackSpecification).where(
        RequirementPackSpecification.document_id == document.id))
    if existing and existing.pack_id != pack.id:
        raise HTTPException(409, '软需文档属于其他需求包')
    if not existing:
        db.add(RequirementPackSpecification(pack_id=pack.id, document_id=document.id))


def specification_versions(db, req, pack_id, user):
    home = RequirementPackSpecification
    rows = db.execute(select(Document, DocumentVersion).join(DocumentVersion)
                      .outerjoin(home, home.document_id == Document.id).where(
        Document.requirement_id == req.id, Document.kind == 'specification',
        active_filter('document', Document.id), DocumentVersion.parse_status == 'ready',
        or_(home.pack_id.is_(None),home.pack_id==pack_id) if pack_id == req.id else home.pack_id == pack_id
    ).order_by(DocumentVersion.created_at.desc(), DocumentVersion.id)).all()
    return [(doc, version) for doc, version in rows if can_version(db, version, user)]


def linked_versions(db, pack_ids, user):
    rows = db.execute(select(RequirementPackDocument, Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == RequirementPackDocument.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(RequirementPackDocument.pack_id.in_(pack_ids), active_filter('document', Document.id))).all()
    return [(link, doc, version) for link, doc, version in rows if can_version(db, version, user)]


def pack_sources(db, requirement, pack_id, user):
    found = {}
    if pack_id == requirement.id:
        direct = Document.requirement_id == requirement.id
        source = db.get(DocumentVersion,requirement.source_version_id) if requirement.source_version_id else None
        if source:
            direct = or_(direct,Document.id==source.document_id)
        rows = db.execute(select(Document,DocumentVersion).join(DocumentVersion).where(
            direct, Document.kind.in_(('business','reference')), active_filter('document',Document.id))).all()
        found.update({version.id:(doc,version) for doc,version in rows if can_version(db,version,user)})
    for _, doc, version in linked_versions(db, [pack_id], user):
        if doc.kind in ('business','reference'):
            found[version.id] = (doc,version)
    pack_scope=AgentRun.inputs['_requirement_pack_id'].as_string()==pack_id
    if pack_id==requirement.id:
        pack_scope=or_(pack_scope,AgentRun.inputs['_requirement_pack_id'].as_string().is_(None))
    rows=db.execute(select(Document,DocumentVersion).join(DocumentVersion)
        .join(TaskDocument,TaskDocument.version_id==DocumentVersion.id)
        .join(AgentRun,AgentRun.id==TaskDocument.run_id)
        .join(ProcessingTaskContext,ProcessingTaskContext.run_id==AgentRun.id)
        .where(ProcessingTaskContext.requirement_id==requirement.id,pack_scope,TaskDocument.role=='input',
               Document.kind.in_(('business','reference')),active_filter('document',Document.id),
               active_filter('agent_run',AgentRun.id))).all()
    found.update({version.id:(doc,version) for doc,version in rows if can_version(db,version,user)})
    return sorted(found.values(), key=lambda item:(item[1].created_at,item[1].id), reverse=True)


def workspace_packs(db, user, requirement, runs, task_assets, documents, reviews, questions, children, readonly):
    from .requirement_initialization import initialization_view, change_available

    rid = requirement.id
    packs = list_packs(db,rid)
    by_pack = {pack.id:[] for pack in packs}
    for run in runs:
        if run['pack_id'] in by_pack:
            by_pack[run['pack_id']].append(run)
    stages = defaultdict(dict)

    def add(pack_id, stage, doc, version):
        if pack_id not in by_pack:
            return
        entry = stages[(pack_id,stage)].setdefault(doc['id'],{**doc,'versions':{}})
        entry['versions'][version['id']] = version

    for link, doc, version in linked_versions(db, by_pack, user):
        add(link.pack_id, link.stage, record(doc), record(version,('content','blocks')))
    for run in runs:
        for item in task_assets.get(run['id'], []):
            add(run['pack_id'],run['pack_stage'],item['document'],item['version'])
    owners = dict(db.execute(select(RequirementPackSpecification.document_id,RequirementPackSpecification.pack_id)
                  .join(RequirementPack).where(RequirementPack.requirement_id==rid)).all())
    review_owners = {}
    for doc in documents:
        if doc['requirement_id'] != rid and 'direct' not in doc['roles'] and 'input' not in doc['roles']:
            continue
        if doc['kind'] == 'specification' and doc['requirement_id'] == rid:
            home = owners.get(doc['id'], rid)
            for version in doc['versions']:
                add(home,'specification',doc,version)
                review_owners[version['id']] = home
                if version['review_status'] == 'approved' or version['publish_status'] == 'published':
                    add(home,'consolidation',doc,version)
                elif version['status'] in ('superseded','archived','deprecated') and version['index_status'] == 'ready':
                    add(home,'consolidation',doc,version)
        elif (doc['requirement_id'] == rid or any(v['id'] == requirement.source_version_id for v in doc['versions'])):
            for version in doc['versions']:
                add(rid,'clarification',doc,version)

    run_owners = {run['id']:run['pack_id'] for run in runs}
    origins = dict(db.execute(select(RequirementContext.requirement_id, RequirementContext.origin_run_id)
                             .where(RequirementContext.parent_id == rid)).all())
    jobs = defaultdict(list)
    if review_owners:
        for job in db.scalars(select(Outbox).where(Outbox.resource_id.in_(review_owners),
                Outbox.kind.in_(('publish','reindex'))).order_by(Outbox.created_at.desc())):
            jobs[review_owners[job.resource_id]].append(
                {**record(job,('lease_token','lease_until','payload','error')),'version_id':job.resource_id})
    available = not readonly and change_available(db,user)
    result = []
    for pack in packs:
        pack_runs = by_pack[pack.id]
        sections = {}
        for stage in STAGES:
            entries = stages[(pack.id,stage)].values()
            sections[stage] = {
                'documents': [{**doc,'versions':sorted(doc['versions'].values(),key=lambda v:v['created_at'],reverse=True)}
                              for doc in entries],
                'runs':[run for run in pack_runs if run['pack_stage']==stage],
            }
        result.append({**pack_record(pack), 'stages':sections, 'publish_jobs':jobs[pack.id],
                       'review_versions':[version for doc in sections['specification']['documents']
                           for version in doc['versions'] if review_owners.get(version['id'])==pack.id
                           and version['status']=='draft' and version['parse_status']=='ready'
                           and (version['creator_id']==user.id or user.role=='super_admin') and not readonly],
                       'reviews':[review for review in reviews if review_owners.get(review['version_id'])==pack.id],
                       'questions':[question for question in questions if (
                           question.get('evidence',{}).get('requirement_pack_id') or
                           run_owners.get(question.get('evidence',{}).get('agent_run_id'),rid)) == pack.id],
                       'children':[child for child in children if run_owners.get(origins.get(child['id']),rid)==pack.id],
                       'initialization':None if readonly else initialization_view(db,user,requirement,pack_runs,pack.id),
                       'can_change':bool(available)})
    return result
