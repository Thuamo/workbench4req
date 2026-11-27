from collections import Counter
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Response
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from pydantic import Field
from typing import Literal
from ..db import get_db
from ..models import DEVELOPMENT_MEMBER, User, Requirement, Metric, Relation, Question, ClarificationTask, TaskHistory, AgentRun, Setting, Document, DocumentVersion, ReviewRequest, RequirementContext, SkillVersion,ProcessingTaskContext,TaskDocument,RequirementPack
from ..schemas import RequirementInput, RequirementWizardInput, TaskInput, QuestionInput, Strict
from ..security import current_user, owned, require_version, can_version, audit, write_lock
from ..serialize import record
from ..services.files import validate
from ..services.ledger import (import_ledger, export_ledger, ledger_columns, public_ledger_columns, preview_ledger,
                               lock_ledger, ledger_import_batches, undo_ledger_import)
from ..config import settings
from ..services.journey import requirement_record, context_for, version_stage, run_stage, work_items, conclusion_changed_after

from ..services.deletion import active_filter, requirement_filter, ensure_active, is_deleted

from ..services.processing_tasks import linked_id,task_record,task_documents,readable_requirements,readable_tasks

router=APIRouter(tags=['需求与澄清'])

from ..services.requirement_packs import (Stage, lock_requirement, create_pack, pack_for, pack_record, remove_pack,
                                         attach_versions, workspace_packs, linked_versions)


class NewPack(Strict):
    name: str = Field(min_length=1,max_length=120)


class AttachPackDocuments(Strict):
    version_ids: list[str] = Field(min_length=1,max_length=50)


class DeletePack(Strict):
    confirm: Literal[True]


@router.post('/requirements/{requirement_id}/packs')
def add_pack(requirement_id:str,data:NewPack,user:User=Depends(current_user),db:Session=Depends(get_db)):
    name = data.name.strip()
    if not name:
        raise HTTPException(422,'请填写需求包名称')
    write_lock(db)
    requirement = lock_requirement(db,user,requirement_id)
    pack = create_pack(db,user,requirement,name)
    db.commit()
    return pack


@router.patch('/requirements/{requirement_id}/packs/{pack_id}')
def rename_pack(requirement_id:str,pack_id:str,data:NewPack,user:User=Depends(current_user),db:Session=Depends(get_db)):
    name=data.name.strip()
    if not name:
        raise HTTPException(422,'请填写需求包名称')
    write_lock(db)
    lock_requirement(db,user,requirement_id)
    pack=pack_for(db,requirement_id,pack_id,persist=True)
    before=pack.name
    pack.name=name
    audit(db,user,'requirement.pack_rename',pack.id,requirement_id=requirement_id,before=before,after=name)
    db.commit()
    return pack_record(pack)


@router.delete('/requirements/{requirement_id}/packs/{pack_id}')
def delete_pack(requirement_id:str,pack_id:str,data:DeletePack,user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db)
    requirement=lock_requirement(db,user,requirement_id)
    pack=pack_for(db,requirement_id,pack_id,persist=True)
    remove_pack(db,user,requirement,pack)
    db.commit()
    return {'deleted':True}


@router.post('/requirements/{requirement_id}/packs/{pack_id}/stages/{stage}/documents')
def add_pack_documents(requirement_id:str,pack_id:str,stage:Stage,data:AttachPackDocuments,
                       user:User=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db)
    lock_requirement(db,user,requirement_id)
    pack = pack_for(db,requirement_id,pack_id,persist=True)
    versions = [require_version(db,vid,user) for vid in dict.fromkeys(data.version_ids)]
    attach_versions(db,user,pack,stage,versions)
    db.commit()
    return {'version_ids':[version.id for version in versions]}

@router.get('/clarification/tasks/{task_id}/requirement-candidates')
def ledger_requirement_candidates(task_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    task=db.get(ClarificationTask,task_id)
    if not task:raise HTTPException(404,'台账记录不存在')
    ensure_active(db,'clarification_task',task_id)
    from ..services.identity import ledger_matches
    return ledger_matches(db,user,task.fields)

@router.put('/clarification/tasks/{task_id}/requirement')
def ledger_requirement(task_id:str,data:dict,user:User=Depends(current_user),db:Session=Depends(get_db)):
    lock_ledger(db,user);task=owned(db.get(ClarificationTask,task_id),user);ensure_active(db,'clarification_task',task_id)
    if task.revision!=data.get('expected_revision'):raise HTTPException(409,'台账已更新，请刷新后核对')
    rid=data.get('requirement_id') or None
    if rid:
        owned(db.get(Requirement,rid),user);ensure_active(db,'requirement',rid)
        if not db.scalar(select(Requirement.id).where(Requirement.id==rid,requirement_filter())):raise HTTPException(422,'只能关联业务需求')
    old=task.requirement_id;task.requirement_id=rid;task.revision+=1
    db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields={**task.fields,'_关联变更':{'before':old,'after':rid}},revision=task.revision))
    audit(db,user,'ledger.link_requirement',task.id,requirement_id=rid);db.commit();return record(task)


@router.get('/requirements')
def requirements(user: User=Depends(current_user),db: Session=Depends(get_db)):
    visible=db.scalars(select(Requirement).where(readable_requirements(user)).order_by(Requirement.created_at.desc())).all()
    pending={r.requirement_id for r in db.scalars(select(ProcessingTaskContext).where(ProcessingTaskContext.needs_review.is_(True))).all()}
    docs={}
    pack_requirements=dict(db.execute(select(RequirementPack.id,RequirementPack.requirement_id).where(
        RequirementPack.requirement_id.in_([req.id for req in visible]),active_filter('requirement_pack',RequirementPack.id))).all())
    for link,doc,_ in linked_versions(db,pack_requirements,user):
        docs.setdefault(pack_requirements[link.pack_id],set()).add(doc.id)
    if user.role in (DEVELOPMENT_MEMBER,'super_admin'):
        for document,version in db.execute(select(Document,DocumentVersion).join(DocumentVersion,DocumentVersion.document_id==Document.id)
                                          .where(Document.requirement_id.is_not(None),active_filter('document',Document.id))):
            if can_version(db,version,user): docs.setdefault(document.requirement_id,set()).add(document.id)
        counts=Counter()
        for run in db.scalars(readable_tasks(user,include_related=True)):
            rid=linked_id(db,run)
            if not rid: continue
            counts[rid]+=1
            docs.setdefault(rid,set()).update(item['document']['id'] for item in task_documents(db,run,user))
        rows=[]
        for requirement in visible:
            summary=requirement_record(db,requirement)
            if requirement.source_version_id:
                version=db.get(DocumentVersion,requirement.source_version_id)
                if version and can_version(db,version,user) and not is_deleted(db,'document',version.document_id):
                    docs.setdefault(requirement.id,set()).add(version.document_id)
                else:
                    summary['source_version_id']=None
            can_edit=user.role=='super_admin' and requirement.owner_id==user.id
            rows.append({**summary,'task_count':counts[requirement.id],'document_count':len(docs.get(requirement.id,set())),
                         'can_edit':can_edit,'needs_review':can_edit and requirement.id in pending})
        return rows
    counts=dict(db.execute(select(ProcessingTaskContext.requirement_id,func.count()).join(AgentRun,AgentRun.id==ProcessingTaskContext.run_id).where(active_filter('agent_run',AgentRun.id)).group_by(ProcessingTaskContext.requirement_id)).all())
    for document in db.scalars(select(Document).where(Document.owner_id==user.id,active_filter('document',Document.id))).all():
        if document.requirement_id:docs.setdefault(document.requirement_id,set()).add(document.id)
    for rid,version in db.execute(select(ProcessingTaskContext.requirement_id,DocumentVersion).select_from(ProcessingTaskContext).join(AgentRun,AgentRun.id==ProcessingTaskContext.run_id).join(TaskDocument,TaskDocument.run_id==ProcessingTaskContext.run_id).join(DocumentVersion,DocumentVersion.id==TaskDocument.version_id).where(ProcessingTaskContext.requirement_id.is_not(None),AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id))).all():
        did=version.document_id
        if can_version(db,version,user) and db.scalar(select(Document.id).where(Document.id==did,active_filter('document',Document.id))):docs.setdefault(rid,set()).add(did)
    for req in db.scalars(select(Requirement).where(Requirement.owner_id==user.id,Requirement.source_version_id.is_not(None))).all():
        version=db.get(DocumentVersion,req.source_version_id)
        if version and can_version(db,version,user) and db.scalar(select(Document.id).where(Document.id==version.document_id,active_filter('document',Document.id))):docs.setdefault(req.id,set()).add(version.document_id)
    return [{**requirement_record(db,r),'task_count':counts.get(r.id,0),'document_count':len(docs.get(r.id,set())),'needs_review':r.id in pending} for r in visible]


def validate_requirement_state(db,user,data,requirement=None):
    if data.state in ('specified','published'):
        versions=db.scalars(select(DocumentVersion).join(Document,DocumentVersion.document_id==Document.id).where(Document.requirement_id==requirement.id,Document.kind=='specification')).all() if requirement else []
        if not versions or data.state=='published' and not any(v.status=='published' for v in versions):
            raise HTTPException(422,'已编制和已发布状态由文档版本及审核发布流程产生，请先确认文档版本或完成发布')


def business_number_exists(db, number):
    from ..services.identity import number_key
    target=number_key(number)
    numbers=db.scalars(select(Requirement.number).where(
        requirement_filter(),
        ~Requirement.id.in_(select(RequirementContext.requirement_id).where(RequirementContext.kind!='business')),
    ))
    return any(number_key(number)==target for number in numbers)


@router.get('/requirements/check-number')
def requirement_number_exists(number: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return {'exists':business_number_exists(db,number)}


@router.post('/requirements/create-from-wizard')
def requirement_wizard_create(data: RequirementWizardInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..services.identity import number_key
    from ..services.requirement_initialization import InitializeInput, initialize

    details=data.requirement
    number,title=details.number.strip(),details.title.strip()
    if not number_key(number) or not title:
        raise HTTPException(422,'请填写需求编号和需求名称')
    lock_ledger(db,user)
    if db.bind.dialect.name=='postgresql':
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext('requirement-wizard:'+number_key(number)))))
    if business_number_exists(db,number):
        raise HTTPException(409,'需求已存在，请检查需求编号。')
    validate_requirement_state(db,user,details)

    if details.source_version_id:
        version=require_version(db,details.source_version_id,user)
        ensure_active(db,'document',version.document_id)
        document=db.get(Document,version.document_id)
        if document.kind not in ('business','reference') or version.parse_status!='ready':
            raise HTTPException(422,'请选择已解析的业务需求文档')
    elif data.initialize_tasks:
        raise HTTPException(422,'请先上传或选择需求文档')

    requirement=Requirement(owner_id=user.id,number=number,title=title,
                            **details.model_dump(exclude={'number','title'}))
    db.add(requirement)
    db.flush()
    audit(db,user,'requirement.create',requirement.id)

    if data.create_clarification:
        fields={'需求编号':number,'需求名称':title}
        task=ClarificationTask(owner_id=user.id,requirement_id=requirement.id,fields=fields,status='pending')
        db.add(task)
        db.flush()
        db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields=fields,revision=task.revision))

    if data.initialize_tasks:
        initialize(db,user,requirement.id,InitializeInput(source_version_id=details.source_version_id),commit=False)
    db.commit()
    return requirement_record(db,requirement)


@router.post('/requirements')
def requirement_create(data: RequirementInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..services.identity import check_identity
    write_lock(db)
    check_identity(db,user,data.number,data.tags)
    validate_requirement_state(db,user,data)
    if data.source_version_id:
        require_version(db,data.source_version_id,user)
    requirement=Requirement(owner_id=user.id,**data.model_dump())
    db.add(requirement)
    db.flush()
    audit(db,user,'requirement.create',requirement.id)
    db.commit()
    return requirement_record(db,requirement)


@router.patch('/requirements/{requirement_id}')
def requirement_edit(requirement_id: str,data: RequirementInput,expected_revision: int,user: User=Depends(current_user),db: Session=Depends(get_db)):
    write_lock(db)
    requirement=owned(db.get(Requirement,requirement_id),user)
    ensure_active(db,'requirement',requirement_id)
    if requirement.revision!=expected_revision:
        raise HTTPException(409,'需求已被修改')
    from ..services.identity import check_identity
    check_identity(db,user,data.number,data.tags,requirement.id)
    validate_requirement_state(db,user,data,requirement)
    if data.source_version_id:
        require_version(db,data.source_version_id,user)
    before=record(requirement)
    for k,v in data.model_dump().items():
        setattr(requirement,k,v)
    requirement.revision+=1
    audit(db,user,'requirement.edit',requirement.id,revision=requirement.revision,before=before,after=record(requirement))
    db.commit()
    return requirement_record(db,requirement)


@router.get('/work-items')
def pending_work(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return work_items(db,user)


@router.get('/requirements/{requirement_id}/workspace')
def workspace(requirement_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    from ..services.requirement_initialization import initialization_view
    requirement=db.get(Requirement,requirement_id)
    development=user.role==DEVELOPMENT_MEMBER
    readonly=development or (user.role=='super_admin' and requirement is not None and requirement.owner_id!=user.id)
    if readonly:
        if not db.scalar(select(Requirement.id).where(Requirement.id==requirement_id,readable_requirements(user))):
            raise HTTPException(404,'业务需求不存在或未授权')
    else:
        requirement=owned(requirement,user)
        ensure_active(db,'requirement',requirement_id)
        legacy=db.scalar(select(ProcessingTaskContext).where(ProcessingTaskContext.legacy_requirement_id==requirement_id,ProcessingTaskContext.legacy_hidden.is_(True)))
        if legacy:return {'redirect_task_id':legacy.run_id}
    children=[]
    for context in db.scalars(select(RequirementContext).where(RequirementContext.parent_id==requirement.id)).all():
        child=db.get(Requirement,context.requirement_id)
        if child and db.scalar(select(Requirement.id).where(Requirement.id==child.id,readable_requirements(user))): children.append(requirement_record(db,child))
    runs=[task_record(db,run,user) for run in db.scalars(readable_tasks(user,requirement.id).order_by(AgentRun.created_at.desc())).all()]
    assets={};origins={};roles={};task_assets={}
    for run_record in runs:
        run=db.get(AgentRun,run_record['id'])
        task_assets[run.id]=task_documents(db,run,user)
        for item in task_assets[run.id]:
            did=item['document']['id'];assets[did]=db.get(Document,did)
            origins.setdefault(did,set()).add(run.id);roles.setdefault(did,set()).add(item['role'])
    for doc in db.scalars(select(Document).where(active_filter('document',Document.id),Document.requirement_id==requirement.id)).all():
        assets[doc.id]=doc;roles.setdefault(doc.id,set()).add('direct')
    source=None
    if requirement.source_version_id:
        version=db.get(DocumentVersion,requirement.source_version_id) if readonly else require_version(db,requirement.source_version_id,user)
        if version and (not readonly or (can_version(db,version,user) and not is_deleted(db,'document',version.document_id))):
            doc=db.get(Document,version.document_id)
            source={**record(version,('content','blocks')),'title':doc.title}
            if not is_deleted(db,'document',doc.id):assets[doc.id]=doc;roles.setdefault(doc.id,set()).add('input')
    documents=[]
    for doc in assets.values():
        visible=[record(v,('content','blocks')) for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id).order_by(DocumentVersion.created_at.desc())).all() if can_version(db,v,user)]
        if visible:documents.append({**record(doc),'versions':visible,'task_ids':sorted(origins.get(doc.id,set())),'roles':sorted(roles.get(doc.id,set()))})
    specs=[(doc,v) for doc in documents if doc['kind']=='specification' and ('direct' in doc['roles'] or 'output' in doc['roles']) for v in doc['versions']]
    latest=max(specs,key=lambda pair:pair[1]['created_at']) if specs else None
    if latest: code,label,action=version_stage(db.get(DocumentVersion,latest[1]['id']))
    else: code,label,action='registered','需求已登记','查看关联任务或准备资料'
    versions={v['id'] for doc in documents for v in doc['versions']}
    review_query=select(ReviewRequest).where(ReviewRequest.version_id.in_(versions)).order_by(ReviewRequest.created_at.desc())
    if user.role!='super_admin' or not readonly:
        review_query=review_query.where(ReviewRequest.submitter_id==user.id)
    reviews=[] if development else [record(review) for review in db.scalars(review_query)]
    question_owner=requirement.owner_id if readonly else user.id
    questions=db.scalars(select(Question).where(active_filter('question',Question.id),Question.requirement_id==requirement.id,Question.owner_id==question_owner)).all()
    summary={**requirement_record(db,requirement),'can_edit':not readonly}
    if readonly and not source: summary['source_version_id']=None
    question_records = [record(q) for q in questions]
    packs = workspace_packs(db,user,requirement,runs,task_assets,documents,reviews,question_records,children,readonly) if summary['kind']=='business' else []
    if development:
        for question in question_records:
            question.pop('evidence',None)
    return {'requirement':summary,'children':children,'source':source,'documents':documents,'runs':runs,'reviews':reviews,'questions':question_records,'packs':packs,'stage':{'code':code,'label':label,'next_action':action},'unresolved_questions':sum(q.status in ('open','answered') for q in questions),'latest_specification':latest[1] if latest else None,'needs_revision':bool(latest and any(conclusion_changed_after(q,db.get(DocumentVersion,latest[1]['id'])) for q in questions)), 'task_initialization':None if readonly else initialization_view(db,user,requirement,runs)}


@router.post('/requirements/{requirement_id}/metrics')
def metrics(requirement_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    r=owned(db.get(Requirement,requirement_id),user)
    ensure_active(db,'requirement',requirement_id)
    setting=db.scalar(select(Setting).where(Setting.key=='scoring'))
    rule=setting.value if setting else {'version':'1','interface_weight':2,'rule_weight':2,'module_weight':1}
    checks={'背景描述':bool(r.description.strip()),'验收标准':bool(r.acceptance.strip()),'业务领域':bool(r.tags.get('业务领域')),'系统':bool(r.tags.get('系统')),'模块':bool(r.tags.get('模块')),'来源':bool(r.source_version_id),'类型':bool(r.tags.get('需求类型'))}
    pending=db.scalars(select(Question).where(active_filter('question',Question.id),Question.requirement_id==r.id,Question.status.in_(['open','answered']))).all()
    interfaces=len(r.tags.get('数据接口',[]))
    rules=len(r.tags.get('业务规则',[]))
    modules=len(r.tags.get('模块',[]))
    complexity=interfaces*float(rule['interface_weight'])+rules*float(rule['rule_weight'])+modules*float(rule['module_weight'])
    relations=db.scalars(select(Relation).where(active_filter('relation',Relation.id),(Relation.source_id==r.id)|(Relation.target_id==r.id),Relation.owner_id==user.id,Relation.status=='confirmed')).all()
    values={'完整度':round(sum(checks.values())/len(checks)*100),'复杂度分数':complexity,'复杂度':'低' if complexity<4 else '中' if complexity<9 else '高','待确认问题':len(pending),'接口变更':interfaces,'规则变更':rules,'影响模块':modules,'已确认关联':len(relations)}
    metric=Metric(requirement_id=r.id,method_version=str(rule['version']),values=values,explanation={'checks':checks,'rule':rule,'requirement_revision':r.revision,'inputs':r.tags})
    db.add(metric)
    db.commit()
    return record(metric)


@router.get('/requirements/{requirement_id}/lineage')
def lineage(requirement_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    requirement=owned(db.get(Requirement,requirement_id),user)
    ensure_active(db,'requirement',requirement_id)
    source=require_version(db,requirement.source_version_id,user) if requirement.source_version_id else None
    documents=[]
    for document in db.scalars(select(Document).where(active_filter('document',Document.id),Document.requirement_id==requirement.id)).all():
        versions=[record(v,('content','blocks')) for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document.id)).all() if can_version(db,v,user)]
        if versions:
            documents.append({**record(document),'versions':versions})
    return {'requirement':record(requirement),'business_source':record(source,('content','blocks')) if source else None,'clarifications':[record(q) for q in db.scalars(select(Question).where(active_filter('question',Question.id),Question.requirement_id==requirement.id,Question.owner_id==user.id)).all()],'documents':documents,'agent_runs':[record(run,('result',)) for run in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id))).all() if linked_id(db,run)==requirement.id]}


@router.get('/requirements/{requirement_id}/metrics')
def metric_history(requirement_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    owned(db.get(Requirement,requirement_id),user)
    return [record(m) for m in db.scalars(select(Metric).where(Metric.requirement_id==requirement_id).order_by(Metric.created_at.desc())).all()]


@router.get('/relations')
def relations(requirement_id:str|None=None,pack_id:str|None=None,user: User=Depends(current_user),db: Session=Depends(get_db)):
    query=select(Relation).where(active_filter('relation',Relation.id),Relation.source_id.in_(select(Requirement.id).where(requirement_filter())),Relation.target_id.in_(select(Requirement.id).where(requirement_filter())))
    if pack_id:
        if not db.scalar(select(Requirement.id).where(Requirement.id==requirement_id,readable_requirements(user))):
            raise HTTPException(404,'业务需求不存在或无权限')
        pack_for(db,requirement_id,pack_id)
        query=query.where((Relation.source_id==requirement_id)|(Relation.target_id==requirement_id))
    if user.role!=DEVELOPMENT_MEMBER:
        query=query.where(Relation.owner_id==user.id)
    result=[]
    for relation in db.scalars(query):
        if pack_id:
            run_id=relation.evidence.get('agent_run_id')
            origin=db.get(AgentRun,run_id) if run_id else None
            home=origin.inputs.get('_requirement_pack_id') if origin and relation.source_id==requirement_id else None
            if (home or requirement_id)!=pack_id:
                continue
        if user.role!=DEVELOPMENT_MEMBER:
            result.append(record(relation))
            continue
        candidate=relation.evidence.get('candidate')
        description=relation.evidence.get('description') or (candidate.get('description') if isinstance(candidate,dict) else '')
        result.append({**record(relation,('evidence',)),'evidence':{'description':str(description or '')}})
    return result


@router.post('/relations')
def relation_create(data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    a=owned(db.get(Requirement,data.get('source_id')),user)
    b=owned(db.get(Requirement,data.get('target_id')),user)
    ensure_active(db,'requirement',a.id)
    ensure_active(db,'requirement',b.id)
    if a.id==b.id:
        raise HTTPException(422,'不能关联自身')
    if not data.get('evidence'):
        raise HTTPException(422,'必须提供来源证据')
    relation=Relation(source_id=a.id,target_id=b.id,owner_id=user.id,kind=str(data.get('kind','语义相似')),evidence=data['evidence'],status='candidate')
    db.add(relation)
    db.commit()
    return record(relation)


@router.patch('/relations/{relation_id}')
def relation_decide(relation_id: str,data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    relation=owned(db.get(Relation,relation_id),user)
    ensure_active(db,'relation',relation_id)
    if data.get('status') not in ('confirmed','rejected'):
        raise HTTPException(422,'只能确认或拒绝候选关联')
    relation.status=data['status']
    audit(db,user,'relation.decide',relation.id,status=relation.status)
    db.commit()
    return record(relation)


@router.get('/clarification/tasks')
def tasks(q: str='',status: str='',user: User=Depends(current_user),db: Session=Depends(get_db)):
    rows=db.scalars(select(ClarificationTask).where(active_filter('clarification_task',ClarificationTask.id)).order_by(ClarificationTask.created_at.desc(),ClarificationTask.id)).all()
    people={u.id:u.display_name for u in db.scalars(select(User)).all()}
    accessible=set(db.scalars(select(Requirement.id).where(readable_requirements(user))).all())
    return [{**record(t),'owner_name':people.get(t.owner_id,'登记人'),'can_edit':t.owner_id==user.id,
             'can_delete':t.owner_id==user.id or user.role=='super_admin','can_open_requirement':t.requirement_id in accessible}
            for t in rows if (not status or t.status==status) and (not q or q.lower() in str(t.fields).lower())]


def validate_task_links(db,user,data,existing=None):
    if data.requirement_id:
        owned(db.get(Requirement,data.requirement_id),user)
        if not existing or existing.requirement_id!=data.requirement_id:
            ensure_active(db,'requirement',data.requirement_id)


@router.post('/clarification/tasks')
def task_create(data: TaskInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    lock_ledger(db,user)
    validate_task_links(db,user,data)
    task=ClarificationTask(owner_id=user.id,**data.model_dump(exclude={'expected_revision'}))
    db.add(task)
    db.flush()
    number=task.fields.get('需求编号')
    if not task.requirement_id and number is not None and str(number).strip():
        from ..services.identity import business_requirements_by_number, ledger_requirement
        matches=business_requirements_by_number(db,user,number)
        if len(matches)==1:
            task.requirement_id=matches[0].id
            audit(db,user,'ledger.link_requirement',task.id,requirement_id=task.requirement_id,mode='number_match')
        elif not matches and user.role=='qa_member':
            requirement=ledger_requirement(db,user,task.fields)
            if requirement:
                task.requirement_id=requirement.id
                audit(db,user,'requirement.create_from_qa_ledger',requirement.id,task_id=task.id)
    db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields=task.fields,revision=task.revision))
    db.commit()
    return record(task)


@router.patch('/clarification/tasks/{task_id}')
def task_edit(task_id: str,data: TaskInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    lock_ledger(db,user)
    task=owned(db.get(ClarificationTask,task_id),user)
    ensure_active(db,'clarification_task',task_id)
    if task.revision!=data.expected_revision:
        raise HTTPException(409,'台账已经修改，请刷新')
    validate_task_links(db,user,data,task)
    task.fields=data.fields
    task.status=data.status
    task.requirement_id=data.requirement_id
    task.revision+=1
    db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields=task.fields,revision=task.revision))
    db.commit()
    return record(task)


@router.get('/clarification/tasks/{task_id}/history')
def task_history(task_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    task=db.get(ClarificationTask,task_id)
    if not task or is_deleted(db,'clarification_task',task_id) and task.owner_id!=user.id and user.role!='super_admin':
        raise HTTPException(404,'台账不存在')
    return [record(t) for t in db.scalars(select(TaskHistory).where(TaskHistory.task_id==task_id).order_by(TaskHistory.revision,TaskHistory.created_at)).all()]


@router.post('/clarification/batch')
def batch_tasks(data: dict,user: User=Depends(current_user),db: Session=Depends(get_db)):
    lock_ledger(db,user)
    changes=data.get('items',[])
    if not isinstance(changes,list) or not 1<=len(changes)<=500:
        raise HTTPException(422,'批量操作限1至500条')
    rows=[]
    for change in changes:
        task=owned(db.get(ClarificationTask,change.get('id')),user)
        ensure_active(db,'clarification_task',task.id)
        if task.revision!=change.get('expected_revision'):
            raise HTTPException(409,'部分台账已修改；本次批量更新未应用')
        if change.get('status') not in ('pending','in_progress','completed','not_needed'):
            raise HTTPException(422,'状态无效')
        rows.append((task,change['status']))
    for task,status in rows:
        task.status=status
        task.revision+=1
        db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields={**task.fields,'_normalized_status':status},revision=task.revision))
    audit(db,user,'ledger.batch',user.id,task_ids=[t.id for t,_ in rows])
    db.commit()
    return {'updated':len(rows)}


async def read_ledger_upload(file: UploadFile):
    data=await file.read(settings.upload_limit_mb*1024*1024+1)
    name=validate(data,file.filename or '')
    if not name.lower().endswith('.xlsx'):
        raise HTTPException(422,'台账导入需要 XLSX')
    return data, name


@router.post('/clarification/import-preview')
async def preview_excel(file: UploadFile=File(),user: User=Depends(current_user),db: Session=Depends(get_db)):
    data, _ = await read_ledger_upload(file)
    return preview_ledger(db,user,data)


@router.post('/clarification/import')
async def import_excel(file: UploadFile=File(),expected_snapshot: str | None=Form(None),user: User=Depends(current_user),db: Session=Depends(get_db)):
    data, name = await read_ledger_upload(file)
    return import_ledger(db,user,data,expected_snapshot,name)


@router.get('/clarification/imports')
def import_batches(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return ledger_import_batches(db,user)


@router.post('/clarification/imports/{batch_id}/undo')
def undo_import(batch_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    return undo_ledger_import(db,user,batch_id)


@router.get('/clarification/export')
def export_excel(user: User=Depends(current_user),db: Session=Depends(get_db)):
    rows=db.scalars(select(ClarificationTask).where(active_filter('clarification_task',ClarificationTask.id)).order_by(ClarificationTask.created_at.desc(),ClarificationTask.id)).all()
    return Response(export_ledger(rows,public_ledger_columns(db)),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="clarification-ledger.xlsx"'})


@router.get('/clarification/columns')
def columns(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return {'columns':public_ledger_columns(db),'own_columns':ledger_columns(db,user),'visibility':'public'}


@router.get('/clarification/stats')
def task_stats(user: User=Depends(current_user),db: Session=Depends(get_db)):
    rows=tasks(user=user,db=db)
    return {'states':dict(Counter(t['status'] for t in rows)),'total':len(rows)}


@router.get('/clarification/questions')
def questions(user: User=Depends(current_user),db: Session=Depends(get_db)):
    return [record(q) for q in db.scalars(select(Question).where(Question.owner_id==user.id,active_filter('question',Question.id))).all()]


def question_links(db,user,data,existing=None):
    if pack_id:=data.evidence.get('requirement_pack_id'):
        if not data.requirement_id or not isinstance(pack_id,str):
            raise HTTPException(422,'请选择需求包所属业务需求')
        pack_for(db,data.requirement_id,pack_id)
    if data.task_id:
        owned(db.get(ClarificationTask,data.task_id),user)
        ensure_active(db,'clarification_task',data.task_id)
    if data.requirement_id:
        owned(db.get(Requirement,data.requirement_id),user)
        if not existing or existing.requirement_id!=data.requirement_id:
            ensure_active(db,'requirement',data.requirement_id)
    if data.status=='confirmed' and not data.conclusion.strip():
        raise HTTPException(422,'确认问题必须填写结论')


@router.post('/clarification/questions')
def question_create(data: QuestionInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if data.task_id:
        lock_ledger(db,user)
    question_links(db,user,data)
    question=Question(owner_id=user.id,**data.model_dump())
    db.add(question)
    db.commit()
    return record(question)


@router.patch('/clarification/questions/{question_id}')
def question_edit(question_id: str,data: QuestionInput,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if data.task_id:
        lock_ledger(db,user)
    question=owned(db.get(Question,question_id),user)
    ensure_active(db,'question',question_id)
    question_links(db,user,data,question)
    before=record(question)
    if data.status=='confirmed' and (question.status!='confirmed' or data.conclusion!=question.conclusion):
        from ..models import now
        data.evidence={**data.evidence,'conclusion_confirmed_at':now().isoformat()}
    for k,v in data.model_dump().items():
        setattr(question,k,v)
    audit(db,user,'question.edit',question.id,before=before,after=data.model_dump())
    db.commit()
    return record(question)
