"""Workspace edits and proposals use isolated SQLite fixtures and no real model calls."""
import io,json,zipfile
from unittest.mock import patch
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import DocumentWorkspace,DocumentVersion,DocumentProposal,DocumentChange,ModelConfig
from app.security import cipher
from test_editing_workflow import fixture_run

def tree(text='人工正文'):
    return {'type':'doc','content':[{'type':'heading','attrs':{'level':1},'content':[{'type':'text','text':'需求背景'}]},{'type':'paragraph','content':[{'type':'text','text':text,'marks':[{'type':'bold'}]}]}]}


def test_duplicate_body_cleanup_is_preview_only_until_confirmed(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    paragraph=lambda text:{'type':'paragraph','content':[{'type':'text','text':text}]}
    heading={'type':'heading','attrs':{'level':2},'content':[{'type':'text','text':'1.1 需求背景'}]}
    body={'type':'doc','content':[paragraph('1.1 需求背景'),paragraph('同一段业务正文'),heading,paragraph('同一段业务正文')]}
    saved=member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':body}).json()
    with patch('app.routes.document_workspaces.complete',side_effect=AssertionError('清理不调用模型')):
        response=member.post(path+'/format-proposal',json={'expected_revision':saved['revision']})
    assert response.status_code==200,response.text
    proposal=response.json()
    assert proposal['detail']['issues']['duplicate_sections']==1
    assert proposal['suggested_content'].count('同一段业务正文')==1
    assert member.get(path).json()['content'].count('同一段业务正文')==2
    applied=member.post(path+'/proposals/'+proposal['id']+'/apply',json={'expected_revision':saved['revision'],'content_json':proposal['preview_json'],'confirm':True})
    assert applied.status_code==200,applied.text
    assert applied.json()['workspace']['content'].count('同一段业务正文')==1

def open_saved(setup):
    member,base,run,requirement=fixture_run(setup)
    w=member.post('/document-workspaces/open',json={'run_id':run})
    assert w.status_code==200,w.text
    w=w.json();path='/document-workspaces/'+w['id']
    draft={'expected_revision':w['revision'],'content_json':tree(),'title':'软件需求说明书','label':'V1.0','base_id':base}
    saved=member.put(path,json=draft)
    assert saved.status_code==200,saved.text
    with SessionLocal() as db:
        db.add(ModelConfig(name='workspace-fixture',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()));db.commit()
    return member,base,run,requirement,path,saved.json(),draft

def assist(member,path,revision,mode='modify'):
    with patch('app.routes.document_workspaces.complete',return_value=('# 需求背景\nAI 建议正文',{'model':'test-only'})):
        r=member.post(path+'/assistant',json={'expected_revision':revision,'mode':mode,'instruction':'补充规则，缺少依据标待确认'})
    assert r.status_code==200,r.text
    return r.json()

def test_workspace_preserves_text_alignment_in_drafts_and_versions(setup):
    member,_,_,_,path,workspace,draft=open_saved(setup)
    body=tree()
    heading,paragraph=body['content']
    heading['attrs']['textAlign']='center'
    paragraph['attrs']={'textAlign':'invalid'}
    payload={**draft,'expected_revision':workspace['revision'],'content_json':body}
    assert member.put(path,json=payload).status_code==422

    paragraph['attrs']['textAlign']='right'
    body['content'].append({'type':'paragraph','attrs':{'textAlign':'left'},'content':[{'type':'text','text':'靠左说明'}]})
    saved=member.put(path,json=payload)
    assert saved.status_code==200,saved.text
    reopened=member.get(path).json()
    assert reopened['content_json']==body
    assert reopened['content']==workspace['content']+'\n\n靠左说明'
    version=member.post(path+'/confirm',json={'expected_revision':saved.json()['revision']})
    assert version.status_code==200,version.text
    assert version.json()['provenance']['rich_text']==body


def test_editable_proposal_apply_discard_and_confirm(setup):
    member,base,run,requirement,path,w,draft=open_saved(setup)
    r=assist(member,path,w['revision'],'ask');assert r['proposal'] is None
    assert member.get(path).json()['content']==w['content']
    p=assist(member,path,w['revision'])['proposal'];pid=p['id']
    assert member.get(path).json()['content']==w['content']
    preview=member.put(path+'/proposals/'+pid,json={'content_json':tree('人工修订 AI 建议')});assert preview.status_code==200
    assert member.get(path).json()['content']==w['content']
    assert setup[0]['other'][0].get(path).status_code==404
    assert member.post(path+'/proposals/'+pid+'/apply',json={'expected_revision':w['revision'],'content_json':tree(),'confirm':False}).status_code==422
    apply=member.post(path+'/proposals/'+pid+'/apply',json={'expected_revision':w['revision'],'content_json':tree('人工修订 AI 建议'),'confirm':True})
    assert apply.status_code==200,apply.text
    w=apply.json()['workspace'];assert '人工修订 AI 建议' in w['content']
    again=member.post(path+'/proposals/'+pid+'/apply',json={'expected_revision':0,'content_json':tree(),'confirm':True});assert again.json()['already_applied']
    assert again.json()['workspace']['content']==w['content']
    p2=assist(member,path,w['revision'])['proposal']
    assert member.post(path+'/proposals/'+p2['id']+'/discard').json()['status']=='discarded'
    assert member.get(path).json()['content']==w['content']
    confirmed=member.post(path+'/confirm',json={'expected_revision':w['revision']});assert confirmed.status_code==200,confirmed.text
    v=confirmed.json();assert v['status']=='draft' and v['requirement_id']==requirement['id']
    assert v['provenance']['rich_text']==tree('人工修订 AI 建议')
    assert member.post(path+'/confirm',json={'expected_revision':w['revision']}).json()['id']==v['id']
    assert member.post('/document-workspaces/open',json={'version_id':v['id']}).json()['id']==w['id']
    assert member.get('/agent-runs/'+run).json()['result']['saved_version_id']==v['id']
    with SessionLocal() as db:
        # Manual saves and confirmed AI changes both belong to draft history.
        assert db.scalar(select(func.count()).select_from(DocumentChange))==2
        assert db.scalar(select(func.count()).select_from(DocumentChange).where(DocumentChange.proposal_id.is_not(None)))==1

def test_stale_proposal_and_revision_conflicts(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    p=assist(member,path,w['revision'])['proposal']
    edited=member.put(path,json={**draft,'content_json':tree('更新的人工正文'),'expected_revision':w['revision']}).json()
    r=member.post(path+'/proposals/'+p['id']+'/apply',json={'expected_revision':edited['revision'],'content_json':tree('旧建议'),'confirm':True})
    assert r.status_code==409
    assert member.get(path).json()['content']==edited['content']
    assert member.put(path,json={**draft,'content_json':tree('过期页面')}).status_code==409
    assert member.post(path+'/assistant',json={'expected_revision':w['revision'],'mode':'ask','instruction':'测试'}).status_code==409

def test_edit_during_ai_call_marks_proposal_stale_and_work_items_resume_editor(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    def model(*args,**kwargs):
        updated=member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':tree('AI 生成期间的人工修改')})
        assert updated.status_code==200,updated.text
        return '过期的 AI 结果',{'model':'fixture'}
    with patch('app.routes.document_workspaces.complete',side_effect=model):
        r=member.post(path+'/assistant',json={'expected_revision':w['revision'],'mode':'modify','instruction':'补充规则'})
    assert r.status_code==200,r.text
    assert r.json()['proposal']['status']=='stale'
    assert 'AI 生成期间的人工修改' in member.get(path).json()['content']
    items=member.get('/work-items').json()
    assert any(item['stage']=='editing' and item['destination']['page']=='editor' for item in items)

def test_reviewed_version_immutable_and_new_revision(setup):
    member,base,run,_,path,w,draft=open_saved(setup)
    v=member.post(path+'/confirm',json={'expected_revision':w['revision']}).json()
    reviewers=[setup[0]['review_a'][1],setup[0]['review_b'][1]]
    assert member.post('/versions/'+v['id']+'/submit',json={'reviewer_ids':reviewers}).status_code==200
    saved=member.put(path,json={**draft,'expected_revision':w['revision'],'label':'V1.1','content_json':tree('新修订内容')})
    assert saved.status_code==200,saved.text
    revised=member.post(path+'/confirm',json={'expected_revision':saved.json()['revision']})
    assert revised.status_code==200,revised.text
    assert revised.json()['parent_id']==v['id']
    with SessionLocal() as db:
        old=db.get(DocumentVersion,v['id']);assert old.content==v['content'] and old.status in ('pending_review','in_review')

def test_deleted_document_blocks_workspace_and_other_users_cannot_create(setup):
    member,_,run,_,path,w,_=open_saved(setup)
    v=member.post(path+'/confirm',json={'expected_revision':w['revision']}).json()
    assert setup[0]['admin'][0].post('/document-workspaces/open',json={'version_id':v['id']}).status_code==403
    assert member.request('DELETE','/records/agent_run/'+run,json={'confirm':True}).status_code==200
    assert member.post('/document-workspaces/open',json={'version_id':v['id']}).status_code==200
    assert member.request('DELETE','/records/document/'+v['document_id'],json={'confirm':True}).status_code==200
    assert member.get(path).status_code==409

def test_import_preview_requires_workflow_and_never_silently_defaults(setup):
    member=setup[0]['member'][0]
    content=b'---\nname: test-srs\ndescription: test\n---\nGenerate a document.'
    r=member.post('/skills/import-preview',files={'file':('SKILL.md',content)})
    assert r.status_code==200 and r.json()['workflow'] is None
    assert member.post('/skills/import',files={'file':('SKILL.md',content)}).status_code==422
    created=member.post('/skills/import',data={'workflow':'specification'},files={'file':('SKILL.md',content)})
    assert created.status_code==200,created.text
    skill=next(s for s in member.get('/skills').json() if s['id']==created.json()['id']);assert skill['config']['workflow']=='specification'
    assert member.post('/skills/import',data={'workflow':'fake'},files={'file':('SKILL.md',content)}).status_code==422

def test_richtext_validated_and_tables_preserved(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    invalid={'type':'doc','content':[{'type':'text','text':'unsafe','marks':[{'type':'link','attrs':{'href':'javascript:alert(1)'}}]}]}
    assert member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':invalid}).status_code==422
    table={'type':'doc','content':[{'type':'table','content':[{'type':'tableRow','content':[{'type':'tableHeader','content':[{'type':'paragraph','content':[{'type':'text','text':'字段'}]}]}]},{'type':'tableRow','content':[{'type':'tableCell','content':[{'type':'paragraph','content':[{'type':'text','text':'ESG评级'}]}]}]}]}]}
    r=member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':table})
    assert r.status_code==200 and '| ESG评级 |' in r.json()['content']

def test_offline_format_proposal_and_provider_failure_preserve_document(setup):
    from app.services.ai import ModelServiceError
    member,_,_,_,path,w,draft=open_saved(setup)
    bad=tree('人工业务规则[citation_id: fake-source]')
    bad['content'].insert(1,bad['content'][0].copy())
    w=member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':bad}).json()
    with patch('app.routes.document_workspaces.complete',side_effect=ModelServiceError(400,'Arrearage')):
        response=member.post(path+'/assistant',json={'expected_revision':w['revision'],'mode':'modify','instruction':'整理目录'})
    assert response.status_code==503 and response.json()['provider_code']=='Arrearage'
    assert '欠费' in response.json()['detail']
    assert member.get(path).json()['content']==w['content']
    with patch('app.routes.document_workspaces.complete',side_effect=AssertionError('格式整理不得调用模型')):
        p=member.post(path+'/format-proposal',json={'expected_revision':w['revision']}).json()
    assert p['detail']['issues']=={'duplicate_headings':1,'citation_markers':1}
    assert member.get(path).json()['content']==w['content']
    result=member.post(path+'/proposals/'+p['id']+'/apply',json={'expected_revision':w['revision'],'content_json':p['preview_json'],'confirm':True})
    assert result.status_code==200,result.text
    assert 'citation_id' not in result.json()['workspace']['content']
    assert '人工业务规则' in result.json()['workspace']['content']
