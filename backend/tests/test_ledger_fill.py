from conftest import ready_source
from datetime import datetime
import json
from unittest.mock import patch
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import Skill,SkillVersion,AgentRun,ClarificationTask,Setting,TaskHistory,ModelConfig
from app.services.ledger import FIELDS
from app.services.ledger_fill import prepare,finish,workflow
from app.security import cipher
from app.worker import process_one


def fixture(setup,existing=False):
    clients,base=setup;member,owner=clients['member']
    payload={'name':'台账填报','command':'/填报','description':'24列','config':{'workflow':'ledger_fill'}}
    skill=member.post('/skills',json=payload).json()
    with SessionLocal() as db:
        columns=FIELDS[:2]+list(reversed(FIELDS[2:]))
        db.add(Setting(key='ledger_columns:'+owner,value={'columns':columns}))
        if existing: db.add(ClarificationTask(owner_id=owner,fields={'需求编号':'RM_00053002','需求名称':'已登记名称','申请部门':'已登记部门','工作量':0}))
        run=AgentRun(owner_id=owner,skill_version_id=skill['current_version_id'],status='completed',inputs={'task':'RM_00053002-澄清台账自动填报'})
        db.add(run);db.flush();rid=run.id
        preview=prepare(db,run)
        fields={c:None for c in columns};fields.update({'需求编号':'RM_00053002','需求名称':'生成名称','申请部门':'模型部门','业务对象':'业务分类'})
        run.result={'ledger_preview':finish(preview,{'items':[{'fields':fields}]})};db.commit()
    return member,rid,columns,clients


def test_preview_preserves_24_column_order_and_requires_explicit_confirm(setup):
    member,rid,columns,clients=fixture(setup)
    run=member.get('/agent-runs/'+rid).json();p=run['result']['ledger_preview']
    assert run['workflow']=='ledger_fill' and p['columns']==columns
    assert list(p['fields'])==columns
    assert member.get('/clarification/tasks').json()==[]
    data={'revision':p['revision'],'fields':p['fields'],'confirm':False}
    assert member.post('/agent-runs/'+rid+'/ledger-confirm',json=data).status_code==422
    assert clients['other'][0].post('/agent-runs/'+rid+'/ledger-confirm',json={**data,'confirm':True}).status_code==404
    result=member.post('/agent-runs/'+rid+'/ledger-confirm',json={**data,'confirm':True})
    assert result.status_code==200,result.text
    assert len(member.get('/clarification/tasks').json())==1
    assert member.post('/agent-runs/'+rid+'/ledger-confirm',json={**data,'confirm':True}).json()['already_confirmed']
    assert len(member.get('/clarification/tasks').json())==1


def test_fill_blanks_preserves_registered_values_and_zero(setup):
    member,rid,columns,_=fixture(setup,True)
    p=member.get('/agent-runs/'+rid).json()['result']['ledger_preview']
    assert p['fields']['需求名称']=='已登记名称' and p['fields']['工作量']==0 and p['fields']['申请部门']=='已登记部门'
    bad={**p['fields'],'申请部门':'覆盖'}
    assert member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':p['revision'],'fields':bad,'confirm':True}).status_code==409
    p['fields']['业务对象']='人工修订分类'
    result=member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':p['revision'],'fields':p['fields'],'confirm':True})
    assert result.status_code==200,result.text
    rows=member.get('/clarification/tasks').json()
    assert len(rows)==1 and rows[0]['fields']['业务对象']=='人工修订分类' and rows[0]['revision']==2
    assert member.get('/agent-runs/'+rid).json()['result']['saved_ledger_fields']['业务对象']=='人工修订分类'


def test_stale_layout_or_existing_row_blocks_confirmation(setup):
    member,rid,_,_=fixture(setup,True)
    p=member.get('/agent-runs/'+rid).json()['result']['ledger_preview']
    with SessionLocal() as db:
        task=db.scalar(select(ClarificationTask));task.revision+=1;db.commit()
    result=member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':p['revision'],'fields':p['fields'],'confirm':True})
    assert result.status_code==409


def test_invalid_row_fields_do_not_insert(setup):
    member,rid,_,_=fixture(setup)
    p=member.get('/agent-runs/'+rid).json()['result']['ledger_preview']
    for fields in [{**p['fields'],'额外列':'不允许'},{**p['fields'],'需求编号':'RM_00099999'},{**p['fields'],'业务对象':'多\n行'}]:
        assert member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':p['revision'],'fields':fields,'confirm':True}).status_code==422
    assert member.get('/clarification/tasks').json()==[]


def test_legacy_package_uses_ledger_workflow_and_graph_output(setup):
    clients,_=setup;member,owner=clients['member']
    skill=member.post('/skills',json={'name':'旧导入填报包','command':'/旧包','description':'test','config':{'workflow':'clarification'}}).json()
    with SessionLocal() as db:
        version=db.get(SkillVersion,skill['current_version_id']);version.config={**version.config,'package_metadata':{'files':['package/scripts/clarification_row.py']}}
        db.add(ModelConfig(name='ledger-test',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()));db.commit()
    assert workflow(version.config)=='ledger_fill'
    run=member.post('/skills/'+skill['id']+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'RM_00053002-澄清台账自动填报'}).json()
    def model(*args,**kwargs):
        fields={c:None for c in FIELDS};fields.update({'需求编号':'RM_00053002','需求名称':'测试需求'})
        return json.dumps({'items':[{'fields':fields}]}),{'model':'fixture'}
    with patch('app.services.agents.complete',side_effect=model) as called:
        assert process_one()
    result=member.get('/agent-runs/'+run['id']).json()
    assert result['status']=='completed',result
    assert result['workflow']=='ledger_fill' and called.call_count==1
    assert 'ledger_preview' in result['result'] and 'clarification' not in result['result']
    assert member.get('/clarification/tasks').json()==[]


def test_regenerate_preview_does_not_write_ledger_and_invalidates_old_token(setup):
    member,rid,columns,_=fixture(setup)
    old=member.get('/agent-runs/'+rid).json()['result']['ledger_preview']
    with SessionLocal() as db:
        db.add(ModelConfig(name='ledger-preview-test',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()));db.commit()
    fields={c:None for c in columns};fields.update({'需求编号':'RM_00053002','需求名称':'重新填报'})
    with patch('app.services.agents.complete',return_value=(json.dumps({'items':[{'fields':fields}]}),{'model':'fixture'})):
        response=member.post('/agent-runs/'+rid+'/ledger-preview')
    assert response.status_code==200,response.text
    assert response.json()['revision']!=old['revision']
    assert member.get('/clarification/tasks').json()==[]
    assert member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':old['revision'],'fields':old['fields'],'confirm':True}).status_code==409


def test_existing_multiline_notes_are_preserved_without_overwrite(setup):
    member,rid,_,_=fixture(setup,True)
    with SessionLocal() as db:
        task=db.scalar(select(ClarificationTask));task.fields={**task.fields,'备注':'登记内容\n第二行'}
        run=db.get(AgentRun,rid);preview=prepare(db,run)
        fields={c:None for c in preview['columns']};fields.update({'需求编号':'RM_00053002','需求名称':'新名称'})
        run.result={'ledger_preview':finish(preview,{'items':[{'fields':fields}]})};db.commit()
    preview=member.get('/agent-runs/'+rid).json()['result']['ledger_preview']
    assert preview['fields']['备注']=='登记内容\n第二行'
    result=member.post('/agent-runs/'+rid+'/ledger-confirm',json={'revision':preview['revision'],'fields':preview['fields'],'confirm':True})
    assert result.status_code==200,result.text
    assert member.get('/clarification/tasks').json()[0]['fields']['备注']=='登记内容\n第二行'


def test_duplicate_number_generates_from_latest_meeting_and_only_updates_selected_row(setup):
    member,rid,columns,clients=fixture(setup)
    owner=clients['member'][1]
    number='RM_00053002'
    with SessionLocal() as db:
        past=ClarificationTask(owner_id=owner,created_at=datetime(2026,11,19),fields={
            '需求编号':number,'需求名称':'旧会议','澄清周':'8/24-8/28','澄清时间':'2026-08-24T14:00:00','会议结论':'保留旧结论','工作量':0})
        latest=ClarificationTask(owner_id=owner,created_at=datetime(2026,10,28),fields={
            '需求编号':number,'需求名称':'最新会议','澄清周':'10/19-10/23','澄清时间':'2026-10-20T15:00:00','会议结论':'最新结论'})
        undated=ClarificationTask(owner_id=owner,created_at=datetime(2026,11,20),fields={'需求编号':number,'需求名称':'未登记时间'})
        foreign=ClarificationTask(owner_id=clients['other'][1],fields={'需求编号':number,'需求名称':'其他账号','澄清时间':'2026-12-01'})
        db.add_all([past,latest,undated,foreign,ModelConfig(name='ledger-multi',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode())])
        db.commit()
        latest_id,past_id,undated_id,foreign_id=latest.id,past.id,undated.id,foreign.id

    def model(db,owner,messages,**kwargs):
        prompt=json.loads(messages[-1]['content'])['instruction']
        assert '最新结论' in prompt and '保留旧结论' not in prompt
        fields={column:None for column in columns}|{'需求编号':number,'需求名称':'模型名称','业务对象':'填报建议'}
        return json.dumps({'items':[{'fields':fields}]}),{}

    with patch('app.services.agents.complete',side_effect=model):
        response=member.post('/agent-runs/'+rid+'/ledger-preview')
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['baseline']['task_id']==latest_id
    assert preview['fields']['会议结论']=='最新结论'
    assert [row['task_id'] for row in preview['targets']]==[latest_id,past_id,undated_id]
    assert preview['targets'][1]['fields']['澄清周']=='8/24-8/28'
    endpoint='/agent-runs/'+rid+'/ledger-confirm'
    body={'revision':preview['revision'],'confirm':True,'fields':preview['fields']}
    assert member.post(endpoint,json=body).status_code==422
    assert member.post(endpoint,json={**body,'target_task_id':foreign_id}).status_code==422
    assert member.post(endpoint,json={**body,'target_task_id':past_id}).status_code==409
    body['fields']={**preview['fields'],**preview['targets'][1]['fields']}
    saved=member.post(endpoint,json={**body,'target_task_id':past_id})
    assert saved.status_code==200,saved.text
    assert saved.json()['task_id']==past_id
    assert member.post(endpoint,json={**body,'target_task_id':latest_id}).status_code==409
    with SessionLocal() as db:
        assert db.get(ClarificationTask,latest_id).revision==1
        row=db.get(ClarificationTask,past_id)
        assert row.revision==2 and row.fields['会议结论']=='保留旧结论' and row.fields['工作量']==0
        assert row.fields['业务对象']=='填报建议'
        assert db.scalar(select(func.count()).select_from(TaskHistory).where(TaskHistory.task_id==past_id))==1
