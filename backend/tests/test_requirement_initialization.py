from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import patch
from uuid import uuid4

from app.db import SessionLocal
from app.models import Document, DocumentVersion, ModelConfig, RequirementPackSpecification
from app.security import cipher
from app.worker import process_one


def upload_business(member, base, requirement_id, label='V1.0', document_id=None):
    data = {'base_id': base, 'title': '业务需求说明书', 'kind': 'business',
            'requirement_id': requirement_id, 'label': label}
    if document_id:
        data['document_id'] = document_id
    response = member.post('/documents/upload', data=data,
                           files={'file': ('业务需求.md', f'{label} 业务要求：保留处理记录'.encode(), 'text/markdown')})
    assert response.status_code == 200, response.text
    return response.json()


def install_model():
    with SessionLocal() as db:
        db.add(ModelConfig(name='initialization-fixture', base_url='https://test.invalid/v1', model='fixture',
                           kind='chat', encrypted_key=cipher().encrypt(b'fixture').decode()))
        db.commit()


def test_launch_uses_existing_and_uploaded_stage_documents_for_each_new_task(setup):
    clients,base=setup
    member=clients['member'][0]
    requirement=member.post('/requirements',json={'number':'LAUNCH-DOC','title':'任务资料关联'}).json()
    path=f"/requirements/{requirement['id']}"
    pack=member.post(path+'/packs',json={'name':'任务资料包'}).json()
    other_pack=member.post(path+'/packs',json={'name':'其他资料包'}).json()
    stage='clarification'
    stage_path=f"{path}/packs/{pack['id']}/stages/{stage}/documents"
    install_model()

    existing=member.post('/documents/upload',data={'title':'已上传资料','base_id':base},
                         files={'file':('existing.md',b'# Existing requirement','text/markdown')})
    assert existing.status_code==200,existing.text
    existing_id=existing.json()['id']
    assert process_one()
    linked=member.post(stage_path,json={'version_ids':[existing_id]})
    assert linked.status_code==200 and linked.json()['version_ids']==[existing_id]

    uploaded=member.post('/documents/upload',data={
        'title':'新资料','base_id':base,'requirement_id':requirement['id'],'kind':'business',
        'pack_id':pack['id'],'pack_stage':stage,
    },files={'file':('source.py',b'class Example: pass','text/plain')})
    assert uploaded.status_code==200,uploaded.text
    source_ids=[existing_id,uploaded.json()['id']]
    launch={
        'pack_id':pack['id'],'stage':stage,'source_version_ids':source_ids,
        'basic_tasks':['clarification','impact'],'request_id':str(uuid4()),
    }
    assert member.post(path+'/launch-tasks',json=launch).status_code==422
    assert process_one()
    assert member.post(path+'/launch-tasks',json={**launch,'pack_id':other_pack['id']}).status_code==422

    response=member.post(path+'/launch-tasks',json=launch)
    assert response.status_code==200,response.text
    assert response.json()['created_count']==2
    for run_id in response.json()['task_ids'].values():
        task=member.get('/processing-tasks/'+run_id).json()
        assert task['inputs']['source_version_ids']==source_ids
        assert task['pack_id']==pack['id'] and task['pack_stage']==stage
        assert {doc['version']['id'] for doc in task['documents'] if doc['role']=='input'}==set(source_ids)


def test_launch_pack_tasks_is_atomic_and_groups_tasks_by_stage(setup):
    clients,base=setup
    member,owner=clients['member']
    requirement=member.post('/requirements',json={'number':'MULTI-STAGE','title':'跨阶段发起'}).json()
    path=f"/requirements/{requirement['id']}"
    pack=member.post(path+'/packs',json={'name':'跨阶段需求包'}).json()
    pack_path=f"{path}/packs/{pack['id']}"
    install_model()

    source=upload_business(member,base,requirement['id'])
    assert process_one()
    assert member.post(pack_path+'/stages/clarification/documents',json={'version_ids':[source['id']]}).status_code==200
    with SessionLocal() as db:
        doc=Document(owner_id=owner,base_id=base,requirement_id=requirement['id'],title='基线软需',kind='specification')
        db.add(doc)
        db.flush()
        baseline=DocumentVersion(document_id=doc.id,creator_id=owner,filename='baseline.md',label='V1.0',
                                 file_hash='fixture',parse_status='ready',content='处理规则')
        db.add_all([baseline,RequirementPackSpecification(pack_id=pack['id'],document_id=doc.id)])
        db.flush()
        baseline_id=baseline.id
        db.commit()

    def workspace_pack():
        return next(item for item in member.get(path+'/workspace').json()['packs'] if item['id']==pack['id'])

    plan=workspace_pack()['initialization']
    mind_map_id=next(skill['id'] for skill in plan['extra_skills'] if skill['workflow']=='mind_map')
    data={'request_id':str(uuid4()),'stages':[
        {'stage':'clarification','basic_tasks':['impact'],'source_version_ids':[source['id']]},
        {'stage':'specification','basic_tasks':['specification'],'target_system':'测试系统','source_version_ids':[source['id']]},
        {'stage':'consolidation','skill_ids':[mind_map_id],'source_version_ids':[baseline_id]},
    ],'change':{'baseline_version_id':'missing','source_version_ids':[source['id']]}}
    endpoint=pack_path+'/launch-tasks'
    assert member.post(endpoint,json=data).status_code==422
    assert all(not stage['runs'] for stage in workspace_pack()['stages'].values())
    data['change']['baseline_version_id']=baseline_id
    response=member.post(endpoint,json=data)
    assert response.status_code==200,response.text
    task_ids=response.json()['task_ids']
    assert len(task_ids)==4
    assert member.post(endpoint,json=data).json()['task_ids']==task_ids
    expected={'clarification':{task_ids['impact']},
              'specification':{task_ids['specification'],task_ids['specification_change']},
              'consolidation':{task_ids[f'skill:{mind_map_id}']}}
    for name,stage in workspace_pack()['stages'].items():
        assert {run['id'] for run in stage['runs']}==expected[name]


def test_launch_quality_uses_selected_specification_as_target(setup):
    clients,base=setup
    member,owner=clients['member']
    requirement=member.post('/requirements',json={'number':'QUALITY-INIT','title':'软件需求核查'}).json()
    other=member.post('/requirements',json={'number':'QUALITY-OTHER','title':'其他需求'}).json()
    install_model()
    with SessionLocal() as db:
        version_ids=[]
        for item in (requirement,other):
            doc=Document(owner_id=owner,base_id=base,requirement_id=item['id'],title='软件需求说明书',kind='specification')
            db.add(doc);db.flush()
            version=DocumentVersion(document_id=doc.id,creator_id=owner,filename='spec.docx',label='V1.0',
                                    file_hash='fixture',parse_status='ready',content='第一章 处理记录')
            db.add(version);db.flush();version_ids.append(version.id)
        db.commit()
    path=f"/requirements/{requirement['id']}"
    plan=member.get(path+'/workspace').json()['task_initialization']
    assert [version['id'] for version in plan['quality_versions']]==version_ids[:1]
    skill=next(skill for skill in plan['extra_skills'] if skill['workflow']=='quality')
    data={'skill_ids':[skill['id']]}
    for invalid in (None,version_ids[1]):
        assert member.post(path+'/launch-tasks',json={**data,'quality_version_id':invalid}).status_code==422
    response=member.post(path+'/launch-tasks',json={**data,'quality_version_id':version_ids[0]})
    assert response.status_code==200,response.text
    run_id=response.json()['task_ids'][f"skill:{skill['id']}"]

    def model(_db,_owner,messages,**_kwargs):
        payload=json.loads(messages[-1]['content'])
        assert 'quality_target' in payload['instruction']
        assert any(entry['role']=='quality_target' and entry['document_version_id']==version_ids[0]
                   for entry in payload['evidence_untrusted'] if 'role' in entry)
        return json.dumps({'answer':'核查报告'}),{}

    with patch('app.services.agents.complete',side_effect=model):
        assert process_one()
    run=member.get('/processing-tasks/'+run_id).json()
    assert run['status']=='completed',run['error']
    assert run['result']['review']['answer']=='核查报告'


def test_initialization_creates_only_missing_task_kinds_and_preserves_ledger_confirmation(setup):
    clients, base = setup
    member = clients['member'][0]
    requirement = member.post('/requirements', json={
        'number': 'INIT-1', 'title': '记录保留', 'description': '涉及 RM_00053002 和 RM_00053003',
        'tags': {'系统': ['业务系统']}}).json()
    path = f"/requirements/{requirement['id']}"
    source = upload_business(member, base, requirement['id'])

    def workspace():
        return member.get(path + '/workspace').json()

    assert workspace()['task_initialization']['sources'][0]['parse_status'] == 'pending'
    assert member.post(path + '/initialize-tasks', json={}).status_code == 422
    assert process_one()
    install_model()
    skill = next(s for s in member.get('/skills').json() if s['command'] == '/澄清计划')
    existing = member.post(f"/skills/{skill['id']}/execute", json={
        'task': '已有缺口识别', 'requirement_id': requirement['id'], 'source_version_ids': [source['id']],
    })
    assert existing.status_code == 200, existing.text
    assert workspace()['task_initialization']['missing'] == ['impact', 'specification', 'ledger_fill']
    newer = upload_business(member, base, requirement['id'], 'V2.0', source['document_id'])

    def model(_db, _owner, messages, **_kwargs):
        payload = json.loads(messages[-1]['content'])
        instruction = payload['instruction']
        if '列顺序及当前行：' in instruction:
            preview = json.loads(instruction.split('列顺序及当前行：', 1)[1])
            assert preview['number'] == 'INIT-1'
            fields = dict.fromkeys(preview['columns'])
            fields.update({'需求编号': 'INIT-1', '需求名称': '记录保留'})
            result = {'items': [{'fields': fields}]}
        else:
            result = {'answer': '保留处理记录，保存期限待确认。'}
        return json.dumps(result, ensure_ascii=False), {}

    with patch('app.services.agents.complete', side_effect=model):
        assert process_one() and process_one()
        assert workspace()['task_initialization']['suggested_source_id'] == newer['id']
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: member.post(path + '/initialize-tasks', json={}), range(2)))
        assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
        assert sorted(response.json()['created_count'] for response in responses) == [0, 3]
        task_ids = responses[0].json()['task_ids']
        assert task_ids == responses[1].json()['task_ids']
        assert task_ids['clarification'] == existing.json()['id']
        assert set(task_ids) == {'clarification', 'impact', 'specification', 'ledger_fill'}
        assert workspace()['task_initialization']['missing'] == []
        assert {run['id'] for run in workspace()['runs']} == set(task_ids.values())
        for run in workspace()['runs']:
            expected = source['id'] if run['workflow'] == 'clarification' else newer['id']
            assert run['inputs']['source_version_ids'] == [expected]
        assert clients['other'][0].post(path + '/initialize-tasks', json={}).status_code == 404

        assert process_one() and process_one() and process_one()
        ledger = member.get(f"/agent-runs/{task_ids['ledger_fill']}").json()
        assert ledger['status'] == 'completed', ledger['error']
        preview = ledger['result']['ledger_preview']
        assert preview['fields']['需求编号'] == 'INIT-1'
        assert member.get('/clarification/tasks').json() == []
        confirmed = member.post(f"/agent-runs/{task_ids['ledger_fill']}/ledger-confirm", json={
            'revision': preview['revision'], 'fields': preview['fields'], 'confirm': True,
        })
        assert confirmed.status_code == 200, confirmed.text
        assert member.get('/clarification/tasks').json()[0]['requirement_id'] == requirement['id']
        run_id = task_ids['specification']
        saved = member.post(f'/agent-runs/{run_id}/save', json={'base_id': base, 'title': '测试软需', 'label': 'V1.0'})
        assert saved.status_code == 200, saved.text
        assert not process_one()
        assert len(workspace()['runs']) == 4


def test_initialization_requests_ambiguous_inputs_and_resumes_after_outline_confirmation(setup):
    clients, base = setup
    member = clients['member'][0]
    requirement = member.post('/requirements', json={'number': 'INIT-2', 'title': '自定义提纲', 'tags': {'系统': ['甲', '乙']}}).json()
    path = f"/requirements/{requirement['id']}"
    source = upload_business(member, base, requirement['id'])
    upload_business(member, base, requirement['id'])
    assert process_one() and process_one()
    install_model()
    plan = member.get(path + '/workspace').json()['task_initialization']
    assert plan['suggested_source_id'] is None and plan['target_system'] == ''
    assert member.post(path + '/initialize-tasks', json={'source_version_id': source['id']}).status_code == 422
    selected = {'source_version_id': source['id'], 'target_system': '乙', 'fixed_template': False}
    response = member.post(path + '/initialize-tasks', json=selected)
    assert response.status_code == 200, response.text
    assert response.json()['created_count'] == 4
    run_id = response.json()['task_ids']['specification']

    def model(_db, _owner, messages, **_kwargs):
        payload = json.loads(messages[-1]['content'])
        assert payload['target_system'] == '乙'
        instruction = payload['instruction']
        if '列顺序及当前行：' in instruction:
            preview = json.loads(instruction.split('列顺序及当前行：', 1)[1])
            fields = dict.fromkeys(preview['columns'])
            fields.update({'需求编号': 'INIT-2', '需求名称': '自定义提纲'})
            result = {'items': [{'fields': fields}]}
        else:
            result = {'outline': ['核心功能需求']} if instruction.startswith('只在 outline') else {'answer': '保留业务处理记录'}
        return json.dumps(result, ensure_ascii=False), {}

    with patch('app.services.agents.complete', side_effect=model):
        assert process_one() and process_one() and process_one()
        assert member.get(f'/agent-runs/{run_id}').json()['status'] == 'awaiting_confirmation'
        assert member.post(f'/agent-runs/{run_id}/resume', json={'approved': True}).status_code == 200
        assert process_one() and process_one()
        run = member.get(f'/agent-runs/{run_id}').json()
        assert run['status'] == 'completed'
        assert [section['title'] for section in run['result']['sections']] == ['核心功能需求']


def test_launch_mixes_basic_and_extra_skills_and_replays_the_same_submission(setup):
    clients, base = setup
    member = clients['member'][0]
    requirement = member.post('/requirements', json={'number': 'LAUNCH-1', 'title': '批量发起任务'}).json()
    path = f"/requirements/{requirement['id']}"
    source = upload_business(member, base, requirement['id'])
    assert process_one()
    install_model()

    custom = member.post('/skills', json={'name': '专项缺口分析', 'command': '/专项缺口分析',
                         'description': '专项技能', 'config': {'workflow': 'clarification'}})
    assert custom.status_code == 200, custom.text
    custom_id = custom.json()['id']
    skill_catalog = member.get('/skills').json()
    uml_id = next(skill['id'] for skill in skill_catalog if skill['config']['workflow']=='uml')
    qa_id = next(skill['id'] for skill in skill_catalog if skill['config']['workflow']=='qa')
    basic_id = next(skill['id'] for skill in skill_catalog if skill['command']=='/澄清计划')

    def workspace():
        return member.get(path + '/workspace').json()

    extras = {skill['id'] for skill in workspace()['task_initialization']['extra_skills']}
    assert {custom_id, uml_id} <= extras
    assert not {qa_id, basic_id} & extras
    endpoint = path + '/launch-tasks'
    assert clients['other'][0].post(endpoint, json={'basic_tasks': ['impact']}).status_code == 404
    assert member.post(endpoint, json={'basic_tasks': ['impact'], 'skill_ids': [qa_id]}).status_code == 422
    assert member.post(endpoint, json={'basic_tasks': ['impact'], 'skill_ids': [uml_id]}).status_code == 422
    assert workspace()['runs'] == []

    selection = {'basic_tasks': ['impact'], 'skill_ids': [custom_id, uml_id], 'diagram_types': ['sequence'],
                 'source_version_id': source['id'], 'request_id': str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: member.post(endpoint, json=selection), range(2)))
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    assert sorted(response.json()['created_count'] for response in responses) == [0, 3]
    ids = responses[0].json()['task_ids']
    assert ids == responses[1].json()['task_ids']
    state = workspace()
    assert state['task_initialization']['missing'] == ['clarification', 'specification', 'ledger_fill']
    assert {run['id'] for run in state['runs']} == set(ids.values())
    uml_run = next(run for run in state['runs'] if run['id']==ids[f'skill:{uml_id}'])
    assert uml_run['inputs']['diagram_types'] == ['sequence']
    assert uml_run['requirement_skill_task'] is True
    assert member.post(endpoint, json={'basic_tasks': ['impact']}).json()['created_count'] == 0
    assert member.post(endpoint, json={'skill_ids': [custom_id], 'request_id': str(uuid4())}).json()['created_count'] == 1


def test_launch_ppt_skill_can_use_current_requirement_as_its_only_source(setup):
    clients, _ = setup
    member = clients['member'][0]
    requirement = member.post('/requirements', json={'number': 'LAUNCH-PPT', 'title': '需求进度汇报'}).json()
    skill_id = next(skill['id'] for skill in member.get('/skills').json() if skill['config']['workflow']=='ppt_report')
    install_model()
    response = member.post(f"/requirements/{requirement['id']}/launch-tasks", json={'skill_ids': [skill_id]})
    assert response.status_code == 200, response.text
    run_id = response.json()['task_ids'][f'skill:{skill_id}']
    run = member.get(f'/agent-runs/{run_id}').json()
    assert run['inputs']['source_version_ids'] == []
    assert run['inputs']['report_requirement_ids'] == [requirement['id']]
    assert run['inputs']['report_requirement_revisions'] == {requirement['id']: requirement['revision']}
