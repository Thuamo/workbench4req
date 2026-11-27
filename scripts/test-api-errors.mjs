import test from 'node:test';
import assert from 'node:assert/strict';
import {readJsonResponse} from '../frontend/lib/http.ts';

test('plain internal errors never surface as JSON syntax errors',async()=>{
    await assert.rejects(readJsonResponse(new Response('Internal Server Error',{status:500})),error=>error instanceof Error&&error.message.includes('HTTP 500')&&!error.message.includes('Unexpected token'));
});
test('HTML proxy failures have a readable service error',async()=>{
    await assert.rejects(readJsonResponse(new Response('<html>Bad Gateway</html>',{status:502})),/后端服务暂时不可用/);
});
test('database contention JSON detail is preserved',async()=>{
    await assert.rejects(readJsonResponse(new Response(JSON.stringify({detail:'数据库繁忙，请关闭数据库连接后重试。'}),{status:503})),/数据库繁忙/);
});
test('validation details and normal JSON still work',async()=>{
    await assert.rejects(readJsonResponse(new Response(JSON.stringify({detail:[{msg:'密码至少6位'}]}),{status:422})),/密码至少6位/);
    assert.deepEqual(await readJsonResponse(new Response('{"ok":true}',{status:200})),{ok:true});
});
test('empty successful responses and malformed successful responses differ',async()=>{
    assert.equal(await readJsonResponse(new Response(null,{status:204})),undefined);
    await assert.rejects(readJsonResponse(new Response('<html>wrong service</html>',{status:200})),/非 JSON 数据/);
});
