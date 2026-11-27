from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import Skill,SkillVersion,AgentRun,DocumentVersion


def test_personal_skill_approval_promotes_same_asset_and_keeps_runs(setup):
    clients,_=setup
    member,owner=clients['member']
    admin=clients['admin'][0]
    other=clients['other'][0]
    payload={'name':'待发布技能','command':'/待发布','description':'测试','config':{'system_prompt':'早期私人草稿'}}
    created=member.post('/skills',json=payload).json()
    sid=created['id']
    initial_version=created['current_version_id']
    with SessionLocal() as db:
        run=AgentRun(owner_id=owner,skill_version_id=initial_version,status='completed',inputs={'task':'历史任务'})
        db.add(run);db.commit();rid=run.id
        count=db.scalar(select(func.count()).select_from(Skill))
    revised=member.post(f'/skills/{sid}/versions',json={**payload,'config':{'system_prompt':'批准版本'}})
    assert revised.status_code==200,revised.text
    assert admin.post(f'/skills/{sid}/govern',json={'public':True}).status_code==409
    assert member.post(f'/skills/{sid}/publish-request').status_code==200
    assert other.post(f'/skills/{sid}/govern',json={'public':True}).status_code==403
    promoted=admin.post(f'/skills/{sid}/govern',json={'public':True})
    assert promoted.status_code==200,promoted.text
    assert promoted.json()['id']==sid and promoted.json()['public']
    assert not promoted.json()['publication_requested']
    assert admin.post(f'/skills/{sid}/govern',json={'public':True}).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Skill))==count
        assert db.get(AgentRun,rid).owner_id==owner
        assert db.get(AgentRun,rid).skill_version_id==initial_version
    for client in [member,other]:
        items=[s for s in client.get('/skills').json() if s['id']==sid]
        assert len(items)==1 and items[0]['public']
    assert len(member.get(f'/skills/{sid}/versions').json())==2
    assert [v['id'] for v in other.get(f'/skills/{sid}/versions').json()]==[revised.json()['id']]
    assert member.post(f'/skills/{sid}/versions',json=payload).status_code==403
    assert member.get(f'/agent-runs/{rid}').status_code==200
    assert other.get(f'/agent-runs/{rid}').status_code==404


def test_skill_approval_rejects_stale_submission(setup):
    clients,_=setup
    member=clients['member'][0];admin=clients['admin'][0]
    payload={'name':'版本变更技能','command':'/版本测试','description':'测试','config':{}}
    skill=member.post('/skills',json=payload).json();sid=skill['id']
    member.post(f'/skills/{sid}/publish-request')
    member.post(f'/skills/{sid}/versions',json=payload)
    assert admin.post(f'/skills/{sid}/govern',json={'public':True}).status_code==409
    member.post(f'/skills/{sid}/publish-request')
    assert admin.post(f'/skills/{sid}/govern',json={'public':True}).status_code==200


def test_uploaded_file_visible_while_parsing_with_nested_location(setup):
    clients,base=setup
    member=clients['member'][0];admin=clients['admin'][0];other=clients['other'][0]
    parent=admin.post(f'/knowledge-bases/{base}/folders',json={'name':'业务需求'}).json()
    child=admin.post(f'/knowledge-bases/{base}/folders',json={'name':'授信资料','parent_id':parent['id']}).json()
    uploaded=member.post('/documents/upload',data={'title':'新上传文件','base_id':base,'folder_id':child['id'],'label':'V1.0'},files={'file':('sample.txt',b'file fixture')})
    assert uploaded.status_code==200,uploaded.text
    version=uploaded.json()
    docs=member.get('/documents').json()
    doc=next(d for d in docs if d['id']==version['document_id'])
    assert doc['folder_path']==[{'id':parent['id'],'name':'业务需求'},{'id':child['id'],'name':'授信资料'}]
    assert doc['location_path'].endswith(' / 业务需求 / 授信资料')
    assert doc['versions'][0]['parse_status']!='ready'
    assert all(d['id']!=doc['id'] for d in other.get('/documents').json())
    with SessionLocal() as db:
        db.get(DocumentVersion,version['id']).parse_status='ready';db.commit()
    assert next(d for d in member.get('/documents').json() if d['id']==doc['id'])['versions'][0]['parse_status']=='ready'
    assert member.get(f"/documents/{doc['id']}").json()['location_path']==doc['location_path']
