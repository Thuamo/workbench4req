import asyncio
import json
from unittest.mock import patch
import httpx
from sqlalchemy import select
from app.db import SessionLocal
from app.models import User,Conversation,Message
from app.schemas import ChatInput
from app.routes.chat import send
from app.services.claim_stream import ClaimTextStream
from test_qa_and_batch_review import source
from test_chat_modes_and_reset import model


def test_claim_parser_streams_only_text_across_every_json_boundary():
    value={'text':'外层字段不得输出','claims':[{'kind':'fact','text':'规则“中文”\\路径\n表格 | 标识 {x} 😀','evidence_ids':['private-id'], 'evidence_quotes':[{'citation_id':'private-id','quote':'不要输出引文协议','text':'嵌套text不得输出'}]}, {'text':'第二条建议','kind':'verify','other':[True,False,None,1,{'text':'不能输出'}]}]}
    for ensure_ascii in (True,False):
        raw=json.dumps(value,ensure_ascii=ensure_ascii)
        expected='- '+value['claims'][0]['text']+'\n\n- 第二条建议'
        stream=ClaimTextStream();parts=[stream.feed(ch) for ch in raw]
        assert ''.join(parts)==expected
        assert any(parts[:raw.index('evidence_ids')])
        for cut in range(len(raw)+1):
            stream=ClaimTextStream()
            assert stream.feed(raw[:cut])+stream.feed(raw[cut:])==expected


def test_parser_accepts_text_last_and_ignores_nonclaim_strings():
    stream=ClaimTextStream()
    assert stream.feed('{"claims":[{"evidence_quotes":[{"text":"隐藏"}],"kind":"fact","text":"首')=='- 首'
    assert stream.feed('段"},{"kind":"verify","text":"次段"}]}')=='段\n\n- 次段'
    invalid=ClaimTextStream()
    assert invalid.feed('{"claims":[{"text":"保留\\uZZZZ 协议不应泄漏')=='- 保留'


class Request:
    async def is_disconnected(self):return False


class Response:
    status_code=200
    def __init__(self,raw,gate,mode):self.raw=raw;self.gate=gate;self.mode=mode
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def aiter_lines(self):
        cut=self.raw.index('边生成')+len('边生成')
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':self.raw[:cut]}}]})
        await self.gate.wait()
        if self.mode=='error':raise httpx.ReadError('provider diagnostic must not leak')
        yield 'data: '+json.dumps({'choices':[{'delta':{'content':self.raw[cut:]}}]})
        if self.mode!='truncated':yield 'data: [DONE]'


def client_factory(gate,mode):
    class Client:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def stream(self,*args,**kwargs):
            evidence=json.loads(kwargs['json']['messages'][0]['content'].split('本次证据：',1)[1]);first=evidence[0]
            raw=json.dumps({'claims':[{'kind':'fact','text':'边生成边输出的答案','evidence_ids':[first['citation_id']],'evidence_quotes':[{'citation_id':first['citation_id'],'quote':first['excerpt']}]},{'kind':'fact','text':'应被最终校验移除的内容','evidence_ids':['forged-id']}]},ensure_ascii=False)
            return Response(raw,gate,mode)
    return Client


def setup_response(setup):
    v=source(setup,text='评级为空时阻断提交，并保留原评级。');model()
    with SessionLocal() as db:
        conv=Conversation(owner_id=setup[0]['member'][1]);db.add(conv);db.flush();cid=conv.id;db.commit()
    return v,cid


def event(frame):return json.loads(frame[6:])


def test_real_sse_iterator_yields_before_model_completion_and_final_replaces_preview(setup):
    version,cid=setup_response(setup)
    async def run():
        gate=asyncio.Event()
        with SessionLocal() as db,patch('app.routes.chat.httpx.AsyncClient',client_factory(gate,'success')):
            response=send(cid,ChatInput(content='评级为空时的规则',scopes=['selected'],version_ids=[version['id']]),Request(),db.get(User,setup[0]['member'][1]),db)
            stream=response.body_iterator
            assert event(await anext(stream))['type']=='retrieval'
            assert event(await anext(stream))['type']=='sources'
            first=event(await asyncio.wait_for(anext(stream),timeout=2))
            assert first['type']=='token' and first['provisional'] and '边生成' in first['content']
            assert not gate.is_set()  # The rest of the model response is still blocked.
            gate.set();events=[event(frame) async for frame in stream]
        final=next(e for e in events if e['type']=='answer')
        assert final['provisional'] is False
        assert final['content']=='【未审核资料／登记记录】边生成边输出的答案〔来源1〕'
        assert '应被最终校验移除' not in final['content'] and 'forged-id' not in final['content']
        sources=next(e for e in events if e['type']=='sources' and not e['candidate'])
        assert sources['citations'][0]['quotes']==['评级为空时阻断提交，并保留原评级。']
        assert events[-1]['type']=='done'
    asyncio.run(run())
    saved=setup[0]['member'][0].get('/conversations/'+cid+'/messages').json()[-1]
    assert saved['generation_status']=='completed' and saved['citations']
    assert saved['citations'][0]['quotes']==['评级为空时阻断提交，并保留原评级。']
    assert '应被最终校验移除' not in saved['content']
    assert saved['id']==saved['retrieval']['reply_id']


def test_stopping_stream_retains_fragment_without_claiming_verified_sources(setup):
    version,cid=setup_response(setup)
    async def run():
        gate=asyncio.Event()
        with SessionLocal() as db,patch('app.routes.chat.httpx.AsyncClient',client_factory(gate,'success')):
            response=send(cid,ChatInput(content='评级为空时的规则',scopes=['selected'],version_ids=[version['id']]),Request(),db.get(User,setup[0]['member'][1]),db)
            stream=response.body_iterator
            await anext(stream);await anext(stream)
            first=event(await anext(stream));assert '边生成' in first['content']
            await stream.aclose()
    asyncio.run(run())
    saved=setup[0]['member'][0].get('/conversations/'+cid+'/messages').json()[-1]
    assert saved['generation_status']=='stopped' and saved['content']=='- 边生成'
    assert saved['retrieval']['validation']=='incomplete' and saved['citations']==[]
    assert saved['candidate_citations']


def test_provider_error_or_missing_end_marker_keeps_incomplete_fragment(setup):
    version,cid=setup_response(setup)
    async def run(mode):
        gate=asyncio.Event();gate.set()
        with SessionLocal() as db,patch('app.routes.chat.httpx.AsyncClient',client_factory(gate,mode)):
            response=send(cid,ChatInput(content='评级为空时的规则',scopes=['selected'],version_ids=[version['id']]),Request(),db.get(User,setup[0]['member'][1]),db)
            return [event(frame) async for frame in response.body_iterator]
    for mode in ('error','truncated'):
        events=asyncio.run(run(mode))
        assert any(e['type']=='token' for e in events) and any(e['type']=='error' for e in events)
        assert not any(e['type']=='answer' for e in events)
        assert 'provider diagnostic' not in json.dumps(events)
        saved=setup[0]['member'][0].get('/conversations/'+cid+'/messages').json()[-1]
        assert saved['generation_status']=='failed' and saved['retrieval']['validation']=='incomplete' and saved['citations']==[]


def test_sse_heartbeat_is_transport_only_and_does_not_enter_answer(setup):
    version,cid=setup_response(setup)
    async def run():
        gate=asyncio.Event();gate.set();calls=0
        def clock():
            nonlocal calls
            calls+=1
            return 0 if calls==1 else 11
        with SessionLocal() as db,patch('app.routes.chat.httpx.AsyncClient',client_factory(gate,'success')),patch('app.routes.chat.monotonic',clock):
            response=send(cid,ChatInput(content='评级为空时的规则',scopes=['selected'],version_ids=[version['id']]),Request(),db.get(User,setup[0]['member'][1]),db)
            frames=[frame async for frame in response.body_iterator]
        assert ': keep-alive\n\n' in frames
    asyncio.run(run())
    with SessionLocal() as db:
        reply=db.scalar(select(Message).where(Message.conversation_id==cid,Message.role=='assistant'))
        assert 'keep-alive' not in reply.content and reply.generation_status=='completed'
