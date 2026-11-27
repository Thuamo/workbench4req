from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import AgentRun,Requirement,Document,DocumentVersion,Outbox,ProcessingTaskContext
from test_editing_workflow import start_protocol_run
from test_document_workspace import tree

def completed(setup):
    member,id=start_protocol_run(setup)
    with SessionLocal() as db:
        run=db.get(AgentRun,id);run.status='completed';run.result={'sections':[{'title':'需求背景','content':'原始正文'}],'analysis':{'items':[{'title':'功能明细','tags':{}}]}}
        job=db.scalar(select(Outbox).where(Outbox.resource_id==id));job.status='completed';db.commit()
    return member,id

def save_document(member,id,base):
    w=member.post('/document-workspaces/open',json={'run_id':id}).json()
    r=member.put('/document-workspaces/'+w['id'],json={'expected_revision':w['revision'],'content_json':tree('任务独立文档'),'title':'任务输出','label':'V1.0','base_id':base})
    assert r.status_code==200,r.text
    result=member.post('/document-workspaces/'+w['id']+'/confirm',json={'expected_revision':r.json()['revision']})
    assert result.status_code==200,result.text
    return result.json(),w['id']

def test_unlinked_task_and_confirmed_document_never_create_requirement(setup):
    member,id=completed(setup)
    assert member.get('/requirements').json()==[]
    assert member.get('/processing-tasks/'+id).json()['requirement_id'] is None
    v,_=save_document(member,id,setup[1])
    assert v['requirement_id'] is None and member.get('/requirements').json()==[]
    task=member.get('/processing-tasks/'+id).json()
    assert task['output_count']==1 and [d['version']['id'] for d in task['documents'] if d['role']=='output']==[v['id']]
    assert member.post('/agent-runs/'+id+'/save-requirements',json={'selected_indices':[0],'confirm':True}).status_code==409
    assert member.get('/requirements').json()==[]
    assert setup[0]['other'][0].get('/processing-tasks/'+id).status_code==404

def test_one_requirement_has_many_tasks_documents_deduplicate_and_inputs_unchanged(setup):
    member,a=completed(setup);v,wid=save_document(member,a,setup[1])
    req=member.post('/requirements',json={'number':'BUS-1','title':'业务需求'}).json()
    attached=member.put('/processing-tasks/'+a+'/requirement',json={'requirement_id':req['id'],'expected_revision':1})
    assert attached.status_code==200,attached.text
    member,b=completed(setup)
    assert member.put('/processing-tasks/'+b+'/requirement',json={'requirement_id':req['id'],'expected_revision':1}).status_code==200
    assert member.get('/agent-runs/'+a).json()['inputs']['requirement_id'] is None
    page=member.get('/requirements/'+req['id']+'/workspace')
    assert page.status_code==200,page.text
    assert {r['id'] for r in page.json()['runs']}=={a,b}
    assert len(page.json()['documents'])==3  # Two required inputs plus one output asset.
    assert len({d['id'] for d in page.json()['documents']})==3
    assert sum(d['id']==v['document_id'] for d in page.json()['documents'])==1
    listing=member.get('/requirements').json()[0];assert listing['task_count']==2 and listing['document_count']==3
    with SessionLocal() as db:
        assert db.get(Document,v['document_id']).requirement_id==req['id']
        assert db.get(DocumentVersion,v['id']).content==v['content']
    assert member.put('/processing-tasks/'+a+'/requirement',json={'requirement_id':None,'expected_revision':1}).status_code==409

    admin=setup[0]['admin'][0]
    admin_page=admin.get('/requirements/'+req['id']+'/workspace')
    assert admin_page.status_code==200,admin_page.text
    assert {r['id'] for r in admin_page.json()['runs']}=={a,b}
    assert all(r['read_only'] for r in admin_page.json()['runs'])
    assert len(admin_page.json()['documents'])==3
    admin_listing=admin.get('/requirements').json()[0]
    assert admin_listing['task_count']==2 and admin_listing['document_count']==3
    task=admin.get('/processing-tasks/'+a).json()
    assert task['read_only'] and task['result']['analysis']['items'][0]['title']=='功能明细'
    assert 'sections' not in task['result']
    assert admin.get('/processing-tasks').json()==[]
    assert admin.put('/processing-tasks/'+a+'/requirement',json={'requirement_id':None,'expected_revision':2}).status_code==404
    _,unlinked=completed(setup)
    assert admin.get('/processing-tasks/'+unlinked).status_code==404

def test_reviewed_outputs_lock_reassociation_and_users_cannot_cross_link(setup):
    member,id=completed(setup);v,_=save_document(member,id,setup[1])
    a=member.post('/requirements',json={'number':'A','title':'需求A'}).json();b=member.post('/requirements',json={'number':'B','title':'需求B'}).json()
    assert member.put('/processing-tasks/'+id+'/requirement',json={'requirement_id':a['id'],'expected_revision':1}).status_code==200
    assert member.post('/versions/'+v['id']+'/submit',json={'reviewer_ids':[setup[0]['review_a'][1]]}).status_code==200
    blocked=member.put('/processing-tasks/'+id+'/requirement',json={'requirement_id':b['id'],'expected_revision':2})
    assert blocked.status_code==409 and '审核' in blocked.text
    assert member.get('/processing-tasks/'+id).json()['requirement_id']==a['id']
    private=setup[0]['other'][0].post('/requirements',json={'number':'P','title':'他人需求'}).json()
    assert member.put('/processing-tasks/'+id+'/requirement',json={'requirement_id':private['id'],'expected_revision':2}).status_code==404

def test_explicit_create_and_associate_is_atomic_and_deleting_requirement_keeps_task(setup):
    member,id=completed(setup)
    payload={'expected_revision':999,'requirement':{'number':'NEW','title':'明确新建'}}
    assert member.post('/processing-tasks/'+id+'/new-requirement',json=payload).status_code==409
    assert member.get('/requirements').json()==[]
    created=member.post('/processing-tasks/'+id+'/new-requirement',json={**payload,'expected_revision':1})
    assert created.status_code==200,created.text
    rid=created.json()['requirement_id']
    assert member.request('DELETE','/records/requirement/'+rid,json={'confirm':True}).status_code==200
    assert member.get('/processing-tasks/'+id).json()['requirement_id'] is None
    assert member.get('/processing-tasks').json()[0]['id']==id

def test_running_task_association_is_locked(setup):
    member,id=start_protocol_run(setup)
    req=member.post('/requirements',json={'number':'R','title':'业务需求'}).json()
    assert member.put('/processing-tasks/'+id+'/requirement',json={'requirement_id':req['id'],'expected_revision':1}).status_code==409
