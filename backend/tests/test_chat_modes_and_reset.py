import json
from unittest.mock import patch
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import User,Audit,ModelConfig,AgentRun,DocumentVersion
from app.security import cipher,verify
from conftest import ready_source


def test_admin_reset_password_invalidates_sessions_without_changing_role(setup):
    clients,_=setup;admin=clients['admin'][0];member,uid=clients['member']
    assert clients['other'][0].post('/admin/users/'+uid+'/reset-password').status_code==403
    response=admin.post('/admin/users/'+uid+'/reset-password')
    assert response.status_code==200,response.text
    assert member.get('/auth/me').status_code==401
    assert member.post('/auth/login',json={'username':'member','password':'Test-only_password123'}).status_code==401
    assert member.post('/auth/login',json={'username':'member','password':'mima123'}).status_code==200
    with SessionLocal() as db:
        account=db.get(User,uid);assert account.role=='requirement_member' and account.enabled
        assert verify('mima123',account.password_hash) and account.password_hash!='mima123'
        log=db.scalar(select(Audit).where(Audit.action=='admin.password_reset'))
        assert log.actor_id==clients['admin'][1] and 'mima123' not in json.dumps(log.detail)
    assert admin.post('/admin/users/not-a-user/reset-password').status_code==404


def test_reset_self_and_disabled_account(setup):
    clients,_=setup;admin,aid=clients['admin'];uid=clients['member'][1]
    admin.patch('/admin/users/'+uid,json={'enabled':False})
    assert admin.post('/admin/users/'+uid+'/reset-password').status_code==200
    assert clients['member'][0].post('/auth/login',json={'username':'member','password':'mima123'}).status_code==401
    assert admin.post('/admin/users/'+aid+'/reset-password').status_code==200
    assert admin.get('/auth/me').status_code==401
    assert admin.post('/auth/login',json={'username':'admin','password':'mima123'}).status_code==200


class Response:
    status_code=200
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def aiter_lines(self):
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':'按当前技能回答'}}]})
        yield 'data: [DONE]'

class Client:
    requests=[]
    def __init__(self,*args,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    def stream(self,*args,**kwargs):self.requests.append(kwargs['json']);return Response()


def model():
    with SessionLocal() as db:
        db.add(ModelConfig(name='chat-mode-fixture',base_url='https://test.invalid/v1',model='fixture',kind='chat',encrypted_key=cipher().encrypt(b'not-real').decode()));db.commit()


def test_chat_selected_skill_without_files_never_starts_work_and_isolates_history(setup):
    member=setup[0]['member'][0];model();Client.requests=[]
    def skill(name,prompt):return member.post('/skills',json={'name':name,'command':'/'+name,'description':'fixture','config':{'workflow':'specification','system_prompt':prompt,'allowed_tools':[]}}).json()['id']
    a=skill('软需','规则甲');b=skill('台账','规则乙');conv=member.post('/conversations').json()['id'];path='/conversations/'+conv+'/messages'
    with patch('app.routes.chat.httpx.AsyncClient',Client):
        assert member.post(path,json={'content':'甲的问题','skill_id':a}).status_code==200
        assert member.post(path,json={'content':'乙的问题','skill_id':b}).status_code==200
        assert member.post(path,json={'content':'甲的后续','skill_id':a}).status_code==200
    prompt=Client.requests[-1]['messages']
    assert '规则甲' in prompt[0]['content'] and '规则乙' not in json.dumps(prompt,ensure_ascii=False)
    assert '甲的问题' in json.dumps(prompt,ensure_ascii=False) and '乙的问题' not in json.dumps(prompt,ensure_ascii=False)
    assert member.post(path,json={'content':'甲的后续','skill_id':b,'regenerate':True}).status_code==422
    assert member.get(path).json()[-2]['skill_id']==a
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(AgentRun))==0


def test_chat_files_optional_authorized_and_work_requires_business_file(setup):
    clients,_=setup;member=clients['member'][0];model()
    skill=member.post('/skills',json={'name':'工作技能','command':'/work','description':'fixture'}).json()['id']
    conv=member.post('/conversations').json()['id'];path='/conversations/'+conv+'/messages'
    assert member.post('/skills/'+skill+'/execute',json={'task':'没有文件'}).status_code==422
    own=ready_source(setup);foreign=ready_source(setup,'other')
    assert member.post('/skills/'+skill+'/execute',json={'task':'仅样例','sample_version_ids':[own]}).status_code==422
    assert member.post('/skills/'+skill+'/execute',json={'task':'越权文件','source_version_ids':[foreign]}).status_code==404
    assert member.post(path,json={'content':'越权技能','skill_id':clients['other'][0].post('/skills',json={'name':'私人','command':'/private','description':'fixture'}).json()['id']}).status_code==404
    assert member.post(path,json={'content':'越权附件','skill_id':skill,'version_ids':[foreign]}).status_code==404
    with patch('app.routes.chat.httpx.AsyncClient',Client):
        assert member.post(path,json={'content':'带附件问答','skill_id':skill,'version_ids':[own]}).status_code==200
    assert '测试业务证据' in Client.requests[-1]['messages'][0]['content']
    result=member.post('/skills/'+skill+'/execute',json={'task':'合法工作','source_version_ids':[own]})
    assert result.status_code==200,result.text
    assert result.json()['status']=='pending'
