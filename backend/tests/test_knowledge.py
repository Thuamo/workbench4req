from sqlalchemy import select
from app.db import SessionLocal
from app.models import KnowledgeItem, KnowledgeRevision
from test_workbench import upload, publish


def test_confirmed_knowledge_revision_search_and_snapshot(setup):
    clients,base=setup
    member,admin=clients['member'][0],clients['admin'][0]
    version=upload(setup,text='业务规则来源：对处理记录保持追溯')
    publish(setup,version)
    data={'name':'处理追溯规则','kind':'business_rule','content':'知识检索专用术语甲：追溯原始状态','locator':version['blocks'][0]['locator'],'reason':'测试确认','source_version_id':version['id']}
    item=admin.post('/knowledge-bases/'+base+'/items',json=data)
    assert item.status_code==200,item.text
    snapshot=admin.post('/knowledge-bases/'+base+'/snapshots',json={'name':'知识固定测试'}).json()
    revision=admin.post('/knowledge-items/'+item.json()['id']+'/revisions',json={**data,'content':'知识检索专用术语乙：新知识修订'}).json()
    current=member.get('/search',params={'q':'知识检索专用术语乙'}).json()
    assert any(row.get('knowledge_revision_id')==revision['id'] for row in current)
    historical=member.get('/search',params={'q':'知识检索专用术语甲','snapshot_id':snapshot['id']}).json()
    assert any(row.get('knowledge_item_id')==item.json()['id'] and row['knowledge_revision_id']!=revision['id'] for row in historical)
    assert all(row.get('knowledge_revision_id')!=revision['id'] for row in historical)
    admin.post('/knowledge-items/'+item.json()['id']+'/deprecate')
    current=member.get('/search',params={'q':'知识检索专用术语乙'}).json()
    assert not any(row.get('knowledge_item_id')==item.json()['id'] for row in current)
    historical=member.get('/search',params={'q':'知识检索专用术语甲','snapshot_id':snapshot['id']}).json()
    assert any(row.get('knowledge_item_id')==item.json()['id'] for row in historical)
