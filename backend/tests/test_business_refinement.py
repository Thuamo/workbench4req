"""Business-flow contracts, isolated DB and mocked providers only."""
import io,json
from unittest.mock import patch
from sqlalchemy import select
from docx import Document as Word
from docx.shared import Cm
from conftest import ready_source
from test_document_workspace import open_saved,tree
from app.db import SessionLocal
from app.models import Skill,SkillVersion,AgentRun,DocumentVersion,Document,ModelConfig,Message,Audit,ClarificationTask
from app.security import cipher,digest
from app.services.delivery import SRS_TEMPLATE
from app.services.files import store
from app.services.export import export_docx
from app.services.capabilities import install
from app.worker import process_one

def test_business_identity_and_public_ledger_link_permissions(setup):
    clients,_=setup;m=clients['member'][0];other=clients['other'][0]
    data={'number':'RM_00053002','title':'澄清台账','tags':{'系统':['信贷'],'项目':['A']}}
    req=m.post('/requirements',json=data).json()
    assert m.post('/requirements',json={**data,'number':'rm-00053002'}).status_code==409
    assert m.post('/requirements',json={**data,'tags':{'系统':['信贷'],'项目':['B']}}).status_code==200
    row=m.post('/clarification/tasks',json={'fields':{'需求编号':'00053002','需求名称':'同一需求的原表行'}}).json()
    assert row['requirement_id'] is None
    r=m.put('/clarification/tasks/'+row['id']+'/requirement',json={'requirement_id':req['id'],'expected_revision':row['revision']})
    assert r.status_code==200,r.text
    assert len(m.get('/clarification/tasks/'+row['id']+'/requirement-candidates').json())==2
    assert other.put('/clarification/tasks/'+row['id']+'/requirement',json={'requirement_id':None,'expected_revision':r.json()['revision']}).status_code==404
    assert m.put('/clarification/tasks/'+row['id']+'/requirement',json={'requirement_id':None,'expected_revision':row['revision']}).status_code==409
    with SessionLocal() as db:assert db.get(ClarificationTask,row['id']).requirement_id==req['id']

def test_block_proposal_history_restore_and_refinement_preserve_other_blocks(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    original=w['content_json']['content'][0]
    request={'mode':'modify','expected_revision':w['revision'],'instruction':'补充异常规则','block_from':1,'block_to':2}
    with patch('app.routes.document_workspaces.complete',return_value=('建议段落',{})):
        p=member.post(path+'/assistant',json=request).json()['proposal']
    assert p['detail']['scope']=='blocks' and '需求背景' not in p['before_content']
    assert member.get(path).json()['content']==w['content']
    fragment={'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'人工调整后的建议'}]}]}
    diff=member.post(path+'/proposals/'+p['id']+'/diff',json={'content_json':fragment}).json()
    assert any(d['kind']!='equal' for d in diff)
    assert member.put(path+'/proposals/'+p['id'],json={'content_json':fragment}).status_code==200
    with patch('app.routes.document_workspaces.complete',return_value=('第二轮建议',{})) as model:
        refined=member.post(path+'/assistant',json={**request,'proposal_id':p['id'],'instruction':'进一步精简'}).json()['proposal']
        assert '人工调整后的建议' in model.call_args[0][2][-1]['content']
    assert refined['detail']['scope']=='blocks' and refined['before_content']==p['before_content']
    applied=member.post(path+'/proposals/'+refined['id']+'/apply',json={'expected_revision':w['revision'],'content_json':fragment,'confirm':True}).json()['workspace']
    assert applied['content_json']['content'][0]==original
    assert '人工调整后的建议' in applied['content']
    assert member.post(path+'/proposals/'+p['id']+'/apply',json={'expected_revision':applied['revision'],'content_json':tree('过期'),'confirm':True}).status_code==409
    history=member.get(path+'/history').json();assert len(history)==2
    restored=member.post(path+'/restore-proposal/'+history[-1]['id'],json={'expected_revision':applied['revision']}).json()
    assert restored['detail']['kind']=='history_restore'
    assert member.get(path).json()['content']==applied['content']
    assert setup[0]['other'][0].get(path+'/history').status_code==404
    assert member.post(path+'/assistant',json={**request,'expected_revision':applied['revision'],'block_to':10000}).status_code==422

def test_fixed_template_skips_outline_gate_but_keeps_human_document_confirmation(setup):
    clients,base=setup;member=clients['member'][0];source=ready_source(setup)
    with SessionLocal() as db:
        db.add(ModelConfig(name='fixture',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'fixture').decode()))
        sid=db.scalar(select(Skill.id).where(Skill.command=='/软需生成'));db.commit()
    run=member.post('/skills/'+sid+'/execute',json={'task':'梳理测试业务证据','source_version_ids':[source],'fixed_template':True}).json()
    def model(db,owner,messages,**kwargs):
        payload=json.loads(messages[-1]['content'])
        return json.dumps({'answer':'待确认业务口径','citations':[source]},ensure_ascii=False),{}
    with patch('app.services.agents.complete',side_effect=model):process_one()
    result=member.get('/agent-runs/'+run['id']).json()
    assert result['status']=='completed',result
    assert result['result']['outline']==SRS_TEMPLATE['outline']
    assert len(result['result']['sections'])==len(SRS_TEMPLATE['outline'])
    assert not result['business_completed'] and not result['result'].get('saved_version_id')
    assert result['result']['retrieval_meta']['retrieval']
    assert result['citations'][0]['document_version_id']==source

def test_skill_catalog_idempotence_and_template_validation(setup):
    admin=setup[0]['admin'][0]
    with SessionLocal() as db:
        before=list(db.scalars(select(SkillVersion.id)).all());assert install(db)==[];db.commit()
        assert list(db.scalars(select(SkillVersion.id)).all())==before
        assert db.scalar(select(Skill).where(Skill.command=='/需求解析'))
        assert db.scalar(select(Skill).where(Skill.command=='/软需质检'))
    response=admin.post('/skills',json={'name':'模板测试','command':'/模板测试','description':'测试','config':{'workflow':'specification','delivery_template':{'version':'1','outline':[]}}})
    assert response.status_code==422

def test_docx_inherits_layout_and_header_without_sample_body(setup):
    owner=setup[0]['member'][1];base=setup[1]
    template=Word();template.sections[0].page_width=Cm(19);template.sections[0].header.paragraphs[0].text='测试交付页眉'
    template.add_paragraph('这是模板样例业务，禁止复制');buf=io.BytesIO();template.save(buf)
    with SessionLocal() as db:
        doc=Document(owner_id=owner,base_id=base,title='版式模板',kind='template');db.add(doc);db.flush()
        v=DocumentVersion(document_id=doc.id,creator_id=owner,label='V1',filename='template.docx',file_hash=store(buf.getvalue()),content='模板示例',parse_status='ready');db.add(v);db.flush()
        output=DocumentVersion(document_id=doc.id,creator_id=owner,label='V2',filename='out.md',file_hash='fixture',content='# 业务规则\n\n本次实际业务正文',provenance={'word_template_version_id':v.id})
        db.add(output);db.commit();result=export_docx(doc,output)
    rendered=Word(io.BytesIO(result))
    # Word stores dimensions in integer twips; compare serialized dimensions.
    assert rendered.sections[0].page_width==Word(io.BytesIO(buf.getvalue())).sections[0].page_width
    assert '测试交付页眉' in rendered.sections[0].header.paragraphs[0].text
    text='\n'.join(p.text for p in rendered.paragraphs)
    assert '本次实际业务正文' in text and '禁止复制' not in text

def test_save_chat_analysis_cas_and_idempotence(setup):
    member=setup[0]['member'][0];owner=setup[0]['member'][1]
    req=member.post('/requirements',json={'number':'CHAT-1','title':'分析归档'}).json()
    conv=member.post('/conversations').json()
    with SessionLocal() as db:
        m=Message(conversation_id=conv['id'],role='assistant',content='有依据的分析与待确认事项',citations=[{'title':'业务证据','document_version_id':'fixture'}]);db.add(m);db.flush();mid=m.id;db.commit()
    data={'requirement_id':req['id'],'expected_revision':req['revision'],'message_id':mid}
    r=member.post('/conversations/'+conv['id']+'/save-analysis',json=data);assert r.status_code==200,r.text
    assert r.json()['description'].count('有依据的分析')==1
    assert member.post('/conversations/'+conv['id']+'/save-analysis',json=data).json()['description'].count('有依据的分析')==1
    assert setup[0]['other'][0].post('/conversations/'+conv['id']+'/save-analysis',json=data).status_code==404
    with SessionLocal() as db:
        db.get(Message,mid).generation_status='stopped';db.commit()
    assert member.post('/conversations/'+conv['id']+'/save-analysis',json=data).status_code==409

def test_confirmed_analysis_reused_only_while_evidence_unchanged(setup):
    member=setup[0]['member'][0];vid=ready_source(setup)
    requirement=member.post('/requirements',json={'number':'REUSE-1','title':'测试业务证据'}).json()
    with SessionLocal() as db:
        db.add(ModelConfig(name='fixture',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'fixture').decode()))
        skill=db.scalar(select(Skill).where(Skill.command=='/需求解析'));sid=skill.id;db.commit()
    data={'task':'测试业务证据','source_version_ids':[vid],'requirement_id':requirement['id']}
    def model(*args,**kwargs):return json.dumps({'items':[{'description':'测试需求'}],'answer':'测试分析','citations':[vid]},ensure_ascii=False),{}
    with patch('app.services.agents.complete',side_effect=model):
        first=member.post('/skills/'+sid+'/execute',json=data).json();process_one()
        assert member.post('/processing-tasks/'+first['id']+'/confirm-analysis').status_code==200
        assert member.get('/processing-tasks/'+first['id']).json()['business_completed']
        second=member.post('/skills/'+sid+'/execute',json=data).json();process_one()
        result=member.get('/agent-runs/'+second['id']).json()
        assert result['result']['reused_from']['analysis']==first['id']
        with SessionLocal() as db:db.get(DocumentVersion,vid).content='来源规则已经变化';db.commit()
        third=member.post('/skills/'+sid+'/execute',json=data).json();process_one()
        assert not member.get('/agent-runs/'+third['id']).json()['result'].get('reused_from')

def test_export_preview_access_and_errors_do_not_modify_document(setup):
    member,_,_,_,path,w,_=open_saved(setup)
    version=member.post(path+'/confirm',json={'expected_revision':w['revision']}).json()
    with patch('app.services.export_preview.render',return_value=(b'%PDF-test',{'pages':2,'warnings':[]})):
        r=member.post('/versions/'+version['id']+'/export-preview')
        assert r.status_code==200 and r.headers['x-export-pages']=='2'
        assert setup[0]['other'][0].post('/versions/'+version['id']+'/export-preview').status_code==404
    assert member.get(path).json()['revision']==w['revision']

def test_quality_report_creates_repair_proposal_without_applying_and_rejects_changed_draft(setup):
    member,_,_,_,path,w,draft=open_saved(setup)
    version=member.post(path+'/confirm',json={'expected_revision':w['revision']}).json()
    with SessionLocal() as db:
        skill=db.scalar(select(Skill).where(Skill.command=='/软需质检'))
        run=AgentRun(owner_id=setup[0]['member'][1],skill_version_id=skill.current_version_id,status='completed',inputs={'task':'核查软需','source_version_ids':[version['id']]},result={'review':{'answer':'异常规则缺少依据，请标为待确认'}})
        db.add(run);db.flush();rid=run.id;db.commit()
    with patch('app.routes.document_workspaces.complete',return_value=('修改建议，待确认规则',{})):
        response=member.post('/processing-tasks/'+rid+'/repair-proposal',json={'version_id':version['id']})
        assert response.status_code==200,response.text
    assert member.get(path).json()['content']==w['content']
    assert member.post('/processing-tasks/'+rid+'/repair-proposal',json={'version_id':'unrelated'}).status_code==422
    member.put(path,json={**draft,'expected_revision':w['revision'],'content_json':tree('新的人工草稿')})
    with patch('app.routes.document_workspaces.complete',side_effect=AssertionError('不得对已变动草稿调用修复')):
        assert member.post('/processing-tasks/'+rid+'/repair-proposal',json={'version_id':version['id']}).status_code==409
