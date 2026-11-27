from sqlalchemy import select
from app.db import SessionLocal
from app.models import AgentRun, RequirementContext, Notification, DocumentVersion, Question
from test_editing_workflow import fixture_run, start_protocol_run


def test_task_stays_independent_until_explicit_requirement_association(setup):
    member,run_id=start_protocol_run(setup)
    run=member.get('/agent-runs/'+run_id).json()
    assert run['requirement_id'] is None and member.get('/requirements').json()==[]
    assert member.get('/work-items').json()[0]['destination']=={'page':'task','id':run_id}
    with SessionLocal() as db:
        run=db.get(AgentRun,run_id);run.status='completed'
        run.result={'workflow':'specification','sections':[{'title':'正文','content':'测试正文'}],'analysis':{'items':[{'title':'原子功能','tags':{}}]}}
        db.commit()
    saved=member.post('/agent-runs/'+run_id+'/save',json={'base_id':setup[1],'title':'测试文档','label':'V1.0','content':'确认正文'})
    assert saved.status_code==200,saved.text
    assert saved.json()['requirement_id'] is None
    requirement=member.post('/requirements',json={'number':'BUSINESS-1','title':'明确的业务需求'}).json()
    parent_id=requirement['id']
    assert member.put('/processing-tasks/'+run_id+'/requirement',json={'requirement_id':parent_id,'expected_revision':1}).status_code==200
    child=member.post('/agent-runs/'+run_id+'/save-requirements',json={'selected_indices':[0],'confirm':True}).json()['requirements'][0]
    assert child['kind']=='detail' and child['parent_id']==parent_id
    workspace=member.get('/requirements/'+parent_id+'/workspace').json()
    assert workspace['requirement']['kind']=='business'
    assert workspace['children'][0]['id']==child['id']
    assert workspace['stage']['code']=='version_confirmed'
    assert setup[0]['other'][0].get('/requirements/'+parent_id+'/workspace').status_code==404
    assert setup[0]['other'][0].get('/work-items').json()==[]


def test_draft_revisions_block_other_tab_and_late_autosave(setup):
    member,base,run_id,_=fixture_run(setup)
    path='/agent-runs/'+run_id
    draft={'content':'本页编辑','base_id':base,'label':'V1.0','title':'并发编辑','expected_editor_revision':0}
    assert member.put(path+'/document-draft',json=draft).json()['revision']==1
    assert member.put(path+'/document-draft',json={**draft,'content':'旧页面覆盖'}).status_code==409
    assert member.post(path+'/save',json=draft).status_code==409
    assert member.get(path).json()['result']['editor_draft']['content']=='本页编辑'
    assert member.post(path+'/save',json={**draft,'expected_editor_revision':1}).status_code==200
    assert member.put(path+'/document-draft',json={**draft,'expected_editor_revision':1}).status_code==409
    assert 'editor_draft' not in member.get(path).json()['result']


def test_workspace_review_and_notification_destinations_are_authorized(setup):
    clients,_=setup
    member,base,run_id,requirement=fixture_run(setup)
    saved=member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'title':'审核动线','label':'V1.0','content':'确认正文'}).json()
    review=member.post('/versions/'+saved['id']+'/submit',json={'reviewer_ids':[clients['review_a'][1]],'note':'流程测试'})
    assert review.status_code==200,review.text
    workspace=member.get('/requirements/'+requirement['id']+'/workspace').json()
    assert workspace['stage']['code']=='reviewing'
    assert workspace['reviews'][0]['id']==review.json()['id']
    items=clients['review_a'][0].get('/work-items').json()
    assert any(item['stage']=='review_todo' and item['destination']['id']==review.json()['id'] for item in items)
    notifications=clients['review_a'][0].get('/notifications').json()
    assert any(n['destination'] and n['destination']['page'] in ('reviews','document') for n in notifications)
    assert clients['other'][0].get('/notifications').json()==[]
    if notifications:
        assert clients['other'][0].post('/notifications/'+notifications[0]['id']+'/read').status_code==404


def test_changed_clarification_warns_without_overwriting_document(setup):
    member,base,run_id,requirement=fixture_run(setup)
    q=member.post('/clarification/questions',json={'description':'保存期限','category':'业务规则','requirement_id':requirement['id']}).json()
    saved=member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'title':'澄清追踪','label':'V1.0','content':'原确认正文'}).json()
    changed=member.patch('/clarification/questions/'+q['id'],json={'description':q['description'],'category':q['category'],'requirement_id':requirement['id'],'status':'confirmed','conclusion':'保留三年','evidence':{}})
    assert changed.status_code==200,changed.text
    workspace=member.get('/requirements/'+requirement['id']+'/workspace').json()
    assert workspace['needs_revision'] is True
    assert workspace['unresolved_questions']==0
    with SessionLocal() as db:
        assert db.get(DocumentVersion,saved['id']).content=='原确认正文'


def test_manual_state_cannot_claim_unpublished_document_is_published(setup):
    member=setup[0]['member'][0]
    assert member.post('/requirements',json={'number':'P-1','title':'非法发布','state':'published'}).status_code==422
    requirement=member.post('/requirements',json={'number':'P-1','title':'正常登记'}).json()
    assert member.patch('/requirements/'+requirement['id']+'?expected_revision=1',json={'number':'P-1','title':'非法编制','state':'specified'}).status_code==422
    assert member.patch('/requirements/'+requirement['id']+'?expected_revision=1',json={'number':'P-1','title':'正常确认','state':'confirmed'}).status_code==200
