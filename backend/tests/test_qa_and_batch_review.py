import json
from unittest.mock import patch
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import (Document,DocumentVersion,Requirement,ReviewRequest,ReviewTask,Notification,
                        Audit,AgentRun,KnowledgeBase,DeletedRecord)
from app.schemas import ChatInput
from app.services.qa import collect,validate_answer,text_index
from app.security import digest
from test_chat_modes_and_reset import model
from test_workbench import upload,publish


def source(setup,number='50059',who='member',label='V1',text='担保公司贷后报告线上化，新增互斥校验。',doc_id=None):
    with SessionLocal() as db:
        uid=setup[0][who][1]
        doc=db.get(Document,doc_id) if doc_id else Document(owner_id=uid,base_id=setup[1],title=number+'-贷后管理')
        if not doc_id: db.add(doc);db.flush()
        version=DocumentVersion(document_id=doc.id,creator_id=uid,label=label,filename=f'{number}-软需{label}.md',file_hash=digest(text),content=text,blocks=[{'kind':'paragraph','locator':'3 规则 / 段落1','text':text}],parse_status='ready')
        db.add(version);db.flush();result={'id':version.id,'document_id':doc.id,'revision':version.revision};db.commit();return result


def collect_for(setup,**kwargs):
    from app.models import User
    with SessionLocal() as db:return collect(db,db.get(User,setup[0]['member'][1]),ChatInput(**kwargs),[])


def test_qa_scope_private_acl_exact_number_and_no_publication_side_effect(setup):
    own=source(setup);foreign=source(setup,who='other');wrong=source(setup,number='52854')
    evidence,meta=collect_for(setup,content='50059需求大致内容是什么',scopes=['mine'])
    assert {c['document_version_id'] for c in evidence}=={own['id']}
    assert all(c['formal'] is False and c['scope']=='mine' for c in evidence)
    assert meta['unreviewed_count']==1
    assert collect_for(setup,content='50059需求内容',scopes=['formal'])[0]==[]
    assert collect_for(setup,content='99999需求内容',scopes=['mine'])[0]==[]
    client=setup[0]['member'][0];model();conv=client.post('/conversations').json()['id']
    assert client.post(f'/conversations/{conv}/messages',json={'content':'查看文件','scopes':['selected'],'version_ids':[foreign['id']]}).status_code==404
    with SessionLocal() as db:
        assert db.get(Document,own['document_id']).current_index_id is None
        assert db.get(DocumentVersion,own['id']).status=='draft'


def test_qa_selected_only_no_other_docs_and_content_cache_refresh(setup):
    own=source(setup);other=source(setup,number='52854',text='完全不同的历史资料')
    evidence,_=collect_for(setup,content='总结附件',scopes=['selected'],version_ids=[own['id']])
    assert {c['document_version_id'] for c in evidence}=={own['id']}
    before=evidence[0]['citation_id']
    with SessionLocal() as db:
        v=db.get(DocumentVersion,own['id']);v.content='最新互斥校验：必须拦截';v.blocks=[];v.revision+=1;db.commit()
    evidence,_=collect_for(setup,content='总结附件',scopes=['selected'],version_ids=[own['id']])
    assert evidence[0]['citation_id']!=before and '必须拦截' in evidence[0]['excerpt']
    assert other['id'] not in json.dumps(evidence)


def test_qa_formal_gate_current_and_retired_source_exclusion(setup):
    version=upload(setup,text='评级推翻规则：提交复核并保留原评级。');publish(setup,version)
    rows,_=collect_for(setup,content='评级推翻规则',scopes=['formal'])
    assert rows and all(r['formal'] for r in rows)
    with SessionLocal() as db:
        # Exercise a document that was already retired by an older version of the application.
        saved=db.get(DocumentVersion,version['id'])
        doc=db.get(Document,saved.document_id)
        saved.status='deprecated'
        doc.current_version_id=None
        doc.current_index_id=None
        db.commit()
    assert collect_for(setup,content='评级推翻规则',scopes=['formal'])[0]==[]


def test_compare_locks_versions_across_assets_and_ambiguity_never_falls_back(setup):
    left=source(setup,'51380',label='V2',text='评级为空时允许提交。')
    right=source(setup,'51380',label='V3',text='评级为空时阻断提交。')
    source(setup,'52854',label='V3',text='完全无关的其他编号')
    rows,meta=collect_for(setup,content='51380需求V2与V3有哪些业务规则变化',qa_mode='compare',scopes=['mine'])
    assert {r['document_version_id'] for r in rows}=={left['id'],right['id']}
    assert meta['coverage']['complete'] and len(meta['comparison_versions'])==2
    source(setup,'51380',label='V3',text='重复上传的V3')
    rows,meta=collect_for(setup,content='51380需求V2与V3有哪些变化',qa_mode='compare',scopes=['mine'])
    assert not rows and len(meta['comparison_candidates'])==3 and '明确选择' in meta['notice']
    rows,meta=collect_for(setup,content='逐条比较',qa_mode='compare',scopes=['selected'],comparison_version_ids=[left['id'],right['id']])
    assert {r['document_version_id'] for r in rows}=={left['id'],right['id']}


def test_compare_coverage_and_unchanged_files_reported(setup):
    left=source(setup,label='V2',text='甲'*130000);right=source(setup,label='V3',text='乙'*130000)
    _,meta=collect_for(setup,content='比较',qa_mode='compare',scopes=['selected'],comparison_version_ids=[left['id'],right['id']])
    assert meta['coverage']['complete'] is False
    with SessionLocal() as db:
        a=db.get(DocumentVersion,left['id']);b=db.get(DocumentVersion,right['id']);b.content=a.content;b.blocks=a.blocks;db.commit()
    rows,meta=collect_for(setup,content='比较',qa_mode='compare',scopes=['selected'],comparison_version_ids=[left['id'],right['id']])
    assert not rows and '相同' in meta['notice']


def test_analysis_reads_owned_records_only_and_preserves_evidence_status(setup):
    with SessionLocal() as db:
        for who in ('member','other'):
            db.add(Requirement(owner_id=setup[0][who][1],number='50059',title=who+'互斥校验',description='新增互斥校验可能影响放款提交。'))
        db.commit()
    rows,_=collect_for(setup,content='互斥校验影响哪些功能',qa_mode='analysis',scopes=['mine'])
    assert rows and all('other' not in r['title'] for r in rows)
    assert any(r.get('record_kind')=='requirement' for r in rows)
    assert all(not r['formal'] for r in rows)
    assert collect_for(setup,content='互斥校验影响哪些功能',qa_mode='analysis',scopes=['formal'])[0]==[]


def test_citation_membership_filter_status_labels_and_untrusted_output():
    rows=[{'citation_id':'a','formal':True,'excerpt':'正式原文规则内容'},{'citation_id':'b','formal':False,'excerpt':'草稿原文规则内容'}]
    raw=json.dumps({'claims':[{'text':'正式规则','kind':'fact','evidence_ids':['a'],'evidence_quotes':[{'citation_id':'a','quote':'正式原文规则'}]},{'text':'草稿规则','kind':'fact','evidence_ids':['b'],'evidence_quotes':[{'citation_id':'b','quote':'草稿原文规则'}]},{'text':'推测影响','kind':'inference','evidence_ids':['a']},{'text':'伪造事实','kind':'fact','evidence_ids':['wrong']},{'text':'无来源断言','kind':'fact','evidence_ids':[]},{'text':'需核实','kind':'verify','evidence_ids':[]}]})
    text,used,warnings=validate_answer(raw,rows,'analysis')
    assert '伪造事实' not in text and '无来源断言' not in text
    assert '未审核资料' in text and '推导，待人工确认' in text and '建议核实' in text
    assert [r['citation_id'] for r in used]==['a','b'] and warnings
    assert validate_answer('Internal Server Error',rows,'knowledge')[1]==[]
    wrong_quote=json.dumps({'claims':[{'kind':'fact','text':'伪造原文','evidence_ids':['a'],'evidence_quotes':[{'citation_id':'a','quote':'从未出现的规则'}]}]})
    assert '伪造原文' not in validate_answer(wrong_quote,rows,'knowledge')[0]


def test_semantic_retrieval_is_acl_filtered_and_degrades_without_losing_lexical_hits(setup):
    from app.models import ModelConfig,IndexBuild,Chunk
    from app.security import cipher
    v=upload(setup,text='评级推翻时需要重新复核原评级。');publish(setup,v)
    with SessionLocal() as db:
        config=ModelConfig(name='embedding-fixture',kind='embedding',base_url='https://test.invalid',model='fixture',encrypted_key=cipher().encrypt(b'not-real').decode())
        db.add(config);db.flush();mid=config.id
        doc=db.get(Document,v['document_id']);build=db.get(IndexBuild,doc.current_index_id);build.model_config_id=mid
        for chunk in db.scalars(select(Chunk).where(Chunk.build_id==build.id)).all():chunk.embedding=[1,0]
        db.commit()
    with patch('app.services.qa.embeddings',return_value=[[1,0]]) as embed:
        rows,meta=collect_for(setup,content='评级推翻',scopes=['formal'])
        assert rows and '语义' in meta['retrieval'] and embed.call_count==1
    with patch('app.services.qa.embeddings',side_effect=RuntimeError('provider secret must not leak')):
        rows,meta=collect_for(setup,content='评级推翻',scopes=['formal'])
        assert rows and any('降级' in w for w in meta['warnings'])
        assert 'secret' not in json.dumps(meta)
    source(setup,text='评级推翻个人资料')
    with patch('app.services.qa.embeddings') as embed:
        rows,meta=collect_for(setup,content='评级推翻',scopes=['mine'])
        assert rows and not embed.called


class QaResponse:
    status_code=200
    def __init__(self,body): self.body=body
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def aiter_lines(self):
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':self.body}}]})
        yield 'data: [DONE]'


class QaClient:
    requests=[]
    def __init__(self,*args,**kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    def stream(self,*args,**kwargs):
        body=kwargs['json'];self.requests.append(body)
        evidence=json.loads(body['messages'][0]['content'].split('本次证据：',1)[1])
        raw=json.dumps({'claims':[{'kind':'fact','text':'资料记载互斥校验规则','evidence_ids':[evidence[0]['citation_id']],'evidence_quotes':[{'citation_id':evidence[0]['citation_id'],'quote':evidence[0]['excerpt']}]},{'kind':'inference','text':'可能影响提交入口','evidence_ids':[evidence[0]['citation_id']]}]})
        return QaResponse(raw)


def test_chat_persists_scope_actual_citations_regenerate_and_history_isolation(setup):
    v=source(setup);model();QaClient.requests=[]
    member=setup[0]['member'][0];conv=member.post('/conversations').json()['id'];path=f'/conversations/{conv}/messages'
    payload={'content':'互斥校验规则是什么','qa_mode':'analysis','scopes':['selected'],'version_ids':[v['id']]}
    with patch('app.routes.chat.httpx.AsyncClient',QaClient):
        response=member.post(path,json=payload);assert response.status_code==200,response.text
        assert '本次回答未通过' not in response.text
        saved=member.get(path).json();assert saved[-1]['retrieval']['qa_mode']=='analysis'
        assert len(saved[-1]['citations'])==1 and saved[-1]['candidate_citations']
        assert '未审核资料' in saved[-1]['content'] and saved[-2]['scopes']==['selected']
        assert member.post(path,json={'content':payload['content'],'regenerate':True,'qa_mode':'knowledge','scopes':['formal']}).status_code==200
        assert '需求分析辅助' in QaClient.requests[-1]['messages'][0]['content']
        # A different scope/mode must not inherit this private-file conversation.
        member.post(path,json={'content':'互斥校验','qa_mode':'knowledge','scopes':['mine']})
        assert all(m['content']!=payload['content'] for m in QaClient.requests[-1]['messages'][1:-1])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun))==0


def test_followup_resolves_previous_subject_with_same_scope_only(setup):
    source(setup);model();QaClient.requests=[]
    member=setup[0]['member'][0];conv=member.post('/conversations').json()['id'];path=f'/conversations/{conv}/messages'
    with patch('app.routes.chat.httpx.AsyncClient',QaClient):
        assert member.post(path,json={'content':'50059的互斥校验规则','scopes':['mine']}).status_code==200
        assert member.post(path,json={'content':'那为空时呢','scopes':['mine']}).status_code==200
    reply=member.get(path).json()[-1]
    assert '50059' in reply['retrieval']['resolved_query']


def test_batch_submit_atomic_validation_duplicates_and_notifications(setup):
    a=source(setup);b=source(setup,'50060');foreign=source(setup,'50061',who='other')
    member=setup[0]['member'][0];reviewer=setup[0]['review_a'][1]
    def body(ids): return {'version_ids':ids,'reviewer_ids':[reviewer],'note':'批量送审'}
    assert member.post('/documents/batch-submit',json=body([a['id'],foreign['id']])).status_code==404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ReviewRequest))==0
        assert db.scalar(select(func.count()).select_from(Notification))==0
        assert db.get(DocumentVersion,a['id']).status=='draft'
    assert member.post('/documents/batch-submit',json=body([a['id'],a['id']])).status_code==422
    stale={**body([a['id'],b['id']]),'expected_revisions':{b['id']:999}}
    assert member.post('/documents/batch-submit',json=stale).status_code==409
    response=member.post('/documents/batch-submit',json=body([a['id'],b['id']]))
    assert response.status_code==200 and response.json()['submitted']==2
    assert member.post('/documents/batch-submit',json=body([a['id'],b['id']])).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ReviewRequest))==2
        assert db.scalar(select(func.count()).select_from(ReviewTask))==2
        assert db.get(DocumentVersion,a['id']).status=='pending_review'
        assert db.get(Document,a['document_id']).current_index_id is None


def test_batch_pending_empty_deleted_and_creator_cannot_review_via_admin(setup):
    a=source(setup,who='review_a');member=setup[0]['member'][0];admin=setup[0]['admin'][0]
    body={'version_ids':[a['id']],'reviewer_ids':[setup[0]['review_a'][1]]}
    assert admin.post('/documents/batch-submit',json=body).status_code==422
    body['reviewer_ids']=[setup[0]['review_b'][1]]
    assert admin.post('/documents/batch-submit',json=body).status_code==200
    b=source(setup,'50060')
    with SessionLocal() as db:db.get(DocumentVersion,b['id']).parse_status='pending';db.commit()
    body['version_ids']=[b['id']]
    assert member.post('/documents/batch-submit',json=body).status_code==409

    with SessionLocal() as db:db.get(DocumentVersion,b['id']).parse_status='ready';db.get(DocumentVersion,b['id']).content=' ';db.commit()
    assert member.post('/documents/batch-submit',json=body).status_code==409


def test_skill_references_are_bounded_text_only_not_executable(setup):
    import io,zipfile
    from app.services.files import store
    from app.services.qa import skill_references
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        archive.writestr('skill/references/rules.md','技能方法参考：逐项核对原表字段。')
        archive.writestr('skill/scripts/run.py','raise RuntimeError("must not execute")')
        archive.writestr('skill/assets/sample.txt','不应作为方法资料读取')
    config={'package_metadata':{'file_hash':store(buffer.getvalue()),'filename':'test.zip'}}
    refs=skill_references(config)
    assert len(refs)==1 and refs[0]['name'].endswith('rules.md') and '技能方法参考' in refs[0]['text']


def test_concurrent_batch_submit_creates_only_one_review_and_deleted_assets_blocked(setup):
    from concurrent.futures import ThreadPoolExecutor
    v=source(setup);client=setup[0]['member'][0]
    payload={'version_ids':[v['id']],'reviewer_ids':[setup[0]['review_a'][1]]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client.post('/documents/batch-submit',json=payload).status_code,range(2)))
    assert sorted(responses)==[200,409]
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(ReviewRequest))==1
    deleted=source(setup,'50060')
    with SessionLocal() as db:
        db.add(DeletedRecord(resource_type='document',resource_id=deleted['document_id'],owner_id=setup[0]['member'][1],deleted_by=setup[0]['member'][1]));db.commit()
    payload['version_ids']=[deleted['id']]
    assert client.post('/documents/batch-submit',json=payload).status_code==409
    assert not collect_for(setup,content='50060需求',scopes=['mine'])[0]
