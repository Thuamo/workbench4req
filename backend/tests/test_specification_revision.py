import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Document, DocumentVersion, DocumentWorkspace, Outbox, RequirementPackSpecification
from app.services.richtext import render
from app.worker import process_one
from test_requirement_initialization import install_model, upload_business


def baseline_for(setup, *, rich):
    clients,base=setup
    member,owner=clients['member']
    requirement=member.post('/requirements',json={'number':'REV-1','title':'软需变更验证'}).json()
    path='/requirements/'+requirement['id']
    pack=member.post(path+'/packs',json={'name':'变更资料包'}).json()
    tree={'type':'doc','content':[
        {'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':'提交校验'}]},
        {'type':'paragraph','content':[{'type':'text','text':'证件号必填。'}]},
        {'type':'paragraph','attrs':{'textAlign':'right'},'content':[{'type':'text','text':'保留过往记录。','marks':[{'type':'bold'}]}]},
        {'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':'验收用例'}]},
        {'type':'paragraph','content':[{'type':'text','text':'既有验收口径。'}]},
    ]}
    content=render(tree)
    with SessionLocal() as db:
        doc=Document(title='基线软需',kind='specification',requirement_id=requirement['id'],owner_id=owner,base_id=base)
        db.add(doc)
        db.flush()
        baseline=DocumentVersion(document_id=doc.id,creator_id=owner,label='V1.0',filename='基线.md',
            parse_status='ready',content=content,file_hash='fixture',provenance={'rich_text':tree} if rich else {})
        db.add_all([baseline,RequirementPackSpecification(pack_id=pack['id'],document_id=doc.id)])
        db.flush()
        baseline_id=baseline.id
        db.commit()
    return member,path,pack['id'],baseline_id,tree,content


def pack_launch(member,path,pack_id,options,request_id=None):
    return member.post(f'{path}/packs/{pack_id}/launch-tasks',json={
        'request_id':request_id or str(uuid4()),'change':options,
    })


def test_manual_change_creates_independent_draft_without_chat_model(setup):
    member,path,pack_id,baseline_id,tree,content=baseline_for(setup,rich=True)
    request_id=str(uuid4())
    options={'mode':'manual','baseline_version_id':baseline_id,'change_note':'补充备注'}
    response=pack_launch(member,path,pack_id,options,request_id)
    assert response.status_code==200,response.text
    run_id=response.json()['task_ids']['specification_change']
    assert pack_launch(member,path,pack_id,options,request_id).json()==response.json()
    with SessionLocal() as db:
        workspace=db.scalar(select(DocumentWorkspace).where(DocumentWorkspace.run_id==run_id))
        assert workspace and workspace.content_json==tree
        assert workspace.change_note=='补充备注' and workspace.version_id==baseline_id
        assert not db.scalar(select(Outbox.id).where(Outbox.resource_id==run_id))
        workspace_id=workspace.id
    opened=member.post('/document-workspaces/open',json={'run_id':run_id}).json()
    assert opened['id']==workspace_id and opened['label']=='V1.1'
    confirmed=member.post(f'/document-workspaces/{workspace_id}/confirm',json={'expected_revision':0})
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['parent_id']==baseline_id and confirmed.json()['status']=='draft'
    with SessionLocal() as db:
        assert db.get(DocumentVersion,baseline_id).content==content


@pytest.mark.parametrize('rich',[True,False])
def test_local_change_requires_review_and_applies_only_edited_selection(setup,rich):
    member,path,pack_id,baseline_id,tree,content=baseline_for(setup,rich=rich)
    options={'mode':'partial','baseline_version_id':baseline_id,'section':'提交校验'}
    assert pack_launch(member,path,pack_id,options).status_code==422
    options['change_note']='证件号改为选填。'
    assert pack_launch(member,path,pack_id,{**options,'section':'不存在的章节'}).status_code==422
    install_model()
    response=pack_launch(member,path,pack_id,options)
    assert response.status_code==200,response.text
    run_id=response.json()['task_ids']['specification_change']
    first,second,outside=(2,3,5) if rich else (3,5,9)

    def model(_db,_owner,messages,**kwargs):
        data=json.loads(messages[-1]['content'])
        assert data['change_note']=='证件号改为选填。' and data['section']=='提交校验'
        assert kwargs['json_output']
        return json.dumps({'suggestions':[
            {'start':first,'end':first,'replacement':'证件号选填。','reason':'更新提交字段'},
            {'start':second,'end':second,'replacement':'改动既有记录。','reason':'建议复核'},
            {'start':outside,'end':outside,'replacement':'不应出现在本次范围。','reason':'超出范围'},
        ],'unresolved':['接口约束待确认']},ensure_ascii=False),{}

    with patch('app.services.specification_revision.complete',side_effect=model):
        assert process_one()
    task=member.get('/processing-tasks/'+run_id).json()
    plan=task['result']['local_change']
    assert task['stage']=='local_change_ready'
    assert [item['before'] for item in plan['items']]==['证件号必填。','**保留过往记录。**']
    assert len(plan['unresolved'])==2
    assert member.post('/document-workspaces/open',json={'run_id':run_id}).status_code==409
    with SessionLocal() as db:
        assert not db.scalar(select(DocumentWorkspace.id).where(DocumentWorkspace.run_id==run_id))

    endpoint='/agent-runs/'+run_id+'/apply-local-change'
    modified='证件号可选填，按实际情况提供。'
    replacement={'id':1,'replacement':modified}
    if rich:
        replacement['content_json']={'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':modified}]}]}
    assert member.post(endpoint,json={'changes':[replacement,{**replacement,'id':999}]}).status_code==422
    applied=member.post(endpoint,json={'changes':[replacement]})
    assert applied.status_code==200,applied.text
    assert member.post(endpoint,json={'changes':[]}).json()==applied.json()
    opened=member.post('/document-workspaces/open',json={'run_id':run_id}).json()
    assert opened['content']==content.replace('证件号必填。',modified)
    assert opened['version_id']==baseline_id
    if rich:
        assert opened['content_json']['content'][2:]==tree['content'][2:]
    with SessionLocal() as db:
        assert db.get(DocumentVersion,baseline_id).content==content


def test_full_change_requires_primary_source_and_uses_legacy_workflow(setup):
    member,path,pack_id,baseline_id,_tree,_content=baseline_for(setup,rich=True)
    source=upload_business(member,setup[1],path.split('/')[-1])
    assert process_one()
    assert member.post(f'{path}/packs/{pack_id}/stages/specification/documents',json={'version_ids':[source['id']]}).status_code==200
    install_model()
    options={'mode':'full','baseline_version_id':baseline_id,'source_version_ids':[source['id']]}
    assert pack_launch(member,path,pack_id,options).status_code==422
    options['primary_change_version_id']=source['id']
    response=pack_launch(member,path,pack_id,options)
    assert response.status_code==200,response.text
    run_id=response.json()['task_ids']['specification_change']
    task=member.get('/processing-tasks/'+run_id).json()
    assert task['status']=='pending' and task['workflow']=='specification'
    assert task['inputs']['_specification_primary_change_id']==source['id']
    assert task['inputs']['source_version_ids']==[baseline_id,source['id']]
