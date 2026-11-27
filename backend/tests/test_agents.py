from conftest import ready_source
from datetime import timedelta
import json
from unittest.mock import Mock, patch
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ModelConfig, AgentRun, Skill, AgentStep, DocumentVersion, Outbox, User, now
from app.security import cipher
from app.worker import process_one, renew_agent_lease
from app.services.agents import execute


def test_long_agent_task_renews_only_its_own_lease(setup):
    original_deadline = now() + timedelta(seconds=1)
    with SessionLocal() as db:
        job = Outbox(kind='agent', resource_id='lease-fixture', status='running',
                     lease_token='active-token', lease_until=original_deadline)
        db.add(job)
        db.commit()
        job_id = job.id

    renew_agent_lease(job_id, 'old-token', Mock(wait=Mock(side_effect=[False, True])))
    with SessionLocal() as db:
        assert db.get(Outbox, job_id).lease_until == original_deadline

    renew_agent_lease(job_id, 'active-token', Mock(wait=Mock(side_effect=[False, True])))
    with SessionLocal() as db:
        job = db.get(Outbox, job_id)
        assert job.lease_until > original_deadline + timedelta(minutes=55)
        assert job.status == 'running'


def test_langgraph_pause_resume_and_source_trace(setup):
    """Protocol fixtures only; this does not claim a real external model quality check."""
    clients,base=setup
    member=clients['member'][0]
    upload=member.post('/documents/upload',data={'base_id':base,'title':'测试输入','label':'V1.0'},files={'file':('业务.md','测试业务要求：保留处理记录'.encode(),'text/markdown')}).json()
    process_one()
    with SessionLocal() as db:
        model=ModelConfig(name='test-only-protocol-fixture',base_url='https://test.invalid/v1',model='test-only',kind='chat',encrypted_key=cipher().encrypt(b'not-a-real-secret').decode())
        db.add(model)
        skill=db.scalar(select(Skill).where(Skill.command=='/软需生成'))
        skill_id=skill.id
        db.commit()
    requirement=member.post('/requirements',json={'number':'GRAPH-1','title':'业务需求'}).json()
    run=member.post('/skills/'+skill_id+'/execute',json={'requirement_id':requirement['id'],'task':'测试编写软需','source_version_ids':[upload['id']],'base_ids':[base]}).json()

    def protocol_fixture(db,owner,messages,json_output=False,config=None,temperature=0.2,*,read_timeout):
        assert read_timeout is None
        payload=json.loads(messages[-1]['content'])
        instruction=payload['instruction']
        result={'answer':'测试协议返回的业务结果','citations':[upload['id']]}
        if '原子需求' in instruction:
            result={'items':[{'title':'处理记录','description':'保留处理记录','tags':['测试标签'],'source_citation_id':upload['id']}],'citations':[upload['id']]}
        elif instruction.startswith('只在 outline'):
            result={'outline':['需求背景与目标','核心功能需求','验收标准'],'citations':[upload['id']]}
        elif 'questions' in instruction:
            result={'questions':[{'description':'测试待确认问题','reason':'协议测试','source_citation_id':upload['id']}],'citations':[upload['id']]}
        return json.dumps(result,ensure_ascii=False),{'model_config_id':config.id,'model':config.model,'usage':{'total_tokens':0}}

    with patch('app.services.agents.complete',side_effect=protocol_fixture):
        assert process_one()
        paused=member.get('/agent-runs/'+run['id']).json()
        assert paused['status']=='awaiting_confirmation',paused
        assert paused['citations'][0]['document_version_id']==upload['id']
        assert paused['result']['outline']
        candidates=member.post('/agent-runs/'+run['id']+'/save-requirements',json={'selected_indices':[0]})
        assert candidates.status_code==200,candidates.text
        assert len(candidates.json()['requirements'])==1
        assert candidates.json()['requirements'][0]['tags']=={'标签':['测试标签']}
        assert member.post('/agent-runs/'+run['id']+'/resume',json={'approved':True,'outline':['需求背景与目标','核心功能需求','验收标准']}).status_code==200
        # New invocation reconstructs graph and reloads checkpoints, as after worker restart.
        assert process_one()
    completed=member.get('/agent-runs/'+run['id']).json()
    assert completed['status']=='completed',completed
    assert len(completed['result']['sections'])==3
    repeated=member.post('/agent-runs/'+run['id']+'/save-requirements',json={'selected_indices':[0]})
    assert repeated.json()['requirements']==[]
    assert any(s['agent']=='Human' for s in completed['steps'])
    saved=member.post('/agent-runs/'+run['id']+'/save',json={'base_id':base,'title':'测试软需','label':'V1.0'})
    assert saved.status_code==200,saved.text
    assert saved.json()['provenance']['sources'][0]['document_version_id']==upload['id']
    assert saved.json()['status']=='draft'


def test_hallucinated_citation_fails_quality_gate(setup):
    clients,base=setup
    member=clients['member'][0]
    with SessionLocal() as db:
        db.add(ModelConfig(name='test-only',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'test').decode()))
        skill_id=db.scalar(select(Skill).where(Skill.command=='/知识库问答')).id
        db.commit()
    run=member.post('/skills/'+skill_id+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'测试无法检索的业务'}).json()
    with patch('app.services.agents.complete',return_value=(json.dumps({'answer':'test-only','citations':['fabricated-id']}),{})):
        process_one()
    result=member.get('/agent-runs/'+run['id']).json()
    assert result['status']=='failed'
    assert '不存在的来源' in result['error']


def test_impact_candidate_save_is_owned_and_idempotent(setup):
    clients,_=setup
    member=clients['member'][0]
    source=member.post('/requirements',json={'number':'TEST-SOURCE','title':'源需求'}).json()
    target=member.post('/requirements',json={'number':'TEST-TARGET','title':'目标需求'}).json()
    with SessionLocal() as db:
        db.add(ModelConfig(name='test-only',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'test').decode()))
        skill_id=db.scalar(select(Skill).where(Skill.command=='/关联分析')).id
        db.commit()
    run=member.post('/skills/'+skill_id+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'测试影响候选','requirement_id':source['id']}).json()
    with patch('app.services.agents.complete',return_value=(json.dumps({'relations':[{'description':'测试潜在影响','kind':'接口依赖'}]}),{})):
        process_one()
    selected={'selected_indices':[0],'target_id':target['id']}
    saved=member.post('/agent-runs/'+run['id']+'/save-relations',json=selected)
    assert saved.status_code==200,saved.text
    assert saved.json()['relations'][0]['status']=='candidate'
    assert member.post('/agent-runs/'+run['id']+'/save-relations',json=selected).json()['relations']==[]
    assert clients['other'][0].post('/agent-runs/'+run['id']+'/save-relations',json=selected).status_code==404
