from conftest import ready_source
from sqlalchemy import select
from app.db import SessionLocal
from app.models import DeletedRecord, ClarificationTask, TaskHistory, Document, DocumentVersion, AgentRun, Outbox, Skill, RequirementContext, Audit
from app.worker import process_one
from test_workbench import upload, publish
from test_editing_workflow import start_protocol_run, fixture_run
from test_ledger_replacement import workbook, preview, upload as import_tasks


def remove(client,kind,rid,**payload):
    return client.request('DELETE','/records/'+kind+'/'+rid,json={'confirm':True,**payload})


def test_admin_sees_unassigned_review_tasks_but_cannot_sign_for_others(setup):
    clients,_=setup;member=clients['member'][0];admin=clients['admin'][0]
    version=upload(setup,'审核权限测试正文')
    submitted=member.post('/versions/'+version['id']+'/submit',json={'reviewer_ids':[clients['review_a'][1]],'note':'管理员可查看'}).json()
    rows=admin.get('/reviews').json()
    assert [r['id'] for r in rows]==[submitted['id']]
    assert admin.get('/reviews?scope=all').json()[0]['id']==submitted['id']
    detail=admin.get('/reviews/'+submitted['id'])
    assert detail.status_code==200 and detail.json()['version']['content']=='审核权限测试正文'
    assert any(item['destination']['id']==submitted['id'] for item in admin.get('/work-items').json())
    task_id=detail.json()['tasks'][0]['id']
    assert admin.post('/review-tasks/'+task_id+'/decision',json={'decision':'approved'}).status_code==404
    assert clients['other'][0].get('/reviews?scope=all').status_code==403
    assert clients['review_b'][0].get('/reviews/'+submitted['id']).status_code==404
    # Neither the submitter nor admin may hide a document during its live review.
    assert remove(member,'document',version['document_id']).status_code==409
    assert remove(admin,'document',version['document_id']).status_code==409


def test_task_deletion_is_confirmed_owned_and_preserves_question_history(setup):
    clients,_=setup;member=clients['member'][0];other=clients['other'][0]
    task=member.post('/clarification/tasks',json={'fields':{'需求编号':'DEL-1','需求名称':'待删除任务'}}).json()
    q=member.post('/clarification/questions',json={'description':'保留的业务问题','category':'业务','task_id':task['id'],'feedback':'保留反馈'}).json()
    snap=preview(member,workbook(['需求编号','需求名称'],[['NEW','新任务']]))['snapshot']
    assert member.request('DELETE','/records/clarification_task/'+task['id'],json={}).status_code==422
    assert other.request('DELETE','/records/clarification_task/'+task['id'],json={'confirm':True}).status_code==404
    assert remove(member,'clarification_task',task['id']).status_code==200
    assert member.get('/clarification/tasks').json()==[]
    assert preview(member,workbook(['需求编号','需求名称'],[['NEW','新任务']]))['snapshot']!=snap
    assert member.patch('/clarification/tasks/'+task['id'],json={'fields':task['fields'],'expected_revision':1}).status_code==409
    question=member.get('/clarification/questions').json()[0]
    assert question['id']==q['id'] and question['task_id'] is None and question['feedback']=='保留反馈'
    with SessionLocal() as db:
        assert db.get(ClarificationTask,task['id']) is not None
        assert db.scalar(select(TaskHistory).where(TaskHistory.task_id==task['id'])) is not None
    assert remove(member,'clarification_task',task['id']).json()['already_deleted'] is True
    assert remove(member,'question',q['id']).status_code==200
    assert member.get('/clarification/questions').json()==[]
    assert not any(item['id']=='question:'+q['id'] for item in member.get('/work-items').json())
    addition=workbook(['需求编号','需求名称'],[['NEW','导入后任务']])
    checked=preview(member,addition)
    assert checked['existing_count']==0
    assert import_tasks(member,addition,expected_snapshot=checked['snapshot']).status_code==200
    assert len(member.get('/clarification/tasks').json())==1


def test_requirement_delete_hides_children_without_deleting_documents(setup):
    member,base,run_id,parent=fixture_run(setup)
    saved=member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'title':'历史保留文档','label':'V1','content':'已确认正文'}).json()
    child=member.post('/agent-runs/'+run_id+'/save-requirements',json={'selected_indices':[0],'confirm':True}).json()['requirements'][0]
    assert remove(member,'requirement',parent['id']).status_code==200
    ids={r['id'] for r in member.get('/requirements').json()}
    assert parent['id'] not in ids and child['id'] not in ids
    assert member.get('/requirements/'+parent['id']+'/workspace').status_code==409
    assert member.get('/requirements/'+child['id']+'/workspace').status_code==409
    assert member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'content':'不得恢复','title':'错误','label':'V2'}).status_code==409
    with SessionLocal() as db:
        assert db.get(Document,saved['document_id']) is not None
        assert db.get(DocumentVersion,saved['id']).content=='已确认正文'
        assert db.scalar(select(RequirementContext).where(RequirementContext.requirement_id==child['id'])).parent_id==parent['id']


def test_delete_queued_run_cancels_outbox_and_running_run_is_protected(setup):
    member,run_id=start_protocol_run(setup)
    assert remove(member,'agent_run',run_id).status_code==200
    assert not process_one()
    assert member.get('/agent-runs').json()==[]
    with SessionLocal() as db:
        assert db.get(AgentRun,run_id).status=='cancelled'
        assert db.scalar(select(Outbox).where(Outbox.resource_id==run_id)).status=='cancelled'
    assert member.post('/agent-runs/'+run_id+'/retry',json={}).status_code==409
    # A second run must not disappear while its worker is active.
    run2=member.post('/skills/'+member.get('/skills').json()[0]['id']+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'运行中任务保护'}).json()
    with SessionLocal() as db:
        db.get(AgentRun,run2['id']).status='running'
        db.scalar(select(Outbox).where(Outbox.resource_id==run2['id'])).status='running'
        db.commit()
    assert remove(member,'agent_run',run2['id']).status_code==409
    assert member.get('/agent-runs/'+run2['id']).status_code==200


def test_draft_document_delete_cancels_parse_and_blocks_mutations(setup):
    clients,base=setup;member=clients['member'][0]
    response=member.post('/documents/upload',data={'base_id':base,'title':'未解析上传','label':'V1'},files={'file':('上传.txt','保留原始附件'.encode())})
    assert response.status_code==200,response.text
    v=response.json()
    assert remove(clients['other'][0],'document',v['document_id']).status_code==404
    assert remove(member,'document',v['document_id']).status_code==200
    assert member.get('/documents').json()==[]
    assert member.get('/documents/'+v['document_id']).json()['deleted'] is True
    assert member.get('/versions/'+v['id']+'/download').status_code==200
    assert member.post('/documents/'+v['document_id']+'/restore-draft',json={'label':'V2','source_version_id':v['id']}).status_code==409
    assert member.post('/versions/'+v['id']+'/submit',json={'reviewer_ids':[clients['review_a'][1]]}).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(Outbox).where(Outbox.resource_id==v['id'])).status=='cancelled'
        assert db.scalar(select(Audit).where(Audit.action=='record.delete',Audit.resource_id==v['document_id'])) is not None


def test_published_document_delete_is_admin_governed_and_keeps_review_history(setup):
    clients,_=setup;member=clients['member'][0];admin=clients['admin'][0]
    v=upload(setup,'正式知识删除治理测试')
    publish(setup,v)
    item_data={'name':'历史知识条目','kind':'business_rule','content':'正式规则','source_version_id':v['id'],'locator':v['blocks'][0]['locator'],'reason':'测试确认'}
    item=admin.post('/knowledge-bases/'+setup[1]+'/items',json=item_data)
    assert item.status_code==200,item.text
    assert remove(member,'knowledge_item',item.json()['id']).status_code==403
    assert remove(admin,'knowledge_item',item.json()['id']).status_code==200
    assert admin.get('/knowledge-items?base_id='+setup[1]).json()==[]
    assert admin.post('/knowledge-items/'+item.json()['id']+'/revisions',json=item_data).status_code==409
    assert remove(member,'document',v['document_id']).status_code==403
    assert remove(admin,'document',v['document_id']).status_code==200
    with SessionLocal() as db:
        doc=db.get(Document,v['document_id']);version=db.get(DocumentVersion,v['id'])
        assert doc.current_version_id is None and doc.current_index_id is None
        assert version.status=='archived' and version.content=='正式知识删除治理测试'
    assert admin.get('/reviews?scope=all').json()
    assert member.get('/documents').json()==[]
    assert member.get('/search?q=正式知识删除治理测试').json()==[]


def test_skill_and_relation_delete_hide_lists_and_prevent_reuse(setup):
    clients,_=setup;member=clients['member'][0]
    skill=member.post('/skills',json={'name':'删除技能','command':'/delete-test','description':'测试'}).json()
    assert remove(clients['other'][0],'skill',skill['id']).status_code==404
    assert remove(member,'skill',skill['id']).status_code==200
    assert skill['id'] not in {s['id'] for s in member.get('/skills').json()}
    assert member.post('/skills/'+skill['id']+'/execute',json={'task':'不能复用删除技能'}).status_code==409
    with SessionLocal() as db: assert db.get(Skill,skill['id']).enabled is False
    a=member.post('/requirements',json={'number':'A','title':'源需求'}).json()
    b=member.post('/requirements',json={'number':'B','title':'目标需求'}).json()
    relation=member.post('/relations',json={'source_id':a['id'],'target_id':b['id'],'evidence':{'description':'关联证据'}}).json()
    assert remove(member,'relation',relation['id']).status_code==200
    assert member.get('/relations').json()==[]
    assert member.patch('/relations/'+relation['id'],json={'status':'confirmed'}).status_code==409
