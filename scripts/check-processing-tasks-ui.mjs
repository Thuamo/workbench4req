// Independent task/requirement UI fixtures. Every API request is intercepted.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'task-owner',username:'fixture',display_name:'任务测试',role:'requirement_member'};
const now='2026-10-29T08:00:00';
const reqs=[{id:'req1',number:'BUS-001',title:'ESG 评级改造',kind:'business',state:'confirmed',description:'业务需求',acceptance:'验收',tags:{},revision:1},{id:'req2',number:'BUS-002',title:'授信流程优化',kind:'business',state:'draft',description:'',acceptance:'',tags:{},revision:1}];
const versions=[{id:'v2',document_id:'doc',label:'V1.1',status:'draft',review_status:'not_submitted',parse_status:'ready',creator_id:user.id,created_at:now},{id:'v1',document_id:'doc',label:'V1.0',status:'approved',review_status:'approved',parse_status:'ready',creator_id:user.id,created_at:now}];
const doc={id:'doc',title:'ESG 软件需求说明书',kind:'specification',owner_id:user.id,base_id:'base',requirement_id:'req1',versions,created_at:now,task_ids:['t1','t2'],roles:['output']};
const tasks=[['t1','编制 ESG 软需','specification','req1'],['t2','分析 ESG 影响','impact','req1'],['t3','待关联的生成任务','specification',null]].map(([id,title,workflow,rid])=>({id,inputs:{task:title,requirement_id:rid},requirement_id:rid,requirement:reqs.find(r=>r.id===rid)||null,task_revision:1,needs_review:false,workflow,skill_name:'业务技能',stage:'document_ready',stage_label:'正文已生成 · 待编辑确认',next_action:'继续编辑',status:'completed',created_at:now,result:{sections:[{title:'需求背景',content:'正文'}]},steps:[],documents:id==='t1'||id==='t2'?versions.map(v=>({role:'output',document:doc,version:v})):[],output_count:id==='t3'?0:1}));
const page=await browser.newPage({viewport:{width:1600,height:1050},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));let stale=true;
await page.route('**/api/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.slice(4),method=request.method();let data;try{data=request.postDataJSON();}catch{}let body=[];let status=200;
 if(p==='/auth/me')body=user;else if(p==='/auth/csrf')body={csrf_token:'fixture'};
 else if(p==='/requirements')body=reqs.map(r=>({...r,task_count:tasks.filter(t=>t.requirement_id===r.id).length,document_count:r.id==='req1'?1:0}));
 else if(p==='/processing-tasks')body=tasks;
 else if(p.startsWith('/processing-tasks/')){
  const task=tasks.find(t=>t.id===p.split('/')[2]);assert.ok(task);
  if(p.endsWith('/requirement')){
   if(task.id==='t1'){status=409;body={detail:'任务已有审核或历史版本，请新建关联任务'};}
   else if(stale){stale=false;task.task_revision++;status=409;body={detail:'任务关联已被其他页面修改，请刷新后重试'};}
   else{assert.equal(data.expected_revision,task.task_revision);task.requirement_id=data.requirement_id;task.requirement=reqs.find(r=>r.id===data.requirement_id)||null;task.task_revision++;body=task;}
  }else body=task;
 }else if(p==='/requirements/req1/workspace')body={requirement:reqs[0],children:[],source:null,documents:[doc],runs:tasks.filter(t=>t.requirement_id==='req1'),reviews:[],questions:[],unresolved_questions:0,stage:{code:'version_confirmed',label:'版本已确认 · 未提交审核',next_action:'提交会签'},latest_specification:versions[0]};
 else if(p.startsWith('/agent-runs/'))body=tasks.find(t=>t.id===p.split('/')[2]);
 else if(p==='/documents')body=[doc];else if(p==='/knowledge-bases')body=[{id:'base',name:'软件需求说明书库'}];
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto('http://localhost:3000/#page=requirements');await page.getByRole('button',{name:'处理任务',exact:true}).click();
 await page.getByRole('row').filter({hasText:'待关联的生成任务'}).waitFor();assert.equal(await page.getByRole('button',{name:'工作草稿',exact:true}).count(),0);
 await page.getByRole('button',{name:'业务需求',exact:true}).click();await page.getByRole('row').filter({hasText:'BUS-001'}).waitFor();assert.equal(await page.getByRole('row').filter({hasText:'待关联的生成任务'}).count(),0);assert.equal(await page.getByRole('row').filter({hasText:'编制 ESG 软需'}).count(),0);
 await page.getByRole('row').filter({hasText:'BUS-001'}).getByRole('button',{name:'需求详情',exact:true}).click();await page.getByRole('button',{name:'关联任务',exact:true}).click();await page.getByRole('heading',{name:'关联任务',exact:true}).waitFor();assert.equal(await page.locator('.requirement-workspace .initialization-step').count(),2);
 await page.getByRole('button',{name:'关联文档',exact:true}).click();assert.equal(await page.locator('.requirement-workspace .workspace-document').count(),1);await page.getByText('展开文档版本',{exact:true}).click();await page.getByText('V1.1 · 版本已确认 · 未提交审核',{exact:true}).waitFor();
 await page.getByRole('button',{name:'需求分析与关联',exact:true}).click();await page.getByRole('button',{name:'处理任务',exact:true}).click();await page.getByRole('row').filter({hasText:'待关联的生成任务'}).getByRole('button',{name:'任务详情',exact:true}).click();
 await page.getByRole('button',{name:'关联业务需求',exact:true}).click();await page.getByRole('combobox',{name:'任务关联业务需求',exact:true}).click();await page.getByRole('textbox',{name:'搜索选项'}).fill('BUS-001');await page.getByRole('option',{name:'BUS-001 ESG 评级改造',exact:true}).click();await page.getByRole('button',{name:'保存关联',exact:true}).click();await page.getByRole('alert').getByText('任务关联已被其他页面修改，请刷新后重试',{exact:true}).waitFor();await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
 await page.getByRole('button',{name:'关联业务需求',exact:true}).click();await page.getByRole('combobox',{name:'任务关联业务需求',exact:true}).click();await page.getByRole('option',{name:'BUS-001 ESG 评级改造',exact:true}).click();await page.getByRole('button',{name:'保存关联',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});await page.getByRole('button',{name:'BUS-001 ESG 评级改造',exact:true}).waitFor();assert.equal(tasks[2].inputs.requirement_id,null);
 await page.screenshot({path:'test-results/processing-task-detail.png',fullPage:true});
 await page.getByRole('button',{name:'BUS-001 ESG 评级改造',exact:true}).click();await page.getByRole('button',{name:'关联任务',exact:true}).click();await page.getByRole('heading',{name:'关联任务',exact:true}).waitFor();assert.equal(await page.locator('.requirement-workspace .initialization-step').count(),3);
 await page.locator('.initialization-step').filter({hasText:'生成软需草稿'}).first().getByRole('button',{name:'任务详情',exact:true}).click();await page.getByRole('button',{name:'更换关联需求',exact:true}).click();await page.getByRole('combobox',{name:'任务关联业务需求',exact:true}).click();await page.getByRole('option',{name:'BUS-002 授信流程优化',exact:true}).click();await page.getByRole('button',{name:'保存关联',exact:true}).click();await page.getByRole('alert').getByText('任务已有审核或历史版本，请新建关联任务',{exact:true}).waitFor();assert.equal(tasks[0].requirement_id,'req1');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({separateTaskAndRequirementTabs:true,oneRequirementManyTasks:true,documentsGroupedByAsset:true,taskRequirementSearch:true,staleAssociationBlocked:true,currentLinkDistinctFromInputSnapshot:true,reviewedTaskReassignmentBlocked:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
