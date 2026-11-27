from fastapi import HTTPException
from sqlalchemy import select
from ..models import DeletedRecord, Requirement, RequirementContext, ClarificationTask, Question, Relation, Document, DocumentVersion, AgentRun, Skill, KnowledgeItem, Outbox, ReviewRequest,ProcessingTaskContext,DocumentWorkspace,ModelConfig
from ..security import audit, write_lock

MODELS={'requirement':Requirement,'clarification_task':ClarificationTask,'question':Question,'relation':Relation,'document':Document,'agent_run':AgentRun,'skill':Skill,'knowledge_item':KnowledgeItem,'model_config':ModelConfig}


def active_filter(kind,column):
    return ~column.in_(select(DeletedRecord.resource_id).where(DeletedRecord.resource_type==kind))


def requirement_filter():
    hidden=select(DeletedRecord.resource_id).where(DeletedRecord.resource_type=='requirement')
    children=select(RequirementContext.requirement_id).where(RequirementContext.parent_id.in_(hidden))
    legacy=select(ProcessingTaskContext.legacy_requirement_id).where(ProcessingTaskContext.legacy_hidden.is_(True),ProcessingTaskContext.legacy_requirement_id.is_not(None))
    return active_filter('requirement',Requirement.id) & ~Requirement.id.in_(children) & ~Requirement.id.in_(legacy)


def deleted_ids(db,kind):
    return set(db.scalars(select(DeletedRecord.resource_id).where(DeletedRecord.resource_type==kind)).all())


def is_deleted(db,kind,resource_id):
    return bool(db.scalar(select(DeletedRecord.id).where(DeletedRecord.resource_type==kind,DeletedRecord.resource_id==resource_id)))


def ensure_active(db,kind,resource_id):
    if is_deleted(db,kind,resource_id): raise HTTPException(409,'该记录已删除，历史内容仅用于追溯，不能继续修改或执行')
    if kind=='requirement':
        context=db.scalar(select(RequirementContext).where(RequirementContext.requirement_id==resource_id))
        if context and context.parent_id and is_deleted(db,'requirement',context.parent_id):
            raise HTTPException(409,'所属需求已删除，当前明细仅保留历史记录')


def delete_record(db,user,kind,resource_id,reason='用户删除'):
    model=MODELS.get(kind)
    if not model: raise HTTPException(422,'不支持删除此类记录')
    if kind=='model_config' and user.role!='super_admin':
        raise HTTPException(403,'需要管理员权限')
    write_lock(db)
    # Share the ledger owner lock with import/edit so replacement snapshots remain valid.
    if kind=='clarification_task':
        from ..models import User
        task=db.get(ClarificationTask,resource_id)
        if not task or task.owner_id!=user.id and user.role!='super_admin': raise HTTPException(404,'记录不存在或未授权')
        db.scalar(select(User).where(User.id==task.owner_id).with_for_update())
    obj=db.scalar(select(model).where(model.id==resource_id).with_for_update())
    if not obj: raise HTTPException(404,'记录不存在')
    owner=getattr(obj,'owner_id',None)
    if kind=='knowledge_item' or kind=='skill' and obj.public:
        if user.role!='super_admin': raise HTTPException(403,'公共资产由管理员删除')
    elif owner!=user.id and user.role!='super_admin':
        raise HTTPException(404,'记录不存在或未授权')
    if is_deleted(db,kind,resource_id): return {'deleted':True,'already_deleted':True,'mode':'logical'}
    if kind=='requirement':
        children=list(db.scalars(select(RequirementContext.requirement_id).where(RequirementContext.parent_id==obj.id)).all())
        ids=[obj.id,*children]
        for run in db.scalars(select(AgentRun).where(AgentRun.status.in_(['pending','running']),active_filter('agent_run',AgentRun.id))).all():
            from .processing_tasks import linked_id
            if linked_id(db,run) in ids: raise HTTPException(409,'需求还有进行中的生成任务，请先完成或删除执行任务')
        active_review=db.scalar(select(ReviewRequest.id).join(DocumentVersion,ReviewRequest.version_id==DocumentVersion.id).join(Document,DocumentVersion.document_id==Document.id).where(Document.requirement_id.in_(ids),ReviewRequest.status.in_(['pending','in_review'])))
        if active_review: raise HTTPException(409,'需求文档正在会签，完成本轮审核后可删除')
        for context in db.scalars(select(ProcessingTaskContext).where(ProcessingTaskContext.requirement_id.in_(ids)).with_for_update()).all():
            context.requirement_id=None;context.revision+=1
        for workspace in db.scalars(select(DocumentWorkspace).where(DocumentWorkspace.requirement_id.in_(ids),DocumentWorkspace.run_id.is_not(None)).with_for_update()).all():
            workspace.requirement_id=None;workspace.revision+=1
    elif kind=='clarification_task':
        for question in db.scalars(select(Question).where(Question.task_id==obj.id,Question.owner_id==obj.owner_id).with_for_update()).all():
            question.evidence={**question.evidence,'previous_task_id':obj.id,'task_detached_reason':'task_deleted'}
            question.task_id=None
    elif kind=='agent_run':
        job=db.scalar(select(Outbox).where(Outbox.kind=='agent',Outbox.resource_id==obj.id).with_for_update())
        if obj.status=='running' or job and job.status=='running': raise HTTPException(409,'任务正在执行，请等待完成后删除')
        if obj.status in ('pending','awaiting_confirmation','failed'): obj.status='cancelled'
        if job and job.status in ('pending','failed'):
            job.status='cancelled';job.lease_token=None;job.error='用户已删除任务'
    elif kind=='document':
        versions=db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==obj.id).with_for_update()).all()
        if any(v.review_status in ('pending','in_review') for v in versions): raise HTTPException(409,'文档正在会签，暂不能删除；请先完成本轮审核')
        governed=any(v.publish_status=='published' or v.review_status=='approved' for v in versions)
        if governed and user.role!='super_admin': raise HTTPException(403,'已通过审核或发布的文档由管理员治理删除')
        ids=[v.id for v in versions]
        jobs=db.scalars(select(Outbox).where(Outbox.resource_id.in_(ids)).with_for_update()).all() if ids else []
        if any(job.status=='running' for job in jobs): raise HTTPException(409,'文档正在解析或发布，请等待任务结束后删除')
        for job in jobs:
            if job.status in ('pending','failed'): job.status='cancelled';job.lease_token=None
        if governed:
            obj.current_version_id=None;obj.current_index_id=None
            for version in versions:
                if version.status in ('approved','published'): version.status='archived'
    elif kind=='skill': obj.enabled=False
    elif kind=='knowledge_item': obj.deprecated=True
    elif kind=='model_config':
        obj.enabled=False
        obj.encrypted_key=''
    db.add(DeletedRecord(resource_type=kind,resource_id=resource_id,owner_id=owner,deleted_by=user.id,reason=reason))
    audit(db,user,'record.delete',resource_id,resource_type=kind,mode='logical',reason=reason)
    db.commit()
    return {'deleted':True,'mode':'logical'}
