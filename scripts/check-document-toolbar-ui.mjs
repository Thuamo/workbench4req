// Browser contract fixtures only: all /api requests intercepted, no business writes/model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
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
 }else if(p.endsWith('/format-proposal')){const proposal={id:'proposal-'+(++pid),base_revision:w.revision,before_content:w.content,suggested_content:'原始业务正文',preview_json:json('原始业务正文'),status:'pending',detail:{kind:'formatting_cleanup'}};w.proposals.push(proposal);response=proposal;
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
w.content_json={type:'doc',content:[]};
for(let i=0;i<35;i++){w.content_json.content.push({type:'heading',attrs:{level:2},content:[{type:'text',text:`${i+1} 测试章节`}]},{type:'paragraph',content:[{type:'text',text:`第${i+1}章业务说明。`+'这是用于验证长文档滚动的模拟正文。'.repeat(12)}]});}
w.content='长文档滚动模拟';
async function pinned(){const toolbar=page.getByRole('toolbar',{name:'文档正文格式工具',exact:true});const rect=await toolbar.boundingBox();assert.ok(rect&&rect.y>=10&&rect.y<=14,JSON.stringify(rect));return toolbar;}
try{
 await page.goto('http://localhost:3000/#page=editor&id=run~run',{waitUntil:'domcontentloaded'});
 const body=page.getByRole('textbox',{name:'文档正文',exact:true});await body.waitFor();
 await page.evaluate(()=>window.scrollTo(0,2500));await page.waitForTimeout(200);let toolbar=await pinned();
 const middle=body.locator('p').nth(7);await middle.click();toolbar=await pinned();await toolbar.getByRole('button',{name:'项目列表',exact:true}).click();assert.ok(await body.locator('ul').count());
 await page.evaluate(()=>window.scrollTo(0,5000));await page.waitForTimeout(200);toolbar=await pinned();
 const paragraph=body.locator('p').nth(16);await paragraph.click();toolbar=await pinned();await toolbar.getByRole('button',{name:'插入表格',exact:true}).click();assert.equal(await body.locator('table').count(),1);
 toolbar=await pinned();await toolbar.getByRole('button',{name:'添加行',exact:true}).click();assert.equal(await body.locator('table tr').count(),4);
 await page.screenshot({path:'test-results/document-toolbar-pinned.png'});
 // Side panel changes must not detach the toolbar from the center editor.
 await page.getByRole('button',{name:'收起目录',exact:true}).click();await page.getByRole('button',{name:'收起AI 助手',exact:true}).click();
 await page.evaluate(()=>window.scrollTo(0,2200));await page.waitForTimeout(200);await pinned();
 await page.getByRole('button',{name:'展开目录',exact:true}).click();await page.locator('.workspace-directory').getByRole('button',{name:'20 测试章节',exact:true}).click();await page.waitForTimeout(800);
 const heading=await body.getByRole('heading',{name:'20 测试章节',exact:true}).boundingBox();toolbar=await pinned();const toolRect=await toolbar.boundingBox();assert.ok(heading.y>=toolRect.y+toolRect.height);
 await page.setViewportSize({width:900,height:850});await page.evaluate(()=>window.scrollTo(0,2200));await page.waitForTimeout(200);toolbar=await pinned();const small=await toolbar.boundingBox();assert.ok(small.x>=0&&small.x+small.width<=900);assert.ok(await toolbar.getByRole('button',{name:'插入表格',exact:true}).isVisible());
 assert.deepEqual(errors,[]);console.log(JSON.stringify({toolbarPinnedWhileScrolling:true,listActionWorks:true,tableActionWorks:true,tableRowActionWorks:true,sidePanelToggleWorks:true,headingNotObscured:true,narrowLayoutWorks:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
