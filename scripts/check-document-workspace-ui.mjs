// Browser contract fixtures only: all /api requests intercepted, no business writes/model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const site=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const user={id:'workspace-fixture-user',display_name:'文档测试',username:'fixture',role:'requirement_member'};
const json=text=>({type:'doc',content:[{type:'heading',attrs:{level:1},content:[{type:'text',text:'1 需求背景与目标'}]},{type:'paragraph',content:[{type:'text',text}]}]});
let w={id:'workspace',run_id:'run',document_id:null,version_id:null,requirement_id:'req',title:'ESG 软件需求说明书',label:'V1.0',base_id:'base',folder_id:null,content_json:{type:'doc',content:[json('').content[0],json('').content[0],{type:'paragraph',content:[{type:'text',text:'原始业务正文[citation_id: fixture-source]'}]}]},content:'# 1 需求背景与目标\n\n原始业务正文',revision:0,confirmed_revision:null,change_note:'',sources:[],messages:[],proposals:[]};
const run={created_at:'2026-10-29T08:00:00',id:'run',workflow:'specification',status:'completed',inputs:{task:'生成 ESG 软需'},result:{sections:[{title:'1 需求背景与目标',content:'原始业务正文'}]},steps:[{id:'step',agent:'Document Agent',summary:'正文已生成'}],citations:[]};
const errors=[];const calls=[];let pid=0;const bodies=[];
const page=await browser.newPage({viewport:{width:1600,height:1100},locale:'zh-CN'});page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),url=new URL(request.url()),p=url.pathname.slice(4),method=request.method();let data;try{data=request.postDataJSON();}catch{}calls.push({p,method});let response={};let code=200;
 if(p==='/auth/me')response=user;
 else if(p==='/auth/csrf')response={csrf_token:'fixture'};
 else if(p==='/knowledge-bases')response=[{id:'base',name:'软件需求说明书库'}];
 else if(p==='/agent-runs/run')response=run;
 else if(p==='/processing-tasks/run')response={...run,requirement_id:'req',requirement:null,task_revision:1,skill_name:'测试技能',stage:'document_ready',stage_label:'正文已生成',documents:[],output_count:0};
 else if(p==='/document-workspaces/open'||p==='/document-workspaces/workspace'&&method==='GET')response=w;
 else if(p==='/document-workspaces/workspace'&&method==='PUT'){
  assert.equal(data.expected_revision,w.revision);w={...w,...data,revision:w.revision+1};bodies.push(JSON.stringify(data.content_json));response=w;
 }else if(p.endsWith('/assistant')){
  if(data.instruction==='故障测试'){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模型服务账号欠费或不可用（Arrearage）。请检查账户状态。',provider_code:'Arrearage'})});return;}
  const msg={id:'message-'+Date.now(),role:'assistant',mode:data.mode,content:data.mode==='ask'?'此规则缺少业务依据，请确认。':'已生成全文修改提案。',detail:{}};
  w.messages.push({id:'user-'+Date.now(),role:'user',mode:data.mode,content:data.instruction,detail:{}},msg);
  let proposal=null;if(data.mode==='modify'){proposal={id:'proposal-'+(++pid),base_revision:w.revision,before_content:w.content,suggested_content:'# 1 需求背景与目标\n\nAI 建议正文',preview_json:null,status:'pending'};w.proposals.push(proposal);msg.detail.proposal_id=proposal.id;}response={message:msg,proposal};
 }else if(p.includes('/proposals/')){
  const proposal=w.proposals.find(x=>p.includes(x.id));assert.ok(proposal);
  if(p.endsWith('/apply')){if(w.revision!==proposal.base_revision){code=409;response={detail:'正文已变化，请重新生成提案'};}else{w={...w,content_json:data.content_json,revision:w.revision+1};proposal.preview_json=data.content_json;proposal.status='applied';response={workspace:w,proposal};}}
  else if(p.endsWith('/discard')){proposal.status='discarded';response=proposal;}
  else{proposal.preview_json=data.content_json;response=proposal;}
 }else if(p.endsWith('/confirm')){response={id:'version',document_id:'doc',requirement_id:'req'};w.document_id='doc';w.version_id='version';w.confirmed_revision=w.revision;}
 else if(p==='/requirements')response=[];
 else if(p==='/documents'||p==='/agent-runs'||p==='/skills'||p==='/notifications'||p==='/conversations'||p.endsWith('/folders'))response=[];
 else response=[];
 await route.fulfill({status:code,contentType:'application/json',body:JSON.stringify(response)});
});
try{
 await page.goto(site+'/#page=run&id=run');
 await page.getByRole('button',{name:'进入文档编辑工作台',exact:true}).click();
 await page.getByRole('heading',{name:'软需文档编辑工作台'}).waitFor();
 const body=page.getByRole('textbox',{name:'文档正文',exact:true});await body.waitFor();
 assert.equal(await page.locator('.workspace-directory').getByRole('button',{name:'1 需求背景与目标',exact:true}).count(),1);
 assert.equal(await page.getByRole('button',{name:'整理重复内容与引用',exact:true}).count(),0);
 assert.equal(calls.filter(call=>call.p.endsWith('/format-proposal')).length,0);
 await body.fill('人工修改正文');
 await page.getByRole('button',{name:'保存文档',exact:true}).click();
 await page.getByText('工作草稿 · 已保存',{exact:false}).waitFor();assert.ok(JSON.stringify(w.content_json).includes('人工修改正文'));
 await page.reload();await page.getByRole('heading',{name:'软需文档编辑工作台'}).waitFor();await body.waitFor();await page.waitForFunction(()=>document.querySelector('[aria-label="文档正文"]')?.textContent.includes('人工修改正文'));
 const beforeAsk=JSON.stringify(w.content_json);
 await page.getByRole('textbox',{name:'AI 对话输入'}).fill('有哪些缺少依据的规则？');await page.getByRole('button',{name:'发送问题',exact:true}).click();await page.getByText('此规则缺少业务依据，请确认。',{exact:true}).waitFor();assert.equal(JSON.stringify(w.content_json),beforeAsk);
 await page.getByRole('textbox',{name:'AI 对话输入'}).fill('故障测试');await page.getByRole('button',{name:'发送问题',exact:true}).click();await page.getByRole('alert').getByText(/Arrearage/).waitFor();assert.equal(JSON.stringify(w.content_json),beforeAsk);
 await page.getByLabel('AI 对话模式',{exact:true}).selectOption('modify');await page.getByRole('textbox',{name:'AI 对话输入'}).fill('补充处理规则');await page.getByRole('button',{name:'生成修改提案',exact:true}).click();
 await page.getByRole('heading',{name:'AI 修改提案预览',exact:true}).waitFor();assert.equal(JSON.stringify(w.content_json),beforeAsk);
 const preview=page.getByRole('textbox',{name:'AI 修改后正文',exact:true});await preview.waitFor();await preview.fill('人工调整后的 AI 建议');assert.equal(JSON.stringify(w.content_json),beforeAsk);
 await page.screenshot({path:'test-results/document-proposal-editable.png',fullPage:true});
 await page.getByRole('button',{name:'暂存预览并返回',exact:true}).click();
 await page.locator('.proposal-entry').first().click();await preview.waitFor();assert.ok((await preview.textContent()).includes('人工调整后的 AI 建议'));
 await page.getByRole('button',{name:'确认应用修改',exact:true}).click();await page.getByRole('heading',{name:'AI 修改提案预览'}).waitFor({state:'hidden'});assert.ok(JSON.stringify(w.content_json).includes('人工调整后的 AI 建议'));
 await page.getByRole('textbox',{name:'AI 对话输入'}).fill('再补充说明');await page.getByRole('button',{name:'生成修改提案',exact:true}).click();await preview.waitFor();const beforeDiscard=JSON.stringify(w.content_json);await page.getByRole('button',{name:'放弃修改',exact:true}).click();await preview.waitFor({state:'hidden'});assert.equal(JSON.stringify(w.content_json),beforeDiscard);
 await page.getByRole('button',{name:'插入表格',exact:true}).click();await page.getByRole('button',{name:'保存文档',exact:true}).click();await page.getByText('工作草稿 · 已保存',{exact:false}).waitFor();assert.ok(JSON.stringify(w.content_json).includes('table'));
 await page.screenshot({path:'test-results/document-workspace-richtext.png',fullPage:true});
 await page.getByRole('textbox',{name:'AI 对话输入'}).fill('生成旧提案');await page.getByRole('button',{name:'生成修改提案',exact:true}).click();await preview.waitFor();await page.getByRole('button',{name:'暂存预览并返回',exact:true}).click();
 await body.fill('最新人工正文');await page.getByRole('button',{name:'保存文档',exact:true}).click();await page.getByText('工作草稿 · 已保存',{exact:false}).waitFor();await page.locator('.proposal-entry').first().click();await preview.waitFor();assert.equal(await page.getByRole('button',{name:'确认应用修改',exact:true}).isDisabled(),true);await page.getByRole('button',{name:'放弃修改',exact:true}).click();
 await page.getByRole('button',{name:'确认版本并返回任务',exact:true}).click();await page.waitForFunction(()=>location.hash.includes('page=task'));assert.ok(calls.some(c=>c.p.endsWith('/confirm')));
 assert.deepEqual(errors,[]);console.log(JSON.stringify({duplicateDirectoryHidden:true,formatActionRemoved:true,providerErrorExplained:true,richTextEditable:true,tableEditable:true,refreshRestores:true,questionDoesNotEdit:true,proposalPreviewEditable:true,previewSaved:true,applyUsesHumanRevision:true,discardPreserves:true,staleProposalBlocked:true,confirmReturnsToTask:true,processPageRetained:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
