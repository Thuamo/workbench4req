"""Human-confirmed ledger rows, isolated from generic clarification questions."""
import json,re,uuid,math
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import HTTPException
from ..models import ClarificationTask,TaskHistory,User,Requirement
from ..security import digest,audit
from .ledger import ledger_columns,lock_ledger
from .deletion import active_filter,ensure_active


def workflow(config):
    files=config.get('package_metadata',{}).get('files',[])
    return 'ledger_fill' if config.get('workflow')=='ledger_fill' or any(f.endswith('/scripts/clarification_row.py') for f in files) else config.get('workflow','qa')


def number_key(value):
    match=re.fullmatch(r'(?:RM[_-]?)?0*(\d+)',str(value).strip(),re.I)
    return str(int(match[1])) if match else str(value).strip()


def target_number(run,db):
    if run.inputs.get('_initialization_task')=='ledger_fill':
        requirement=db.get(Requirement,run.inputs.get('requirement_id'))
        if not requirement or requirement.owner_id!=run.owner_id:
            raise HTTPException(409,'填报任务关联的业务需求不可用')
        ensure_active(db,'requirement',requirement.id)
        number=number_key(requirement.number)
        return 'RM_'+number.zfill(8) if number.isdecimal() else number
    task=str(run.inputs.get('task',''))
    ids=re.findall(r'RM[_-]?\d+',task,re.I)
    if not ids: ids=re.findall(r'(?<!\d)\d{5,8}(?!\d)',task)
    if not ids and run.inputs.get('requirement_id'):
        r=db.get(Requirement,run.inputs['requirement_id'])
        if r and r.owner_id==run.owner_id: ids=[r.number]
    keys={number_key(v) for v in ids}
    if len(keys)!=1: raise HTTPException(422,'请在任务中明确一个需求编号；多需求请分别发起填报任务')
    return 'RM_'+next(iter(keys)).zfill(8)


def clarification_time(task):
    value=task.fields.get('澄清时间')
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.strip())
        except ValueError:
            return datetime.min
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    return datetime.min


def snapshot(db,user,number):
    columns=ledger_columns(db,user)
    if len(columns)!=24 or len(set(columns))!=24 or not {'需求编号','需求名称'}<=set(columns):
        raise HTTPException(422,'当前澄清计划必须是包含需求编号、需求名称的原表24列，请先核对导入表头')
    rows=[t for t in db.scalars(select(ClarificationTask).where(ClarificationTask.owner_id==user.id,active_filter('clarification_task',ClarificationTask.id))).all() if number_key(t.fields.get('需求编号',''))==number_key(number)]
    rows.sort(key=lambda row: (clarification_time(row),row.created_at,row.id), reverse=True)
    targets=[{'task_id':row.id,'revision':row.revision,'fields':row.fields} for row in rows]
    latest=targets[0] if targets else {'task_id':None,'revision':None,'fields':{}}
    baseline={'columns':columns,**latest}
    return baseline,targets


def snapshot_stamp(payload):
    return digest(json.dumps(payload,ensure_ascii=False,sort_keys=True))


def registered(value):
    return value is not None and value!=''


def values(fields,columns,existing=None):
    if set(fields)!=set(columns): raise HTTPException(422,'填报内容必须恰好包含原表24列，不可遗漏或增加字段')
    result={}
    for column in columns:
        v=fields[column]
        if v is not None and (type(v) not in (str,int,float) or isinstance(v,float) and not math.isfinite(v)):
            raise HTTPException(422,'台账字段仅支持文本、数字或空值')
        unchanged=existing is not None and column in existing and existing[column]==v
        if isinstance(v,str) and not unchanged and (len(v)>10000 or re.search(r'[\t\r\n]',v)): raise HTTPException(422,'新增字段不能包含换行、制表符或超过10000字；原表登记值保持')
        result[column]=v
    return result


def prepare(db,run):
    user=db.get(User,run.owner_id);number=target_number(run,db);base,targets=snapshot(db,user,number)
    stamp=snapshot_stamp({'columns':base['columns'],'targets':targets})
    return {'columns':base['columns'],'number':number,'baseline':base,'targets':targets,'snapshot':stamp,'revision':uuid.uuid4().hex}


def finish(preview,result):
    columns=preview['columns'];items=result.get('items',[])
    if len(items)!=1 or not isinstance(items[0].get('fields'),dict): raise HTTPException(422,'模型必须返回一条包含24列 fields 的填报记录')
    fields=values(items[0]['fields'],columns,preview['baseline']['fields'])
    if number_key(fields['需求编号'])!=number_key(preview['number']): raise HTTPException(422,'模型返回的需求编号与当前任务不一致')
    for key,value in preview['baseline']['fields'].items():
        if key in fields and registered(value): fields[key]=value
    fields['需求编号']=preview['baseline']['fields'].get('需求编号') or preview['number']
    return {**preview,'fields':fields}


def instruction(preview):
    context={'number':preview['number'],'columns':preview['columns'],'baseline':{'fields':preview['baseline']['fields']}}
    return '本次是澄清台账填报，不是生成澄清问题或软需文档。只在 items 返回一个对象，其 fields 按下列24列逐项填写，必须全部包含，未知值为 null，不得添加列；answer/questions/relations 为空。以最新台账记录为参考，已登记非空值（包括0）保持，日期人员进度无证据留空，不把文档编号当需求编号。列顺序及当前行：'+json.dumps(context,ensure_ascii=False)


def confirm(db,run,user,revision,fields,target_task_id=None):
    lock_ledger(db,user);db.refresh(run);ensure_active(db,'agent_run',run.id)
    if run.status!='completed': raise HTTPException(409,'任务状态已变化，请刷新核对')
    if run.result.get('saved_ledger_task_id'):
        tid=run.result['saved_ledger_task_id'];ensure_active(db,'clarification_task',tid)
        if target_task_id and target_task_id!=tid: raise HTTPException(409,'本次填报已写入另一条台账记录')
        return {'task_id':tid,'already_confirmed':True}
    preview=run.result.get('ledger_preview')
    if not preview or preview['revision']!=revision: raise HTTPException(409,'填报预览已更新，请重新打开核对')
    base,targets=snapshot(db,user,preview['number'])
    saved_snapshot={'columns':base['columns'],'targets':targets} if 'targets' in preview else base
    if snapshot_stamp(saved_snapshot)!=preview['snapshot'] or ('targets' not in preview and len(targets)>1):
        raise HTTPException(409,'原表列或同编号台账已变化，请重新生成预览，当前台账未修改')
    if len(targets)>1 and not target_task_id:
        raise HTTPException(422,'请选择要更新的台账记录')
    if target_task_id:
        base=next((target for target in targets if target['task_id']==target_task_id),None)
        if not base: raise HTTPException(422,'所选台账记录不属于本次填报')
    fields=values(fields,preview['columns'],base['fields'])
    if number_key(fields['需求编号'])!=number_key(preview['number']) or not str(fields['需求名称'] or '').strip(): raise HTTPException(422,'请保留任务需求编号并填写需求名称')
    for key,value in base['fields'].items():
        if registered(value) and fields.get(key)!=value: raise HTTPException(409,'已登记非空值不能通过自动填报覆盖，请在澄清计划中人工修改')
    from .processing_tasks import linked_id,linked_requirement
    if not base['task_id'] and linked_id(db,run): linked_requirement(db,run,user)
    task=db.get(ClarificationTask,base['task_id']) if base['task_id'] else ClarificationTask(owner_id=user.id,requirement_id=linked_id(db,run),fields={},status='pending')
    if base['task_id']: task.revision+=1
    else: db.add(task)
    task.fields=fields
    raw=str(fields.get('澄清结果') or '')
    task.status='completed' if raw in ('澄清结束','已自行澄清') else 'not_needed' if raw=='无需澄清' else 'in_progress' if raw else 'pending'
    db.flush();db.add(TaskHistory(task_id=task.id,actor_id=user.id,fields=fields,revision=task.revision))
    run.result={**run.result,'saved_ledger_task_id':task.id,'saved_ledger_revision':revision,'saved_ledger_fields':fields,'saved_ledger_columns':preview['columns']}
    audit(db,user,'ledger.fill_confirm',run.id,task_id=task.id,mode='fill_blanks' if base['task_id'] else 'insert')
    db.commit();return {'task_id':task.id,'already_confirmed':False}
