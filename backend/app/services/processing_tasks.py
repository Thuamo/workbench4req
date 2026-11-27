"""The task's current requirement is independent of its immutable execution input."""
from fastapi import HTTPException
from sqlalchemy import case, or_, select
from ..models import DEVELOPMENT_MEMBER,ProcessingTaskContext as Context,TaskDocument,AgentRun,Requirement,RequirementContext,Document,DocumentVersion,DocumentWorkspace,Question,Relation,Skill,SkillVersion,Outbox
from ..security import owned,audit,can_version
from ..serialize import record
from .deletion import ensure_active,active_filter,requirement_filter,is_deleted


def task_context(db,run,create=False):
    context=db.scalar(select(Context).where(Context.run_id==run.id))
    if not context and create:
        rid=run.inputs.get('requirement_id')
        req=db.get(Requirement,rid) if rid else None
        context=Context(run_id=run.id,requirement_id=rid if req and req.owner_id==run.owner_id else None)
        db.add(context);db.flush()
    return context


def linked_id(db,run):
    context=task_context(db,run)
    return context.requirement_id if context else run.inputs.get('requirement_id')


def readable_requirements(user):
    scope=requirement_filter()
    return scope if user.role in (DEVELOPMENT_MEMBER,'super_admin') else scope & (Requirement.owner_id==user.id)


def readable_tasks(user,requirement_id=None,*,include_related=False):
    query=select(AgentRun).where(active_filter('agent_run',AgentRun.id))
    owned_run=AgentRun.owner_id==user.id
    related_access=user.role=='super_admin' and (include_related or requirement_id is not None)
    if user.role!=DEVELOPMENT_MEMBER and not related_access and requirement_id is None:
        return query.where(owned_run)
    linked=case((Context.run_id.is_not(None),Context.requirement_id),else_=AgentRun.inputs['requirement_id'].as_string())
    query=query.outerjoin(Context,Context.run_id==AgentRun.id)
    visible_link=linked.in_(select(Requirement.id).where(readable_requirements(user)))
    if user.role==DEVELOPMENT_MEMBER:
        query=query.where(visible_link)
    else:
        query=query.where(or_(owned_run,visible_link) if related_access else owned_run)
    if requirement_id is not None:
        query=query.where(linked==requirement_id)
    return query


def readonly_analysis(result):
    fields={
        'analysis': ('items', ('title','description','acceptance','tags')),
        'clarification': ('questions', ('description','category','reason','target')),
        'impact': ('relations', ('kind','description','system','module','function','process','flow','field','interface')),
    }
    analysis={}
    for kind,(collection,keys) in fields.items():
        report=result.get(kind)
        if not isinstance(report,dict):
            continue
        items=report.get(collection,[])
        analysis[kind]={collection:[{key:item[key] for key in keys if key in item} for item in items
                                    if isinstance(item,dict)] if isinstance(items,list) else []}
        if isinstance(report.get('answer'),str):
            analysis[kind]['answer']=report['answer']
    return analysis


def linked_requirement(db,run,user,required=False):
    rid=linked_id(db,run)
    if not rid:
        if required: raise HTTPException(409,'请先在任务详情关联业务需求，再确认结构化明细或澄清结果')
        return None
    requirement=owned(db.get(Requirement,rid),user);ensure_active(db,'requirement',rid)
    if not db.scalar(select(Requirement.id).where(Requirement.id==rid,requirement_filter())):
        raise HTTPException(409,'关联对象是历史任务占位记录，请在任务详情选择业务需求')
    return requirement


def link_document(db,run,version_id,role='output'):
    if not db.scalar(select(TaskDocument.id).where(TaskDocument.run_id==run.id,TaskDocument.version_id==version_id,TaskDocument.role==role)):
        db.add(TaskDocument(run_id=run.id,version_id=version_id,role=role))


def create_agent_run(db, user, skill_version, inputs, model_trace, *, status):
    if inputs.get('requirement_id'):
        from .requirement_packs import lock_active_run_pack
        lock_active_run_pack(db,inputs['requirement_id'],inputs)
    run=AgentRun(owner_id=user.id,skill_version_id=skill_version.id,
                 conversation_id=inputs.get('conversation_id'),inputs=inputs,status=status,
                 model_trace={**model_trace,'skill_version_id':skill_version.id})
    db.add(run)
    db.flush()
    task_context(db,run,True)
    for vid in inputs.get('source_version_ids',[]): link_document(db,run,vid,'input')
    for vid in inputs.get('sample_version_ids',[]): link_document(db,run,vid,'sample')
    if status=='pending':
        db.add(Outbox(kind='agent',resource_id=run.id))
    audit(db,user,'agent.start',run.id,skill_version_id=skill_version.id)
    return run


def queue_agent_run(db, user, skill_version, inputs, model_trace):
    return create_agent_run(db,user,skill_version,inputs,model_trace,status='pending')


def task_documents(db,run,user):
    links={(r.version_id,r.role) for r in db.scalars(select(TaskDocument).where(TaskDocument.run_id==run.id)).all()}
    links.update((vid,'input') for vid in run.inputs.get('source_version_ids',[]))
    links.update((vid,'sample') for vid in run.inputs.get('sample_version_ids',[]))
    if run.inputs.get('word_template_version_id'):links.add((run.inputs['word_template_version_id'],'template'))
    outputs=list(run.result.get('saved_version_ids',[]))
    if run.result.get('saved_version_id'):outputs.append(run.result['saved_version_id'])
    links.update((vid,'output') for vid in outputs)
    result=[]
    for vid,role in sorted(links):
        version=db.get(DocumentVersion,vid)
        if not version or not can_version(db,version,user):continue
        doc=db.get(Document,version.document_id)
        if is_deleted(db,'document',doc.id):continue
        result.append({'role':role,'document':record(doc),'version':record(version,('content','blocks'))})
    return result


def task_record(db,run,user,detail=False):
    from .journey import run_stage
    from .ledger_fill import workflow
    version=db.get(SkillVersion,run.skill_version_id);skill=db.get(Skill,version.skill_id)
    context=task_context(db,run);rid=linked_id(db,run);requirement=db.get(Requirement,rid) if rid else None
    if requirement and not db.scalar(select(Requirement.id).where(Requirement.id==rid,readable_requirements(user))): requirement=None
    selected_workflow=workflow(version.config)
    from .requirement_packs import run_pack_id, workflow_stage
    pack = {'pack_id':run_pack_id(rid,run.inputs),
            'pack_stage':run.inputs.get('_requirement_stage') or workflow_stage(selected_workflow)}
    code,label,action=run_stage(run,selected_workflow,db)
    if selected_workflow=='ledger_fill' and run.status=='completed':code,label,action=('completed','已确认入表','查看澄清计划') if run.result.get('saved_ledger_task_id') else ('analysis_ready','填报内容待确认','核对24列并确认入表')
    if version.config['workflow']=='qa' and run.status=='completed':code,label,action='completed','已完成','查看结果'
    if run.inputs.get('_initialization_run_id') and run.status=='completed':code,label,action='completed','质量核查已完成','查看核查结果'
    docs=task_documents(db,run,user)
    if run.result.get('saved_analysis_confirmed') and selected_workflow not in ('specification','ledger_fill'):code,label,action='completed','分析已确认','查看分析与来源'
    completed=code in ('completed','published','version_confirmed','historical')
    requirement_skill_task=bool(run.inputs.get('_requirement_skill_task'))
    if user.role==DEVELOPMENT_MEMBER or run.owner_id!=user.id:
        return {**record(run,('inputs','result','citations','model_trace','error','conversation_id')),**pack,
                'inputs':{'task':requirement.title if requirement else skill.name},
                'result':readonly_analysis(run.result) if detail else {},'citations':[],'model_trace':{},'error':'',
                'requirement_id':rid,'requirement':{'id':rid,'number':requirement.number,'title':requirement.title} if requirement else None,
                'workflow':selected_workflow,'skill_name':skill.name,'stage':code,'stage_label':label,'requirement_skill_task':requirement_skill_task,
                'read_only':True,
                'business_completed':completed,'output_count':len({d['document']['id'] for d in docs if d['role']=='output'}),
                **({'documents':docs} if detail else {})}
    if detail:
        from .identity import ledger_matches
        suggestions=[]
        if not rid:
            suggestions=ledger_matches(db,user,{'需求编号':run.inputs.get('task','')+' '+ ' '.join(d['document']['title']+' '+d['version']['filename'] for d in docs if d['role']=='input')})
        return {**task_record(db,run,user),'documents':docs,'requirement_candidates':suggestions}
    return {**record(run),**pack,'requirement_id':rid,'requirement':record(requirement) if requirement else None,'task_revision':context.revision if context else 1,'needs_review':bool(context and context.needs_review),'workflow':selected_workflow,'skill_name':skill.name,'requirement_skill_task':requirement_skill_task,'business_completed':completed,'stage':code,'stage_label':label,'next_action':action,'output_count':len({d['document']['id'] for d in docs if d['role']=='output'}),**({'documents':docs} if detail else {})}


def associate_task(db,run,user,requirement_id,expected_revision):
    context=task_context(db,run,True)
    if context.revision!=expected_revision:raise HTTPException(409,'任务关联已被其他页面修改，请刷新后重试')
    old=context.requirement_id
    if old!=requirement_id and (run.inputs.get('_requirement_pack_id') or run.inputs.get('_initialization_task') or run.inputs.get('_initialization') or run.inputs.get('_initialization_run_id')):
        raise HTTPException(409,'初始化任务已绑定需求和输入版本，请从目标需求发起新任务')
    requirement=None
    if requirement_id:
        requirement=owned(db.get(Requirement,requirement_id),user);ensure_active(db,'requirement',requirement_id)
        ensure_active(db,'requirement_pack',requirement_id)
        rc=db.scalar(select(RequirementContext).where(RequirementContext.requirement_id==requirement_id))
        if not db.scalar(select(Requirement.id).where(Requirement.id==requirement_id,requirement_filter())) or rc and rc.kind!='business':
            raise HTTPException(422,'请选择业务需求，不能关联临时占位记录或结构化明细')
    if old==requirement_id:return context
    if run.status in ('pending','running'):raise HTTPException(409,'任务正在排队或执行，请结束后再调整关联需求')
    docs=[d for d in task_documents(db,run,user) if d['role']=='output']
    if old:
        if any(d['version']['status']!='draft' or d['version']['review_status']!='not_submitted' for d in docs):
            raise HTTPException(409,'任务已有审核或历史版本，请新建关联任务，保留原需求与审核链路')
        if run.result.get('saved_requirement_indices') or run.result.get('saved_relation_keys'):
            raise HTTPException(409,'任务已有已确认明细或关联，请新建任务以保留历史归属')
        if any(q.status=='confirmed' and q.evidence.get('agent_run_id')==run.id for q in db.scalars(select(Question).where(Question.owner_id==user.id,Question.requirement_id==old)).all()):
            raise HTTPException(409,'任务已有人工确认的澄清结论，请新建关联任务')
    for document_id in {d['document']['id'] for d in docs}:
        doc=db.scalar(select(Document).where(Document.id==document_id).with_for_update())
        if doc.owner_id!=user.id:raise HTTPException(403,'任务输出文档未授权')
        if doc.requirement_id not in (None,old,context.legacy_requirement_id,requirement_id):
            raise HTTPException(409,'输出文档已属于其他需求，不能通过任务关联直接移动')
        versions=db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id)).all()
        other_runs=db.scalars(select(AgentRun).join(TaskDocument,TaskDocument.run_id==AgentRun.id).join(DocumentVersion,DocumentVersion.id==TaskDocument.version_id).where(DocumentVersion.document_id==doc.id,TaskDocument.role=='output',AgentRun.id!=run.id)).all()
        if any(linked_id(db,r) not in (None,requirement_id) for r in other_runs): raise HTTPException(409,'该文档由其他需求的任务共同使用，请先核对文档归属')
        if all(v.status=='draft' and v.review_status=='not_submitted' for v in versions): doc.requirement_id=requirement_id
    for w in db.scalars(select(DocumentWorkspace).where(DocumentWorkspace.run_id==run.id,DocumentWorkspace.owner_id==user.id).with_for_update()).all():
        confirmed=w.confirmed_revision==w.revision
        w.requirement_id=requirement_id;w.revision+=1
        if confirmed:w.confirmed_revision=w.revision
    for q in db.scalars(select(Question).where(Question.owner_id==user.id,Question.status!='confirmed')).all():
        if q.evidence.get('agent_run_id')==run.id and q.requirement_id in (old,None,context.legacy_requirement_id):q.requirement_id=requirement_id
    context.requirement_id=requirement_id;context.revision+=1;context.needs_review=False
    audit(db,user,'task.associate_requirement',run.id,before=old,after=requirement_id,revision=context.revision)
    return context
