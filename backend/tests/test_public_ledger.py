import io
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import User,ClarificationTask,TaskHistory
from app.schemas import ChatInput
from app.services.qa import collect
from test_ledger_replacement import workbook,preview,confirmed_upload


def test_public_list_history_export_stats_and_private_link_permissions(setup):
    clients,_=setup;member=clients['member'][0];other=clients['other'][0]
    req=member.post('/requirements',json={'number':'PUB-01','title':'私有业务需求','description':'不随台账公开'}).json()
    a=member.post('/clarification/tasks',json={'fields':{'需求编号':'PUB-01','需求名称':'公共计划甲','自定义字段':'甲字段'}}).json()
    b=other.post('/clarification/tasks',json={'fields':{'需求编号':'PUB-02','需求名称':'公共计划乙'},'status':'completed'}).json()
    assert a['requirement_id']==req['id'] and b['requirement_id'] is None
    baseline=None
    for name,(client,_) in clients.items():
        rows=client.get('/clarification/tasks').json()
        assert {r['id'] for r in rows}=={a['id'],b['id']}
        row=next(r for r in rows if r['id']==a['id'])
        assert row['can_edit']==(name=='member')
        assert row['can_open_requirement']==(name in ('member','admin'))
        assert client.get('/clarification/tasks/'+a['id']+'/history').status_code==200
        layout=client.get('/clarification/columns').json()
        assert layout['visibility']=='public'
        if baseline is None:baseline=layout['columns']
        assert layout['columns']==baseline
        assert client.get('/clarification/stats').json()=={'states':{'pending':1,'completed':1},'total':2}
        dashboard=client.get('/dashboard').json()
        assert dashboard['counts']['待澄清任务']==1 and dashboard['charts']['澄清进度']=={'pending':1,'completed':1}
        rows=list(load_workbook(io.BytesIO(client.get('/clarification/export').content),read_only=True).active.values)
        assert list(rows[0])==baseline and len(rows)==3
    assert other.get('/requirements/'+req['id']+'/workspace').status_code==404
    assert other.get('/requirements').json()==[]
    admin=clients['admin'][0]
    assert admin.get('/requirements').json()[0]['id']==req['id']
    workspace=admin.get('/requirements/'+req['id']+'/workspace')
    assert workspace.status_code==200,workspace.text
    assert workspace.json()['requirement']['description']=='不随台账公开'
    assert workspace.json()['requirement']['can_edit'] is False
    assert admin.patch('/requirements/'+req['id']+'?expected_revision=1',
                       json={'number':'PUB-01','title':'跨账号修改'}).status_code==404
    assert other.patch('/clarification/tasks/'+a['id'],json={'fields':a['fields'],'expected_revision':1}).status_code==404
    assert other.post('/clarification/batch',json={'items':[{'id':a['id'],'expected_revision':1,'status':'completed'}]}).status_code==404
    assert other.request('DELETE','/records/clarification_task/'+a['id'],json={'confirm':True}).status_code==404
    with TestClient(app) as anonymous:
        for path in ('/clarification/tasks','/clarification/export','/clarification/columns','/clarification/stats','/clarification/tasks/'+a['id']+'/history'):
            assert anonymous.get(path).status_code==401


def test_manual_ledger_create_matches_normalized_number_within_owned_requirements(setup):
    clients,_=setup
    member,other=clients['member'][0],clients['other'][0]
    req=member.post('/requirements',json={'number':'RM_00053681','title':'业务需求','tags':{'系统':['信贷']}}).json()
    fields={'需求编号':'53681','需求名称':'不同的台账标题','系统':'其他系统'}
    first=member.post('/clarification/tasks',json={'fields':fields}).json()
    second=member.post('/clarification/tasks',json={'fields':{**fields,'需求编号':'rm-053681'}}).json()
    assert first['id']!=second['id'] and first['requirement_id']==second['requirement_id']==req['id']
    assert other.post('/clarification/tasks',json={'fields':fields}).json()['requirement_id'] is None
    assert member.post('/clarification/tasks',json={'fields':{**fields,'需求编号':'REQ-53681'}}).json()['requirement_id'] is None
    alternate=member.post('/requirements',json={'number':'ALT-001','title':'人工指定需求'}).json()
    explicit=member.post('/clarification/tasks',json={'fields':fields,'requirement_id':alternate['id']})
    assert explicit.status_code==200 and explicit.json()['requirement_id']==alternate['id']


def test_qa_ledger_create_reuses_unique_number_and_creates_missing_requirement(setup):
    clients,_=setup
    member,owner=clients['member']
    with SessionLocal() as db:
        db.get(User,owner).role='qa_member'
        db.commit()
    original=member.post('/requirements',json={'number':'RM_00053681','title':'已有需求','tags':{'系统':['信贷']}}).json()
    response=member.post('/clarification/tasks',json={'fields':{'需求编号':'53681','需求名称':'台账计划'}})
    assert response.status_code==200 and response.json()['requirement_id']==original['id']
    response=member.post('/clarification/tasks',json={'fields':{'需求编号':'53682','需求名称':'新需求'}})
    assert response.status_code==200 and response.json()['requirement_id']
    assert {row['id'] for row in member.get('/requirements').json()}=={original['id'],response.json()['requirement_id']}


def test_public_columns_same_for_everyone_and_personal_import_preserves_others(setup):
    clients,_=setup;member=clients['member'][0];other=clients['other'][0]
    first=workbook(['需求名称','需求编号','甲字段'],[['甲计划','50059','甲']])
    second=workbook(['需求编号','乙字段','需求名称'],[['50060','乙','乙计划']])
    assert confirmed_upload(member,first).status_code==200
    assert confirmed_upload(other,second).status_code==200
    expected=['需求编号','乙字段','需求名称','甲字段']
    assert member.get('/clarification/columns').json()['columns']==expected
    assert other.get('/clarification/columns').json()['columns']==expected
    original_other=next(t for t in member.get('/clarification/tasks').json() if t['owner_id']==clients['other'][1])
    addition=workbook(['新字段','需求编号','需求名称'],[['新','50061','新计划']])
    checked=preview(member,addition)
    assert checked['existing_count']==1
    assert confirmed_upload(member,addition).status_code==200
    rows=other.get('/clarification/tasks').json()
    assert len(rows)==3 and original_other['id'] in {r['id'] for r in rows}
    assert member.get('/clarification/columns').json()['columns']==['需求名称','需求编号','甲字段','新字段','乙字段']
    assert member.get('/clarification/columns').json()['own_columns']==['需求名称','需求编号','甲字段','新字段']


def test_public_ledger_available_to_analysis_without_sharing_private_requirements(setup):
    clients,_=setup;member=clients['member'][0]
    member.post('/requirements',json={'number':'50059','title':'私有需求','description':'私有机密，不能随台账传播'})
    task=member.post('/clarification/tasks',json={'fields':{'需求编号':'50059','需求名称':'公共互斥校验计划'}}).json()
    with SessionLocal() as db:
        user=db.get(User,clients['other'][1])
        evidence,_=collect(db,user,ChatInput(content='50059需求内容是什么',scopes=['mine']),[])
        assert any(r.get('record_id')==task['id'] and r['scope']=='public_ledger' for r in evidence)
        assert all('私有机密' not in r['excerpt'] for r in evidence)
    assert member.request('DELETE','/records/clarification_task/'+task['id'],json={'confirm':True}).status_code==200
    assert clients['other'][0].get('/clarification/tasks').json()==[]
    assert clients['other'][0].get('/clarification/tasks/'+task['id']+'/history').status_code==404
    assert member.get('/clarification/tasks/'+task['id']+'/history').status_code==200
