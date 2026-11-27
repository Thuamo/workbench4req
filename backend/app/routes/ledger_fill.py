from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from ..db import get_db
from ..models import AgentRun,User,SkillVersion
from ..security import current_user,owned,write_lock
from ..services.deletion import ensure_active
from ..services.ledger_fill import workflow,confirm

router=APIRouter(tags=['台账填报'])

def access(db,id,user):
    run=owned(db.get(AgentRun,id),user);ensure_active(db,'agent_run',id)
    if run.status!='completed' or workflow(db.get(SkillVersion,run.skill_version_id).config)!='ledger_fill': raise HTTPException(409,'请等待台账填报任务完成')
    return run

class ConfirmInput(BaseModel):
    revision:str
    fields:dict
    confirm:bool=False
    target_task_id:str|None=Field(default=None,min_length=1,max_length=36)

@router.post('/agent-runs/{id}/ledger-preview')
def generate_preview(id:str,user:User=Depends(current_user),db=Depends(get_db)):
    run=access(db,id,user)
    if run.result.get('saved_ledger_task_id'): raise HTTPException(409,'已入表的任务不能重新生成，请新建填报任务')
    # Explicit user action repairs old generic-clarification runs. No DB lock
    # is held across the model call, and the ledger itself is never written here.
    evidence=list(run.citations)
    db.commit()
    from ..services.agents import ledger_fill
    preview=ledger_fill({'run_id':id,'evidence':evidence})['ledger_preview']
    write_lock(db);run=access(db,id,user)
    if run.result.get('saved_ledger_task_id'): raise HTTPException(409,'任务已确认入表，请刷新核对')
    run.result={**run.result,'ledger_preview':preview};db.commit();return preview

@router.post('/agent-runs/{id}/ledger-confirm')
def confirm_preview(id:str,data:ConfirmInput,user:User=Depends(current_user),db=Depends(get_db)):
    run=access(db,id,user)
    if not data.confirm: raise HTTPException(422,'请明确确认内容后入表')
    return confirm(db,run,user,data.revision,data.fields,data.target_task_id)
