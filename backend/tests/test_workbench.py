from conftest import ready_source
import io
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import httpx
import pytest
from sqlalchemy import select, func
from docx import Document as Word
from openpyxl import Workbook, load_workbook
from app.db import SessionLocal
from app.config import settings
from app.models import Audit, Chunk, Document, DocumentVersion, ReviewRequest, ReviewTask, Outbox, IndexBuild, ModelConfig, User
from app.worker import process_one
from app.security import cipher


def upload(setup,text='1 业务功能\n接口字段新增审核说明',label='V1.0',document_id=None):
    clients,base=setup
    client=clients['member'][0]
    data={'title':'测试需求资产','base_id':base,'label':label}
    if document_id:
        data['document_id']=document_id
    response=client.post('/documents/upload',data=data,files={'file':('需求.md',text.encode(),'text/markdown')})
    assert response.status_code==200,response.text
    version=response.json()
    assert process_one()
    detail=client.get(f"/documents/{version['document_id']}/versions/{version['id']}").json()
    assert detail['parse_status']=='ready',detail
    return detail


def submit(setup,version):
    clients,_=setup
    response=clients['member'][0].post(f"/versions/{version['id']}/submit",json={'reviewer_ids':[clients['review_a'][1],clients['review_b'][1]],'note':'测试会签'})
    assert response.status_code==200,response.text
    request=response.json()
    tasks=clients['member'][0].get('/reviews/'+request['id']).json()['tasks']
    return request,tasks


def approve(setup,task,comment='同意'):
    clients,_=setup
    name='review_a' if task['reviewer_id']==clients['review_a'][1] else 'review_b'
    return clients[name][0].post('/review-tasks/'+task['id']+'/decision',json={'decision':'approved','comment':comment})


def publish(setup,version):
    _,tasks=submit(setup,version)
    assert approve(setup,tasks[0]).status_code==200
    assert approve(setup,tasks[1]).status_code==200
    assert process_one()


def test_registration_csrf_and_roles(setup):
    clients,_=setup
    member=clients['member'][0]
    assert member.get('/admin/users').status_code==403
    assert member.post('/review-tasks/missing/decision',json={'decision':'approved'}).status_code==403
    assert member.post('/auth/register',json={'username':'attack','display_name':'x','password':'Test_password123','confirm_password':'Test_password123','role':'super_admin'}).status_code==422
    assert TestClient_no_csrf().post('/auth/login',json={'username':'x','password':'x'}).status_code==403
    response=member.post('/conversations',headers={'Origin':'https://evil.example'})
    assert response.status_code==403
    assert clients['admin'][0].patch('/admin/users/'+clients['admin'][1],json={'enabled':False}).status_code==409


def TestClient_no_csrf():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_historical_time_retrieval_uses_publication_event(setup):
    clients,_=setup
    first=upload(setup,text='历史业务术语 旧版本规则')
    publish(setup,first)
    cutoff=datetime.now(timezone.utc).isoformat()
    second=upload(setup,text='历史业务术语 新版本规则',label='V2.0',document_id=first['document_id'])
    publish(setup,second)
    member=clients['member'][0]
    current=member.get('/search',params={'q':'历史业务术语'}).json()
    historical=member.get('/search',params={'q':'历史业务术语','as_of':cutoff}).json()
    assert current[0]['document_version_id']==second['id']
    assert historical[0]['document_version_id']==first['id']
    assert historical[0]['current'] is False
    assert member.get('/search',params={'q':'历史业务术语','as_of':cutoff,'version_id':first['id']}).status_code==422


def test_word_export_keeps_markdown_table_rows_and_trace(setup):
    clients,_=setup
    version=upload(setup,text='# 核心功能需求\n| 字段 | 规则 |\n|---|---|\n| 状态 | 保留 |\n| 备注 | 人工确认 |\n\n## 验收标准\n验证记录')
    response=clients['member'][0].get('/versions/'+version['id']+'/export')
    word=Word(io.BytesIO(response.content))
    assert len(word.tables)==2
    assert len(word.tables[1].rows)==3
    assert word.tables[1].cell(2,1).text=='人工确认'
    assert word.tables[1].rows[0]._tr.trPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblHeader') is not None


def test_parallel_review_publication(setup):
    clients,_=setup
    version=upload(setup)
    req,tasks=submit(setup,version)
    assert approve(setup,tasks[0]).status_code==200
    assert clients['member'][0].get('/search',params={'q':'接口字段'}).json()==[]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.kind=='publish'))==0
    assert approve(setup,tasks[1]).status_code==200
    assert approve(setup,tasks[1]).status_code==409
    assert process_one()
    result=clients['other'][0].get('/search',params={'q':'接口字段'}).json()
    assert result and result[0]['document_version_id']==version['id']
    with SessionLocal() as db:
        doc=db.get(Document,version['document_id'])
        assert doc.current_version_id==version['id']
        assert db.get(IndexBuild,doc.current_index_id).status=='ready'


def test_publish_falls_back_after_partial_vector_batch_and_reindex_restores_vectors(setup,monkeypatch):
    monkeypatch.setattr(settings,'embedding_dimensions',3)
    version=upload(setup,text='互斥校验\n\n'+('业务规则。'*5000))
    with SessionLocal() as db:
        config=ModelConfig(name='测试向量',kind='embedding',base_url='https://model.invalid/v1',
                           model='test-embedding',encrypted_key=cipher().encrypt(b'test-key').decode())
        db.add(config)
        db.flush()
        config_id=config.id
        db.commit()

    batch_sizes=[]
    def provider(request):
        assert request.url.path=='/v1/embeddings'
        texts=json.loads(request.content)['input']
        batch_sizes.append(len(texts))
        if len(batch_sizes)==2:
            return httpx.Response(404,json={'error':{'message':'fixture provider error'}})
        return httpx.Response(200,json={'data':[
            {'index':i,'embedding':[0.2,0.4,0.6]} for i in range(len(texts))
        ]})

    real_client=httpx.Client
    transport=httpx.MockTransport(provider)
    member=setup[0]['member'][0]
    with patch('app.services.ai.httpx.Client',side_effect=lambda **kw:real_client(transport=transport,**kw)):
        publish(setup,version)
        assert batch_sizes[0]==32 and len(batch_sizes)==2
        with SessionLocal() as db:
            doc=db.get(Document,version['document_id'])
            build=db.get(IndexBuild,doc.current_index_id)
            saved=db.get(DocumentVersion,version['id'])
            assert saved.review_status=='approved' and saved.publish_status=='published' and saved.index_status=='ready'
            assert build.status=='ready' and build.embedding_model=='text-only' and build.model_config_id is None
            chunks=db.scalars(select(Chunk).where(Chunk.build_id==build.id)).all()
            assert len(chunks)==build.chunks>32 and all(chunk.embedding is None for chunk in chunks)
            fallback=db.scalar(select(Audit).where(Audit.action=='index.embedding_fallback',Audit.resource_id==version['id']))
            assert fallback.detail=={'index_build_id':build.id,'embedding_model':'test-embedding','reason':'Embedding 调用失败 HTTP 404'}
            job=db.scalar(select(Outbox).where(Outbox.kind=='publish',Outbox.resource_id==version['id']))
            assert job.status=='completed' and job.error==''
            fallback_build_id=build.id
        result=member.get('/search',params={'q':'互斥校验'}).json()
        assert result[0]['document_version_id']==version['id'] and len(batch_sizes)==2

        assert member.post('/documents/'+version['document_id']+'/reindex').status_code==200
        assert process_one()
        with SessionLocal() as db:
            doc=db.get(Document,version['document_id'])
            build=db.get(IndexBuild,doc.current_index_id)
            assert doc.current_version_id==version['id'] and build.id!=fallback_build_id
            assert build.status=='ready' and build.model_config_id==config_id
            assert db.scalar(select(Chunk).where(Chunk.build_id==build.id)).embedding==[0.2,0.4,0.6]


def test_no_indexable_text_still_fails_publication(setup):
    version=upload(setup)
    with patch('app.services.publishing.chunks_for',return_value=[]):
        publish(setup,version)
    with SessionLocal() as db:
        saved=db.get(DocumentVersion,version['id'])
        assert saved.review_status=='approved' and saved.publish_status=='failed' and saved.index_status=='failed'
        assert db.get(Document,version['document_id']).current_index_id is None
        assert not db.scalar(select(Audit.id).where(Audit.action=='index.embedding_fallback'))


def test_concurrent_last_decisions_one_job(setup):
    version=upload(setup)
    _,tasks=submit(setup,version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda task:approve(setup,task),tasks))
    assert [r.status_code for r in responses]==[200,200]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.kind=='publish'))==1
    process_one()
    assert not process_one()


def test_return_cancels_round_and_new_revision(setup):
    clients,_=setup
    version=upload(setup)
    req,tasks=submit(setup,version)
    task=next(t for t in tasks if t['reviewer_id']==clients['review_a'][1])
    url='/review-tasks/'+task['id']+'/decision'
    assert clients['review_a'][0].post(url,json={'decision':'returned','comment':''}).status_code==422
    assert clients['review_a'][0].post(url,json={'decision':'returned','comment':'缺少验收标准'}).status_code==200
    other=next(t for t in tasks if t['id']!=task['id'])
    assert approve(setup,other).status_code==409
    assert clients['member'][0].patch('/versions/'+version['id'],json={'content':'改稿','expected_revision':1}).status_code==403
    response=clients['member'][0].post(f"/documents/{version['document_id']}/versions",json={'label':'V1.1','source_version_id':version['id'],'content':'新增验收标准'})
    assert response.status_code==200
    _,new_tasks=submit(setup,response.json())
    assert all(t['decision']=='pending' for t in new_tasks)


def test_draft_isolation_and_assigned_review_only(setup):
    clients,_=setup
    version=upload(setup)
    path=f"/documents/{version['document_id']}/versions/{version['id']}"
    assert clients['other'][0].get(path).status_code==404
    assert clients['other'][0].get('/versions/'+version['id']+'/download').status_code==404
    assert clients['review_a'][0].get(path).status_code==404
    _,tasks=submit(setup,version)
    assert clients['review_a'][0].get(path).status_code==200
    task_b=next(t for t in tasks if t['reviewer_id']==clients['review_b'][1])
    assert clients['review_a'][0].post('/review-tasks/'+task_b['id']+'/decision',json={'decision':'approved'}).status_code==404
    assert clients['admin'][0].post('/review-tasks/'+task_b['id']+'/decision',json={'decision':'approved'}).status_code==404


def test_version_switch_diff_restore_snapshot(setup):
    clients,base=setup
    member=clients['member'][0]
    admin=clients['admin'][0]
    v1=upload(setup,'旧版字段甲\n保留段落')
    publish(setup,v1)
    s1=admin.post(f'/knowledge-bases/{base}/snapshots',json={'name':'Snapshot-001'}).json()
    v2=upload(setup,'新版字段乙\n保留段落','V1.1',v1['document_id'])
    _,tasks=submit(setup,v2)
    assert member.get('/search',params={'q':'旧版字段甲'}).json()[0]['document_version_id']==v1['id']
    delta=member.get(f"/documents/{v1['document_id']}/diff",params={'left':v1['id'],'right':v2['id']}).json()
    assert any(d['kind']=='replace' for d in delta)
    for task in tasks:
        approve(setup,task)
    process_one()
    assert member.get('/search',params={'q':'新版字段乙'}).json()[0]['document_version_id']==v2['id']
    s2=admin.post(f'/knowledge-bases/{base}/snapshots',json={'name':'Snapshot-002'}).json()
    change=admin.get(f'/knowledge-bases/{base}/snapshot-diff',params={'left':s1['id'],'right':s2['id']}).json()
    assert change['documents']['updated'][v1['document_id']]['left']==v1['id']
    historical=member.get('/search',params={'q':'旧版字段甲','snapshot_id':s1['id']}).json()
    assert historical[0]['document_version_id']==v1['id']
    restored=member.post(f"/documents/{v1['document_id']}/restore-draft",json={'label':'V1.2','source_version_id':v1['id'],'change_note':'恢复旧版本'}).json()
    assert restored['status']=='draft' and restored['content']==v1['content']
    assert admin.get(f'/knowledge-bases/{base}/snapshots/'+s1['id']).json()['manifest']==s1['manifest']


def test_index_failure_keeps_previous_and_retry(setup):
    clients,_=setup
    v1=upload(setup,'有效旧版规则')
    publish(setup,v1)
    v2=upload(setup,'新规则更新','V1.1',v1['document_id'])
    _,tasks=submit(setup,v2)
    for task in tasks:
        approve(setup,task)
    with SessionLocal() as db:
        config=ModelConfig(name='test-only',base_url='http://test.invalid/v1',model='test-only',kind='embedding',encrypted_key=cipher().encrypt(b'test-only-key').decode())
        db.add(config)
        db.commit()
    with patch('app.services.publishing.embeddings',side_effect=RuntimeError('测试：索引服务失败')):
        process_one()
    with SessionLocal() as db:
        assert db.get(Document,v1['document_id']).current_version_id==v1['id']
        build=db.scalar(select(IndexBuild).where(IndexBuild.version_id==v2['id']))
        assert build.status=='failed'
        build_id=build.id
        config=db.scalar(select(ModelConfig))
        config.enabled=False
        db.commit()
    member=clients['member'][0]
    assert member.get('/search',params={'q':'有效旧版规则'}).json()[0]['document_version_id']==v1['id']
    assert member.post('/index-builds/'+build_id+'/retry').status_code==200
    process_one()
    with SessionLocal() as db:
        assert db.get(Document,v1['document_id']).current_version_id==v2['id']


def test_optimistic_edit_and_export(setup):
    clients,_=setup
    v=upload(setup)
    member=clients['member'][0]
    assert member.patch('/versions/'+v['id'],json={'content':'# 需求背景\n业务目标\n## 功能\n验收标准','expected_revision':1}).status_code==200
    assert member.patch('/versions/'+v['id'],json={'content':'旧提交','expected_revision':1}).status_code==409
    response=member.get('/versions/'+v['id']+'/export')
    assert response.status_code==200
    doc=Word(io.BytesIO(response.content))
    assert any('草稿' in p.text for p in doc.paragraphs)
    assert any(p.style.name=='Heading 1' for p in doc.paragraphs)
    assert doc.sections[0].page_width.inches==pytest.approx(8.5)


def test_ledger_duplicate_numbers_and_confirmed_import(setup):
    clients,_=setup
    wb=Workbook()
    wb.active.append(['需求编号','需求名称','澄清结果','备注'])
    wb.active.append(['RM_001','第一次','澄清结束','=HYPERLINK("evil")'])
    wb.active.append(['RM_001','第二次','需要二次澄清','原文'])
    wb.active.append(['RM_002','唯一编号','澄清结束','有效台账'])
    stream=io.BytesIO()
    wb.save(stream)
    member=clients['member'][0]
    assert member.post('/clarification/import',files={'file':('计划.xlsx',stream.getvalue(),'application/octet-stream')}).status_code==409
    preview=member.post('/clarification/import-preview',files={'file':('计划.xlsx',stream.getvalue())}).json()
    imported=member.post('/clarification/import',data={'expected_snapshot':preview['snapshot']},files={'file':('计划.xlsx',stream.getvalue())})
    assert imported.status_code==200,imported.text
    assert imported.json()['conflicts']==2 and imported.json()['added']==1
    tasks=member.get('/clarification/tasks').json()
    assert len(tasks)==1 and tasks[0]['requirement_id']
    assert len(member.get('/requirements').json())==1
    response=member.get('/clarification/export')
    exported=load_workbook(io.BytesIO(response.content))
    assert exported.active.max_row==2
    public=clients['other'][0].get('/clarification/tasks').json()
    assert len(public)==1 and all(not row['can_edit'] for row in public)


def test_no_fake_ai_and_personal_skill_isolation(setup):
    clients,_=setup
    member=clients['member'][0]
    conversation=member.post('/conversations').json()
    assert member.post('/conversations/'+conversation['id']+'/messages',json={'content':'请分析'}).status_code==503
    skill=member.post('/skills',json={'name':'个人技能','command':'/个人','description':'测试'}).json()
    assert clients['other'][0].get('/skills/'+skill['id']+'/versions').status_code==404
    assert member.post('/skills/'+skill['id']+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'分析'}).status_code==503
    assert member.post('/skills',json={'name':'越权公共','command':'/越权','description':'x','public':True}).status_code==403
    assert clients['other'][0].get('/conversations/'+conversation['id']+'/messages').status_code==404


def test_private_base_search_and_snapshots_are_scoped(setup):
    clients,_=setup
    admin=clients['admin'][0]
    private=admin.post('/knowledge-bases',json={'name':'私有库','public':False,'member_ids':[clients['member'][1]]}).json()
    assert clients['other'][0].get('/search',params={'q':'test','base_id':private['id']}).status_code==404
    snapshot=admin.post('/knowledge-bases/'+private['id']+'/snapshots',json={'name':'private'}).json()
    assert clients['other'][0].get('/search',params={'q':'test','snapshot_id':snapshot['id']}).status_code==404
