from datetime import datetime, timezone
from app.db import SessionLocal
from app.models import Audit, Document, DocumentVersion
from test_workbench import upload, publish


def test_metadata_move_and_legacy_retirement_history(setup):
    clients,base=setup
    member,admin,other=clients['member'][0],clients['admin'][0],clients['other'][0]
    version=upload(setup,text='退役历史测试专用文档')
    publish(setup,version)
    before=datetime.now(timezone.utc).isoformat()
    folder=admin.post('/knowledge-bases/'+base+'/folders',json={'name':'新目录'}).json()
    change={'title':'重命名资产','folder_id':folder['id'],'kind':'business'}
    assert other.patch('/documents/'+version['document_id'],json=change).status_code==403
    updated=member.patch('/documents/'+version['document_id'],json=change)
    assert updated.status_code==200,updated.text
    assert updated.json()['current_version_id']==version['id']
    assert updated.json()['folder_id']==folder['id']
    retire_path='/versions/'+version['id']+'/retire'
    for client,status in ((member,'deprecated'),(admin,'archived')):
        assert client.post(retire_path,json={'status':status,'reason':'测试'}).status_code==404
    assert other.get('/search',params={'q':'退役历史测试专用文档'}).json()
    with SessionLocal() as db:
        doc=db.get(Document,version['document_id'])
        saved=db.get(DocumentVersion,version['id'])
        assert doc.current_version_id==saved.id and doc.current_index_id and saved.status=='published'
        saved.status='deprecated'
        doc.current_version_id=None
        doc.current_index_id=None
        db.add(Audit(actor_id=clients['admin'][1],action='version.retire',resource_id=saved.id,
                     detail={'status':'deprecated','reason':'旧版退役记录'}))
        db.commit()
    assert other.get('/search',params={'q':'退役历史测试专用文档'}).json()==[]
    assert other.get('/versions/'+version['id']+'/download').status_code==200
    assert other.get('/search',params={'q':'退役历史测试专用文档','as_of':before}).json()
    assert other.get('/search',params={'q':'退役历史测试专用文档','as_of':datetime.now(timezone.utc).isoformat()}).json()==[]


def test_requirement_lineage_and_explicit_dependency(setup):
    clients,_=setup
    member=clients['member'][0]
    source=upload(setup,text='原件闭环测试')
    publish(setup,source)
    requirement=member.post('/requirements',json={'number':'LINEAGE','title':'原件到软需','source_version_id':source['id']}).json()
    metadata={'title':'业务原件','kind':'business','requirement_id':requirement['id']}
    assert member.patch('/documents/'+source['document_id'],json=metadata).status_code==200
    lineage=member.get('/requirements/'+requirement['id']+'/lineage').json()
    assert lineage['business_source']['id']==source['id']
    edited=member.patch('/requirements/'+requirement['id'],params={'expected_revision':1},json={'number':'LINEAGE','title':'编辑后需求','source_version_id':source['id']})
    assert edited.status_code==200,edited.text
    assert edited.json()['revision']==2
    assert lineage['documents'][0]['current_version_id']==source['id']
    impact=member.get('/documents/'+source['document_id']+'/impact',params={'version_id':source['id']}).json()
    assert impact['requirements'][0]['id']==requirement['id']
    assert impact['requires_confirmation'] is True
    assert clients['other'][0].get('/requirements/'+requirement['id']+'/lineage').status_code==404
