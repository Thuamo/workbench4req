// Real chunked local HTTP + API fixtures. No production writes or model calls.
import {createServer} from 'node:http';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const user={id:'owner',username:'fixture',display_name:'流式输出测试',role:'requirement_member'};
const histories=new Map([['conv',[]]]);const now='2026-11-04T09:00:00';let serial=0,control=null,currentCase='success';
const citation={citation_id:'c1',document_id:'d',document_version_id:'v1',title:'规则文档',version:'V1',locator:'3 处理规则',excerpt:'规则应保留原始记录。',formal:true,scope:'formal'};
const headers={'Content-Type':'text/event-stream; charset=utf-8','Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no','Access-Control-Allow-Origin':'http://localhost:3000','Access-Control-Allow-Credentials':'true','Access-Control-Allow-Headers':'Content-Type,X-CSRF-Token','Access-Control-Allow-Methods':'GET,POST,OPTIONS'};
const server=createServer(async(req,res)=>{
 if(req.method==='OPTIONS'){res.writeHead(204,headers);res.end();return;}
 let raw='';for await(const part of req)raw+=part;const data=JSON.parse(raw);const cid=new URL(req.url,'http://fixture').searchParams.get('conversation');
 const history=histories.get(cid)||[];histories.set(cid,history);const id='reply-'+(++serial);const mode=currentCase;
 const first=mode==='stop'?'停止测试：这段已经输出。':mode==='error'?'异常测试：这段已经输出。':'第一段已实时显示，尚未结束。';
 let preview=first,ended=false;
 const meta={qa_mode:data.qa_mode,scopes:data.scopes,reply_id:id,validation:'pending',document_count:1,evidence_count:1,unreviewed_count:0};
 history.push({id:'user-'+serial,role:'user',content:data.content,qa_mode:data.qa_mode,scopes:data.scopes,version_ids:data.version_ids,created_at:now});
 const emit=value=>{if(!res.destroyed)res.write('data: '+JSON.stringify(value)+'\n\n');};
 function save(status,text,validation,citations=[]){history.push({id,role:'assistant',content:text,generation_status:status,qa_mode:data.qa_mode,retrieval:{...meta,validation},citations,candidate_citations:[citation],created_at:now});}
 res.on('close',()=>{if(!ended){ended=true;save('stopped',preview,'incomplete');}});
 res.writeHead(200,headers);res.flushHeaders();res.write(': keep-alive\n\n');emit({type:'retrieval',meta});emit({type:'sources',citations:[citation],candidate:true});emit({type:'token',content:first,provisional:true});
 control={id,get ended(){return ended;},append(){const text='第二段也在结束前到达。';preview+=text;emit({type:'token',content:text,provisional:true});},finish(){
  const final='校验后的最终回答：规则应保留原始记录。';save('completed',final,'checked',[citation]);ended=true;emit({type:'answer',content:final,provisional:false});emit({type:'sources',citations:[citation],candidate:false});emit({type:'retrieval',meta:{...meta,validation:'checked'}});emit({type:'done'});res.end();
 },fail(){save('failed',preview,'incomplete');ended=true;emit({type:'error',message:'测试服务中途断开，请重试。'});res.end();}};
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);let body=[];
 const match=path.match(/^\/conversations\/([^/]+)\/messages$/);
 if(match&&request.method()==='POST'){await route.continue({url:origin+'/stream?conversation='+match[1]});return;}
 if(match)body=histories.get(match[1])||[];
 else if(path==='/auth/me')body=user;
 else if(path==='/auth/csrf')body={csrf_token:'fixture'};
 else if(path==='/dashboard')body={counts:{},charts:{},recent:{documents:[],reviews:[],conversations:[]}};
 else if(path==='/conversations')body=request.method()==='POST'?{id:'conv-new',title:'新聊天'}:[{id:'conv',title:'实时输出验证'},{id:'conv-new',title:'新聊天'}];
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
});
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
async function start(text){await page.getByPlaceholder('输入您的问题').fill(text);await page.getByRole('button',{name:'发送消息',exact:true}).click();}
try{
 await page.goto(url+'/#page=chat&id=conv',{waitUntil:'domcontentloaded'});
 await start('验证边生成边输出');await page.locator('.live-reply').getByText('第一段已实时显示，尚未结束。',{exact:true}).waitFor();assert.equal(control.ended,false);
 assert.ok(await page.getByRole('button',{name:'停止',exact:true}).isVisible());await page.getByText('正在生成 · 来源待校验',{exact:true}).waitFor();await page.screenshot({path:'test-results/chat-streaming-preview.png'});
 control.append();await page.getByText('第一段已实时显示，尚未结束。第二段也在结束前到达。',{exact:true}).waitFor();assert.equal(control.ended,false);
 control.finish();await page.getByRole('button',{name:'停止',exact:true}).waitFor({state:'hidden'});await page.getByText('校验后的最终回答：规则应保留原始记录。',{exact:true}).waitFor();assert.equal(await page.getByText('第一段已实时显示，尚未结束。第二段也在结束前到达。',{exact:true}).count(),0);
 currentCase='stop';await start('停止后保留片段');await page.getByText('停止测试：这段已经输出。',{exact:true}).waitFor();await page.getByRole('button',{name:'停止',exact:true}).click();await page.getByText('已停止 · 部分内容',{exact:true}).waitFor();await page.getByText('停止测试：这段已经输出。',{exact:true}).waitFor();await page.getByText('未完成来源校验',{exact:true}).waitFor();
 currentCase='error';await start('错误后保留片段');await page.getByText('异常测试：这段已经输出。',{exact:true}).waitFor();control.fail();await page.getByText('生成失败 · 部分内容',{exact:true}).waitFor();await page.getByText('异常测试：这段已经输出。',{exact:true}).waitFor();assert.equal(await page.getByPlaceholder('输入您的问题').inputValue(),'错误后保留片段');
 await page.screenshot({path:'test-results/chat-streaming-interrupted.png'});
 currentCase='success';await page.goto(url+'/#page=chat',{waitUntil:'domcontentloaded'});await start('新会话实时输出');await page.getByText('第一段已实时显示，尚未结束。',{exact:true}).waitFor();assert.equal(control.ended,false);control.finish();await page.waitForFunction(()=>location.hash.includes('id=conv-new'));await page.getByText('校验后的最终回答：规则应保留原始记录。',{exact:true}).waitFor();assert.equal(await page.getByRole('combobox',{name:'问答模式',exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({chunkVisibleBeforeFinish:true,multipleChunksVisible:true,finalReplacesPreview:true,stopKeepsFragment:true,errorKeepsFragment:true,incompleteSourcesMarked:true,newConversationStreams:true,pageErrors:errors,productionWrites:0,realModelCalls:0}));
}finally{await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
