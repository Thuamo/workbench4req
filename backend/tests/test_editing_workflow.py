from conftest import ready_source
"""Isolated API regressions; model calls are test-only protocol fixtures."""
import io
import json
import zipfile
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from sqlalchemy import select, func
from app.db import SessionLocal
from app.models import AgentRun, Skill, Outbox, DocumentVersion, Document, ModelConfig
from app.security import cipher
from app.worker import process_one


def fixture_run(setup, status='completed', linked=True):
    clients, base = setup
    member, owner = clients['member']
    requirement = member.post('/requirements', json={'number':'EDIT-TEST','title':'文档编辑测试'}).json() if linked else None
    with SessionLocal() as db:
        skill = db.scalar(select(Skill).where(Skill.command=='/软需生成'))
        run = AgentRun(owner_id=owner, skill_version_id=skill.current_version_id, status=status,
            inputs={'task':'编辑测试','requirement_id':requirement['id'] if requirement else None},
            result={'workflow':'specification','outline':[f'第{i}章' for i in range(1,40)],
                'sections':[{'title':'技能输出','content':'原始内容'}],
                'analysis':{'items':[{'title':'待确认功能','description':'保持记录','tags':{}}]},
                'clarification':{'questions':[{'description':'保存多久？','reason':'缺少期限'}]},
                'impact':{'relations':[{'description':'接口影响','kind':'接口依赖'}]}})
        db.add(run)
        db.flush()
        db.add(Outbox(kind='agent',resource_id=run.id,status='awaiting_confirmation' if status=='awaiting_confirmation' else 'completed'))
        run_id=run.id
        db.commit()
    return member, base, run_id, requirement


def test_imported_columns_edit_history_and_export(setup):
    clients,_=setup
    member=clients['member'][0]
    columns=['需求名称','需求编号','自定义补充说明','工作量','_自定义状态']
    wb=Workbook()
    wb.active.append(columns)
    wb.active.append(['测试需求','COL-1','原值',0,None])
    stream=io.BytesIO(); wb.save(stream)
    files={'file':('计划.xlsx',stream.getvalue())}
    checked=member.post('/clarification/import-preview',files=files).json()
    response=member.post('/clarification/import',data={'expected_snapshot':checked['snapshot']},files=files)
    assert response.status_code==200,response.text
    assert response.json()['columns']==columns
    assert member.get('/clarification/columns').json()['columns']==columns
    task=member.get('/clarification/tasks').json()[0]
    fields={**task['fields'],'自定义补充说明':'人工修改','_自定义状态':'自定义值'}
    edited=member.patch('/clarification/tasks/'+task['id'],json={'fields':fields,'status':task['status'],'requirement_id':task['requirement_id'],'expected_revision':task['revision']})
    assert edited.status_code==200,edited.text
    assert edited.json()['fields']['工作量']==0
    assert member.patch('/clarification/tasks/'+task['id'],json={'fields':fields,'expected_revision':task['revision']}).status_code==409
    assert len(member.get('/clarification/tasks/'+task['id']+'/history').json())==2
    exported=load_workbook(io.BytesIO(member.get('/clarification/export').content),read_only=True)
    rows=list(exported.active.values)
    assert list(rows[0])==columns
    assert list(rows[1])==['测试需求','COL-1','人工修改',0,'自定义值']
    public=clients['other'][0].get('/clarification/tasks').json()
    assert public[0]['id']==task['id'] and public[0]['can_edit'] is False and public[0]['can_open_requirement'] is False


def test_skill_package_edit_export_and_access_control(setup):
    clients,_=setup
    member=clients['member'][0]
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('业务技能/SKILL.md','---\nname: 测试生成技能\ndescription: 包导入测试\nworkflow: specification\ncommand: /测试生成\n---\n只输出业务文档。')
        archive.writestr('业务技能/references/模板.md','参考资料')
    response=member.post('/skills/import',files={'file':('技能.zip',data.getvalue())})
    assert response.status_code==200,response.text
    skill=next(s for s in member.get('/skills').json() if s['id']==response.json()['id'])
    assert skill['config']['system_prompt']=='只输出业务文档。'
    assert not skill['public']
    original_hash=skill['config']['package_metadata']['file_hash']
    config={**skill['config'],'system_prompt':'编辑后的技能正文','package_metadata':{'file_hash':'forged'}}
    edited=member.post('/skills/'+skill['id']+'/versions',json={'name':skill['name'],'command':skill['command'],'description':skill['description'],'config':config})
    assert edited.status_code==200,edited.text
    versions=member.get('/skills/'+skill['id']+'/versions').json()
    assert len(versions)==2
    assert {v['config']['system_prompt'] for v in versions}=={'只输出业务文档。','编辑后的技能正文'}
    assert edited.json()['config']['package_metadata']['file_hash']==original_hash
    exported=member.get('/skills/'+skill['id']+'/export')
    assert exported.status_code==200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.read('source/original-package.zip')==data.getvalue()
    again=member.post('/skills/import',files={'file':('重新导入.zip',exported.content)})
    assert again.status_code==200,again.text
    assert clients['other'][0].get('/skills/'+skill['id']+'/export').status_code==404
    malicious=io.BytesIO()
    with zipfile.ZipFile(malicious,'w') as archive:
        archive.writestr('../SKILL.md','not allowed')
    assert member.post('/skills/import',files={'file':('路径.zip',malicious.getvalue())}).status_code==422


def test_outline_39_items_and_precise_validation(setup):
    member,_,run_id,_=fixture_run(setup,'awaiting_confirmation')
    path='/agent-runs/'+run_id+'/resume'
    too_many=member.post(path,json={'approved':True,'outline':[f'标题{i}' for i in range(101)]})
    assert too_many.status_code==422 and '100' in too_many.text
    response=member.post(path,json={'approved':True,'outline':'\r\n'.join('  '+f'第{i}章  ' for i in range(39))+'\r\n'})
    assert response.status_code==200,response.text
    assert response.json()['inputs']['_resume']['outline']==[f'第{i}章' for i in range(39)]
    assert response.json()['status']=='pending'


def test_document_progress_confirmation_revisions_and_ai_suggestions(setup):
    member,base,run_id,requirement=fixture_run(setup)
    path='/agent-runs/'+run_id
    draft={'content':'# 人工正文\n待核对内容','title':'确认文档','label':'V1.0','base_id':base,'folder_id':None}
    assert member.put(path+'/document-draft',json=draft).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DocumentVersion))==0
        db.add(ModelConfig(name='test-only-edit',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()))
        db.commit()
    with patch('app.routes.workflows.complete',return_value=('核对后的建议',{'model':'test-only'})):
        suggestion=member.post(path+'/edit-document',json={'content':draft['content'],'instruction':'只编辑选中部分','selection_start':7,'selection_end':12})
    assert suggestion.status_code==200,suggestion.text
    assert suggestion.json()['content']==draft['content'][:7]+'核对后的建议'+draft['content'][12:]
    assert suggestion.json()['requires_confirmation'] is True
    assert member.get(path).json()['result']['editor_draft']['content']==draft['content']
    assert member.post(path+'/edit-document',json={'content':'短文','instruction':'改','selection_start':1,'selection_end':5}).status_code==422
    assert setup[0]['other'][0].post(path+'/save',json=draft).status_code==404
    first=member.post(path+'/save',json=draft)
    assert first.status_code==200,first.text
    assert first.json()['content']==draft['content'] and first.json()['provenance']['human_edited'] is True
    assert first.json()['status']=='draft' and first.json()['requirement_id']==requirement['id']
    assert member.post(path+'/save',json=draft).json()['id']==first.json()['id']
    assert 'editor_draft' not in member.get(path).json()['result']
    revised=member.post(path+'/save',json={**draft,'content':'# 第二版正文','label':'V1.1'})
    assert revised.status_code==200,revised.text
    assert revised.json()['parent_id']==first.json()['id']
    assert revised.json()['document_id']==first.json()['document_id']
    with SessionLocal() as db:
        assert db.get(DocumentVersion,first.json()['id']).content==draft['content']


def test_requirement_candidate_operations_in_list_are_idempotent(setup):
    member,_,run_id,requirement=fixture_run(setup,'awaiting_confirmation')
    path='/agent-runs/'+run_id
    response=member.get('/requirements/'+requirement['id']+'/candidates')
    assert response.status_code==200,response.text
    assert 'sections' not in response.json()['runs'][0]['result']
    assert setup[0]['other'][0].get('/requirements/'+requirement['id']+'/candidates').status_code==404
    candidates=member.post(path+'/save-requirements',json={'selected_indices':[0],'confirm':True})
    assert candidates.json()['requirements'][0]['state']=='confirmed'
    assert member.post(path+'/save-requirements',json={'selected_indices':[0],'confirm':True}).json()['requirements']==[]
    questions=member.post(path+'/save-questions',json={'selected_indices':[0]})
    assert questions.status_code==200,questions.text
    assert questions.json()['questions'][0]['requirement_id']==requirement['id']
    assert member.post(path+'/save-questions',json={'selected_indices':[0]}).json()['questions']==[]


def test_legacy_unlinked_run_saves_independently_then_explicitly_associates(setup):
    member,base,run_id,_=fixture_run(setup,linked=False)
    response=member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'title':'历史任务','label':'V1.0','content':'人工确认的旧任务'})
    assert response.status_code==200,response.text
    assert response.json()['requirement_id'] is None and member.get('/requirements').json()==[]
    requirement_id=member.post('/requirements',json={'number':'EXPLICIT-1','title':'明确关联需求'}).json()['id']
    assert member.put('/processing-tasks/'+run_id+'/requirement',json={'requirement_id':requirement_id,'expected_revision':1}).status_code==200
    assert member.get('/requirements/'+requirement_id+'/candidates').json()['runs'][0]['id']==run_id
    # Older saved assets lacked the requirement link. A new version must repair it.
    with SessionLocal() as db:
        db.get(Document,response.json()['document_id']).requirement_id=None
        db.commit()
    revised=member.post('/agent-runs/'+run_id+'/save',json={'base_id':base,'title':'历史任务','label':'V1.1','content':'继续编辑旧任务'})
    assert revised.status_code==200,revised.text
    assert revised.json()['requirement_id']==requirement_id


def start_protocol_run(setup, confirmation=True):
    member=setup[0]['member'][0]
    with SessionLocal() as db:
        db.add(ModelConfig(name='test-only-graph',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()))
        db.commit()
    skill=member.post('/skills',json={'name':'图恢复协议测试','command':'/graph-test','description':'test-only','config':{'workflow':'specification','human_confirmation':confirmation}}).json()
    run=member.post('/skills/'+skill['id']+'/execute',json={'source_version_ids':[ready_source(setup)],'task':'图恢复测试'}).json()
    return member,run['id']


def test_39_section_checkpoint_retry_keeps_human_confirmation(setup):
    member,run_id=start_protocol_run(setup)
    fail_once=[True]
    def protocol(db,owner,messages,**kwargs):
        instruction=json.loads(messages[-1]['content'])['instruction']
        if instruction.startswith('编写') and fail_once[0]:
            fail_once[0]=False
            raise RuntimeError('test-only temporary section failure')
        result={'outline':[f'章节{i}' for i in range(39)]} if instruction.startswith('只在 outline') else {'answer':'test-only 正文'}
        return json.dumps(result,ensure_ascii=False),{'model':'test-only'}
    with patch('app.services.agents.complete',side_effect=protocol):
        assert process_one()
        assert member.get('/agent-runs/'+run_id).json()['status']=='awaiting_confirmation'
        assert member.post('/agent-runs/'+run_id+'/resume',json={'approved':True,'outline':[f'章节{i}' for i in range(39)]}).status_code==200
        assert process_one()
        assert member.get('/agent-runs/'+run_id).json()['status']=='failed'
        assert member.post('/agent-runs/'+run_id+'/retry',json={}).status_code==200
        assert process_one()
    completed=member.get('/agent-runs/'+run_id).json()
    assert completed['status']=='completed',completed
    assert len(completed['result']['sections'])==39
    assert sum(step['agent']=='Human' for step in completed['steps'])==1


def test_skill_can_skip_outline_pause_and_enter_document_editing(setup):
    member,run_id=start_protocol_run(setup,confirmation=False)
    def protocol(db,owner,messages,**kwargs):
        instruction=json.loads(messages[-1]['content'])['instruction']
        return json.dumps({'outline':['技能文档']} if instruction.startswith('只在 outline') else {'answer':'test-only 正文'},ensure_ascii=False),{}
    with patch('app.services.agents.complete',side_effect=protocol):
        assert process_one()
    completed=member.get('/agent-runs/'+run_id).json()
    assert completed['status']=='completed',completed
    assert completed['result']['sections'][0]['title']=='技能文档'
    assert not any(step['agent']=='Human' for step in completed['steps'])
