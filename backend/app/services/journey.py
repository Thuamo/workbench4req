from sqlalchemy import select
from datetime import datetime
from ..models import RequirementContext, Document, DocumentVersion, AgentRun, SkillVersion, ReviewRequest, ReviewTask, Requirement, Notification, User, Question, DocumentWorkspace
from ..serialize import record
from ..security import can_version, owned
from .processing_tasks import linked_id,task_context
from .deletion import active_filter, is_deleted, requirement_filter


def context_for(db, requirement, kind=None, parent_id=None, run_id=None):
    context=db.scalar(select(RequirementContext).where(RequirementContext.requirement_id==requirement.id))
    if kind:
        if not context:
            context=RequirementContext(requirement_id=requirement.id,kind=kind)
            db.add(context)
        context.kind=kind
        context.parent_id=parent_id
        context.origin_run_id=run_id or context.origin_run_id
    return context


def requirement_record(db, requirement):
    context=context_for(db,requirement)
    return {**record(requirement),'kind':context.kind if context else 'business','parent_id':context.parent_id if context else None,'deleted':is_deleted(db,'requirement',requirement.id)}


def version_stage(version):
    if version.parse_status=='failed': return ('parse_failed','资料解析失败','重试解析')
    if version.parse_status!='ready': return ('parsing','资料解析中','等待解析')
    if version.status=='published': return ('published','已正式发布','查看正式版本')
    if version.status=='returned' or version.review_status=='returned': return ('returned','审核退回','查看意见并创建修订')
    if version.status in ('pending_review','in_review'): return ('reviewing','会签审核中','查看会签进度')
    if version.review_status=='approved':
        if version.index_status=='failed' or version.publish_status=='failed': return ('publish_failed','发布失败','查看错误并重试')
        return ('publishing','会签通过 · 发布处理中','查看发布进度')
    if version.status in ('deprecated','archived','superseded'): return ('historical','历史版本','查看版本记录')
    return ('version_confirmed','版本已确认 · 未提交审核','提交会签')


def run_stage(run,workflow='specification',db=None):
    if db:
        from .ledger_fill import workflow as selected_workflow
        workflow=selected_workflow(db.get(SkillVersion,run.skill_version_id).config)
    if workflow=='ledger_fill' and run.status=='completed':
        return ('completed','已确认入表','查看澄清计划') if run.result.get('saved_ledger_task_id') else ('analysis_ready','填报内容待确认','核对24列并确认入表')
    if run.status=='awaiting_confirmation': return ('outline','等待确认提纲','确认提纲')
    if run.status=='failed': return ('generation_failed','生成失败','查看错误并重试')
    change_mode=run.inputs.get('_specification_change_mode')
    if run.status in ('pending','running'):
        label='局部变更建议生成中' if change_mode=='partial' else '文档生成中' if workflow=='specification' else '技能执行中'
        return ('generating',label,'查看执行进度')
    if change_mode=='partial' and not run.result.get('local_change_application'):
        return ('local_change_ready','局部变更建议待核对','核对变更建议')
    if workflow=='uml': return ('completed','UML 任务已完成','查看图稿')
    if workflow=='mind_map': return ('completed','思维导图已生成','查看导图')
    if workflow=='ppt_report': return ('completed','一页汇报 PPT 已生成','查看汇报')
    if workflow!='specification': return ('analysis_ready','分析已完成 · 待处理候选','处理分析候选')
    if db:
        workspace=db.scalar(select(DocumentWorkspace).where(DocumentWorkspace.run_id==run.id,DocumentWorkspace.owner_id==run.owner_id))
        if workspace and workspace.content_json and workspace.confirmed_revision!=workspace.revision:
            return ('editing','编辑中 · 工作草稿已保存','继续编辑')
    if run.result.get('editor_draft'): return ('editing','编辑中 · 有已保存进度','继续编辑')
    if run.result.get('saved_version_id'): return ('version_confirmed','版本已确认','查看需求')
    if change_mode in ('manual','partial'): return ('editing','工作草稿已创建','继续编辑')
    return ('document_ready','正文已生成 · 待编辑确认','继续编辑')


def conclusion_changed_after(question,version):
    if question.status!='confirmed': return False
    stamp=question.evidence.get('conclusion_confirmed_at')
    try:
        confirmed=datetime.fromisoformat(stamp).replace(tzinfo=None) if stamp else question.created_at
        return confirmed>version.created_at
    except (TypeError,ValueError): return False


def destination_for(db,user,resource_id):
    run=db.get(AgentRun,resource_id)
    if run and run.owner_id==user.id and not is_deleted(db,'agent_run',run.id): return {'page':'task','id':run.id}
    requirement=db.get(Requirement,resource_id)
    if requirement and requirement.owner_id==user.id and not is_deleted(db,'requirement',requirement.id): return {'page':'requirement','id':requirement.id}
    review=db.get(ReviewRequest,resource_id)
    if review:
        assigned=db.scalar(select(ReviewTask.id).where(ReviewTask.request_id==review.id,ReviewTask.reviewer_id==user.id))
        if assigned or review.submitter_id==user.id or user.role=='super_admin': return {'page':'reviews','id':review.id}
    version=db.get(DocumentVersion,resource_id)
    if version and can_version(db,version,user): return {'page':'document','id':version.id,'document_id':version.document_id}
    document=db.get(Document,resource_id)
    if document:
        versions=db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document.id).order_by(DocumentVersion.created_at.desc())).all()
        version=next((v for v in versions if can_version(db,v,user)),None)
        if version: return {'page':'document','id':version.id,'document_id':document.id}
    return None


def work_items(db,user):
    from ..models import RequirementPackSpecification
    from .requirement_packs import run_pack_id
    items=[]
    for run in db.scalars(select(AgentRun).where(AgentRun.owner_id==user.id,active_filter('agent_run',AgentRun.id)).order_by(AgentRun.created_at.desc())).all():
        rid=linked_id(db,run)
        if rid and not db.scalar(select(Requirement.id).where(Requirement.id==rid,requirement_filter())): continue
        if rid and is_deleted(db,'requirement_pack',run_pack_id(rid,run.inputs)): continue
        saved=db.get(DocumentVersion,run.result.get('saved_version_id')) if run.result.get('saved_version_id') else None
        if saved and is_deleted(db,'document',saved.document_id): continue
        workflow=db.get(SkillVersion,run.skill_version_id).config.get('workflow','qa')
        if workflow=='qa': continue
        if workflow=='ledger_fill' and run.result.get('saved_ledger_task_id'):continue
        destination={'page':'task','id':run.id}
        workspace=db.scalar(select(DocumentWorkspace).where(DocumentWorkspace.run_id==run.id,DocumentWorkspace.owner_id==user.id))
        has_draft=bool(workspace and workspace.content_json and workspace.confirmed_revision!=workspace.revision)
        if run.status=='completed' and run.result.get('saved_analysis_confirmed') and workflow not in ('specification','ledger_fill'):continue
        # Once a version exists, its edit/review/publication entry is the next
        # business action. Keep the run available through task detail, not twice here.
        if run.status=='completed' and workflow=='specification' and saved and not has_draft and not run.result.get('editor_draft'):continue
        if run.status=='completed' and not has_draft and not run.result.get('editor_draft') and (run.result.get('saved_version_id') or workflow!='specification'):
            pending=any(i not in run.result.get('saved_requirement_indices',[]) for i,_ in enumerate(run.result.get('analysis',{}).get('items',[]))) or any(i not in run.result.get('saved_question_indices',[]) for i,_ in enumerate(run.result.get('clarification',{}).get('questions',[]))) or any(not any(key.startswith(str(i)+':') for key in run.result.get('saved_relation_keys',[])) for i,_ in enumerate(run.result.get('impact',{}).get('relations',[])))
            if not pending and workflow in ('specification','ledger_fill'): continue
            code,label,action='analysis_ready','分析已完成 · 待处理候选','处理分析候选'
            if rid: destination={'page':'requirement','id':rid}
        else:
            code,label,action=run_stage(run,workflow,db)
            if run.status=='completed' and workflow=='specification' and code!='local_change_ready': destination={'page':'editor','id':'run~'+run.id}
        items.append({'id':'run:'+run.id,'title':str(run.inputs.get('task','生成任务'))[:300],'stage':code,'label':label,'action':action,'created_at':run.created_at.isoformat(),'destination':destination,'requirement_id':rid})
    for doc in db.scalars(select(Document).where(active_filter('document',Document.id),Document.owner_id==user.id,Document.kind=='specification')).all():
        home=db.scalar(select(RequirementPackSpecification.pack_id).where(RequirementPackSpecification.document_id==doc.id))
        if doc.requirement_id and is_deleted(db,'requirement_pack',home or doc.requirement_id): continue
        version=next((v for v in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==doc.id).order_by(DocumentVersion.created_at.desc())).all() if can_version(db,v,user)),None)
        if not version: continue
        code,label,action=version_stage(version)
        workspace=db.scalar(select(DocumentWorkspace).where(DocumentWorkspace.document_id==doc.id,DocumentWorkspace.owner_id==user.id))
        destination={'page':'document','id':version.id,'document_id':doc.id}
        if workspace and workspace.content_json and workspace.confirmed_revision!=workspace.revision:
            code,label,action='editing','编辑中 · 工作草稿已保存','继续编辑'
            destination={'page':'editor','id':'version~'+version.id}
        if code in ('published','historical'): continue
        items.append({'id':'version:'+version.id,'title':doc.title,'stage':code,'label':label,'action':action,'created_at':version.created_at.isoformat(),'destination':destination,'requirement_id':doc.requirement_id})
    for task in db.scalars(select(ReviewTask).where(ReviewTask.reviewer_id==user.id,ReviewTask.decision=='pending')).all():
        review=db.get(ReviewRequest,task.request_id)
        if not review or review.status not in ('pending','in_review'): continue
        version=db.get(DocumentVersion,review.version_id)
        doc=db.get(Document,version.document_id)
        items.append({'id':'review:'+review.id,'title':doc.title,'stage':'review_todo','label':'待我审核','action':'查看并审核','created_at':review.created_at.isoformat(),'destination':{'page':'reviews','id':review.id},'requirement_id':None})
    for question in db.scalars(select(Question).where(active_filter('question',Question.id),Question.owner_id==user.id,Question.status.in_(['open','answered']))).all():
        origin=db.get(AgentRun,question.evidence.get('agent_run_id')) if question.evidence.get('agent_run_id') else None
        pack_id=question.evidence.get('requirement_pack_id') or run_pack_id(question.requirement_id,origin.inputs if origin else {})
        if pack_id and is_deleted(db,'requirement_pack',pack_id): continue
        items.append({'id':'question:'+question.id,'title':question.description[:300],'stage':'clarification','label':'澄清待反馈' if question.status=='open' else '反馈已填写 · 待确认结论','action':'处理澄清问题','created_at':question.created_at.isoformat(),'destination':{'page':'requirement','id':question.requirement_id} if question.requirement_id else {'page':'clarification','id':''},'requirement_id':question.requirement_id})
    if user.role=='super_admin':
        shown={item['destination'].get('id') for item in items if item['destination']['page']=='reviews'}
        for review in db.scalars(select(ReviewRequest).where(ReviewRequest.status.in_(['pending','in_review']))).all():
            if review.id in shown: continue
            version=db.get(DocumentVersion,review.version_id);doc=db.get(Document,version.document_id)
            items.append({'id':'review:'+review.id,'title':doc.title,'stage':'review_todo','label':'全部待审核 · 管理员可查看','action':'查看会签任务','created_at':review.created_at.isoformat(),'destination':{'page':'reviews','id':review.id},'requirement_id':None})
    return sorted(items,key=lambda item:item['created_at'],reverse=True)
