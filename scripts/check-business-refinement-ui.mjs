// All application APIs are intercepted. No production writes or model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'refinement-fixture',display_name:'动线测试',role:'requirement_member'};
const node=(type,text,level=1)=>({type,...(type==='heading'?{attrs:{level}}:{}),content:[{type:'text',text}]});
const original={type:'doc',content:[node('heading','1 背景'),node('paragraph','必须保留的业务背景'),node('heading','2 处理规则'),node('paragraph','待完善的处理规则'),node('heading','3 系统边界'),node('paragraph','必须保留的系统边界')]};
let w={id:'w',run_id:'r',title:'测试软件需求说明书',label:'V1',base_id:'base',folder_id:null,content_json:structuredClone(original),content:'测试正文',revision:1,confirmed_revision:null,change_note:'',sources:[],messages:[],proposals:[]};
const errors=[],requests=[];let seq=0;
const page=await browser.newPage({viewport:{width:1600,height:1050},locale:'zh-CN'});page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const req=route.request(),p=new URL(req.url()).pathname.slice(4);let data;try{data=req.postDataJSON();}catch{}requests.push({p,data});let result=[];
 if(p==='/auth/me')result=user;
 else if(p==='/auth/csrf')result={csrf_token:'fixture'};
 else if(p==='/knowledge-bases')result=[{id:'base',name:'软件需求说明书库'}];
 else if(p==='/document-workspaces/open')result=w;
 else if(p==='/processing-tasks/quality')result={id:'quality',workflow:'quality',status:'completed',created_at:'2026-11-05T01:00:00Z',inputs:{task:'核查测试软需'},skill_name:'软需质量核查',stage:'analysis_ready',stage_label:'分析待确认',task_revision:1,requirement_id:null,requirement:null,output_count:0,result:{review:{answer:'异常规则缺少依据，建议标记待确认'}},documents:[{role:'input',document:{id:'doc',title:'测试软需',kind:'specification',owner_id:user.id},version:{id:'target',label:'V1',created_at:'2026-11-05T01:00:00Z'}}]};
 else if(p==='/processing-tasks/quality/repair-proposal'){assert.equal(data.version_id,'target');result={version_id:'target',workspace_id:'w',proposal_id:'quality-proposal'};}
 else if(p==='/document-workspaces/w'&&req.method()==='PUT'){w={...w,...data,revision:w.revision+1};result=w;}
 else if(p.endsWith('/history'))result=[{id:'old',revision:1,created_at:'2026-11-05T01:00:00Z'}];
 else if(p.includes('/restore-proposal/')){result={id:'restore',base_revision:w.revision,before_content:w.content,suggested_content:'恢复原草稿',preview_json:original,status:'pending',detail:{kind:'history_restore'}};w.proposals.push(result);}
 else if(p.endsWith('/quality'))result={issues:[{message:'接口字段来源待确认'}],unresolved_count:1};
 else if(p.endsWith('/assistant')){
  assert.equal(data.mode,'modify');
  if(!data.proposal_id){assert.equal(data.block_from,2);assert.equal(data.block_to,4);}
  const proposal={id:'p'+(++seq),base_revision:w.revision,before_content:'## 2 处理规则\n待完善的处理规则',suggested_content:data.proposal_id?'第二轮段落建议':'第一轮段落建议',preview_json:null,status:'pending',detail:{scope:'blocks',block_from:2,block_to:4}};
  w.proposals.push(proposal);result={message:{id:'msg'+seq,role:'assistant',mode:'modify',content:'已生成段落提案',detail:{proposal_id:proposal.id}},proposal};
 }else if(p.includes('/proposals/')){
  const proposal=w.proposals.find(x=>p.includes('/'+x.id));assert.ok(proposal);
  if(p.endsWith('/diff'))result=[{kind:'replace',before:['待完善的处理规则'],after:['人工修订的处理规则']}];
  else if(p.endsWith('/apply')){const content=proposal.detail.scope==='blocks'?[...w.content_json.content.slice(0,2),...data.content_json.content,...w.content_json.content.slice(4)]:data.content_json.content;w={...w,content_json:{type:'doc',content},revision:w.revision+1};proposal.status='applied';result={workspace:w,proposal};}
  else if(p.endsWith('/discard')){proposal.status='discarded';result=proposal;}
  else{proposal.preview_json=data.content_json;result=proposal;}
 }
 await route.fulfill({contentType:'application/json',body:JSON.stringify(result)});
});
try{
 await page.goto('http://localhost:3000/#page=editor&id=run~r');
 await page.getByRole('textbox',{name:'文档正文',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:/AI修改章节|AI 修改本节/}).count(),0);
 await page.locator('.workspace-directory').getByRole('button',{name:'2 处理规则',exact:true}).click();
 await page.waitForFunction(()=>window.getSelection()?.anchorNode?.textContent==='2 处理规则');
 const body=page.getByRole('textbox',{name:'文档正文',exact:true});
 await body.evaluate(el=>{
  const heading=el.querySelectorAll('h1')[1],paragraph=heading.nextElementSibling;
  el.focus();const range=document.createRange();range.setStart(heading.firstChild,0);range.setEnd(paragraph.firstChild,paragraph.textContent.length);
  const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);document.dispatchEvent(new Event('selectionchange'));
 });
 await page.getByText(/已选中 \d+ 字作为对话上下文/).waitFor();
 await page.getByLabel('AI 对话模式',{exact:true}).selectOption('modify');
 assert.equal(await page.getByLabel('AI 修改范围',{exact:true}).inputValue(),'blocks');
 await page.getByLabel('AI 对话输入',{exact:true}).fill('补充为空时的说明，缺少依据标待确认');
 await page.getByRole('button',{name:'生成修改提案',exact:true}).click();
 const preview=page.getByRole('textbox',{name:'AI 修改后正文',exact:true});await preview.waitFor();
 assert.deepEqual(w.content_json,original);
 await preview.fill('人工修订的处理规则');await page.getByRole('button',{name:'核对当前预览差异',exact:true}).click();
 await page.locator('.proposal-diff .added').getByText('人工修订的处理规则',{exact:true}).waitFor();
 await page.screenshot({path:'test-results/business-refinement-proposal.png'});
 await page.getByLabel('继续调整提案',{exact:true}).fill('保留我刚才的人工修订，进一步精简');
 await page.getByRole('button',{name:'生成下一轮建议',exact:true}).click();await preview.waitFor({state:'hidden'});
 assert.deepEqual(w.content_json,original);
 await page.locator('.proposal-entry').last().click();await preview.waitFor();await preview.fill('人工最终确认的段落');
 await page.getByRole('button',{name:'确认应用修改',exact:true}).click();await preview.waitFor({state:'hidden'});
 assert.deepEqual(w.content_json.content.slice(0,2),original.content.slice(0,2));assert.deepEqual(w.content_json.content.slice(-2),original.content.slice(-2));
 assert.ok(JSON.stringify(w.content_json).includes('人工最终确认的段落'));
 await page.getByRole('button',{name:'草稿历史',exact:true}).click();await page.getByRole('button',{name:'预览恢复',exact:true}).click();
 await preview.waitFor();assert.deepEqual(w.content_json.content.slice(-2),original.content.slice(-2));
 await page.getByRole('button',{name:'放弃修改',exact:true}).click();
 await page.getByRole('button',{name:'结构检查',exact:true}).click();await page.getByText('接口字段来源待确认',{exact:true}).waitFor();
 await page.getByRole('dialog').getByRole('button',{name:'返回',exact:true}).click();
 await page.screenshot({path:'test-results/business-refinement-workspace.png'});
 await page.goto('http://localhost:3000/#page=task&id=quality');await page.getByRole('button',{name:'分析结果',exact:true}).click();
 await page.getByRole('button',{name:'根据报告修复：测试软需',exact:true}).click();await page.waitForFunction(()=>location.hash.includes('page=editor')&&location.hash.includes('target'));
 assert.ok(requests.some(r=>r.p==='/processing-tasks/quality/repair-proposal'));
 assert.deepEqual(errors,[]);console.log(JSON.stringify({cleanDirectory:true,headingNavigation:true,selectedTextRange:true,editableProposalDiff:true,multiRoundProposal:true,confirmationRequired:true,otherChaptersPreserved:true,historyRestorePreview:true,structureCheck:true,qualityRepairHandoff:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
