from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import DEVELOPMENT_MEMBER,AgentRun,Requirement
from ..schemas import RequirementInput
from ..security import current_user,owned,write_lock,require_version,audit
from ..services.deletion import active_filter,ensure_active
from ..services.processing_tasks import task_record,associate_task,readable_tasks

router=APIRouter(tags=['处理任务'])

class Association(BaseModel):
    requirement_id:str|None=None
    expected_revision:int

class NewRequirement(BaseModel):
    expected_revision:int
    requirement:RequirementInput

class RepairInput(BaseModel):
    version_id:str

@router.post('/processing-tasks/{id}/repair-proposal')
def repair_proposal(id:str,data:RepairInput,user=Depends(current_user),db:Session=Depends(get_db)):
    from ..models import SkillVersion,Document
    run=owned(db.get(AgentRun,id),user);ensure_active(db,'agent_run',id)
    if run.status!='completed' or db.get(SkillVersion,run.skill_version_id).config['workflow']!='quality':raise HTTPException(409,'请先完成软需质量核查')
    if data.version_id not in run.inputs.get('source_version_ids',[]):raise HTTPException(422,'只能修复本次核查的输入版本')
    version=require_version(db,data.version_id,user);document=db.get(Document,version.document_id)
    if document.kind!='specification' or document.owner_id!=user.id:raise HTTPException(403,'只能为自己的软需文档生成修复提案')
    report=run.result.get('review',{}).get('answer','')
    if not report:raise HTTPException(409,'本次任务没有可用的质量报告')
    from .document_workspaces import open_workspace,OpenInput,assistant,AssistInput
    w=open_workspace(OpenInput(version_id=version.id),user,db)
    if w['content']!=version.content:raise HTTPException(409,'当前工作草稿已经变化，请先确认新版本并重新核查，旧质量报告不能用于自动生成当前稿的修复提案')
    result=assistant(w['id'],AssistInput(expected_revision=w['revision'],mode='modify',instruction='依据以下质量核查报告修复明确缺陷；无业务依据的规则标为待确认，保留其他内容。请生成修改提案供人工调整和确认。\n'+report[:2600]),user,db)
    return {'version_id':version.id,'workspace_id':w['id'],'proposal_id':result['proposal']['id']}

@router.post('/processing-tasks/{id}/confirm-analysis')
def confirm_analysis(id:str,user=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);run=owned(db.get(AgentRun,id),user);ensure_active(db,'agent_run',id)
    from ..services.processing_tasks import linked_requirement
    linked_requirement(db,run,user,True)
    if run.status!='completed':raise HTTPException(409,'请等待分析执行完成')
    from ..models import SkillVersion
    if db.get(SkillVersion,run.skill_version_id).config['workflow'] not in ('analysis','quality','clarification','impact'):raise HTTPException(422,'本任务请使用文档确认或台账确认入口')
    confirmed={field:True for field in ('analysis','clarification','impact') if run.result.get(field)}
    run.result={**run.result,**{'saved_'+k:v for k,v in confirmed.items()},'saved_analysis_confirmed':True}
    audit(db,user,'agent.confirm_analysis',id,fields=list(confirmed));db.commit();return task_record(db,run,user,True)

@router.get('/processing-tasks')
def tasks(user=Depends(current_user),db:Session=Depends(get_db)):
    return [task_record(db,r,user) for r in db.scalars(readable_tasks(user).order_by(AgentRun.created_at.desc())).all()]

@router.get('/processing-tasks/{id}')
def task_detail(id:str,user=Depends(current_user),db:Session=Depends(get_db)):
    if user.role==DEVELOPMENT_MEMBER:
        run=db.scalar(readable_tasks(user).where(AgentRun.id==id))
        if not run: raise HTTPException(404,'任务不存在或未授权')
    else:
        run=db.get(AgentRun,id)
        if user.role=='super_admin' and run and run.owner_id!=user.id:
            run=db.scalar(readable_tasks(user,include_related=True).where(AgentRun.id==id))
            if not run: raise HTTPException(404,'任务不存在或未授权')
        else:
            run=owned(run,user);ensure_active(db,'agent_run',id)
    return task_record(db,run,user,True)

@router.put('/processing-tasks/{id}/requirement')
def associate(id:str,data:Association,user=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);run=owned(db.scalar(select(AgentRun).where(AgentRun.id==id).with_for_update()),user);ensure_active(db,'agent_run',id)
    associate_task(db,run,user,data.requirement_id,data.expected_revision);db.commit();return task_record(db,run,user,True)

@router.post('/processing-tasks/{id}/new-requirement')
def create_requirement(id:str,data:NewRequirement,user=Depends(current_user),db:Session=Depends(get_db)):
    write_lock(db);run=owned(db.scalar(select(AgentRun).where(AgentRun.id==id).with_for_update()),user);ensure_active(db,'agent_run',id)
    if data.requirement.state not in ('draft','clarifying','confirmed'):raise HTTPException(422,'新需求不能直接设置为已编制或发布')
    if data.requirement.source_version_id:require_version(db,data.requirement.source_version_id,user)
    from ..services.identity import check_identity
    check_identity(db,user,data.requirement.number,data.requirement.tags)
    req=Requirement(owner_id=user.id,**data.requirement.model_dump());db.add(req);db.flush()
    associate_task(db,run,user,req.id,data.expected_revision)
    audit(db,user,'requirement.create',req.id,from_task=run.id);db.commit();return task_record(db,run,user,True)
