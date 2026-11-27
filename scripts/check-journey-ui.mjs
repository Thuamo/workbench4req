// Compiled UI + API fixtures only. Never writes production data or invokes a model.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const now='2026-10-27T04:00:00';
const user={id:'journey-user',username:'fixture',display_name:'动线测试',role:'requirement_member'};
const root={id:'root',number:'REQ-001',title:'授信记录保留',description:'保留处理记录并支持查询',acceptance:'按条件检索成功',tags:{系统:['业务系统']},state:'confirmed',kind:'business',revision:1,source_version_id:'input-v'};
const working={...root,id:'working',kind:'working',title:'未确认的生成草稿',number:'TASK-W'};
const child={...root,id:'child',kind:'detail',parent_id:'root',number:'AI-1',title:'查询明细'};
const sourceVersion={id:'input-v',document_id:'input',label:'V1.0',parse_status:'ready',status:'draft',created_at:now,content:'业务依据',creator_id:user.id,revision:1};
const documents=[{id:'input',title:'业务原件',owner_id:user.id,base_id:'base',kind:'business',requirement_id:'root',folder_id:null,versions:[sourceVersion]}];
const run={id:'run',skill_version_id:'sv',workflow:'specification',inputs:{task:'按需求生成',requirement_id:'root'},result:{workflow:'specification',saved_editor_revision:0,sections:[{title:'需求正文',content:'根据业务依据编写的正文'}],analysis:{items:[{title:'查询记录',description:'按条件查询',acceptance:'查询结果正确',tags:{模块:['查询']}}]},clarification:{questions:[]},impact:{relations:[]}},status:'completed',steps:[],citations:[],created_at:now,error:''};
const skill={id:'skill',name:'软需生成',command:'/软需生成',description:'按技能生成文档',owner_id:user.id,public:false,enabled:true,current_version_id:'sv',config:{workflow:'specification',system_prompt:'按来源生成文档'}};
const tasks=[];const notifications=[{id:'notice',message:'请查看审核进度',resource_id:'review',read:false,created_at:now,destination:{page:'reviews',id:'review'}}];
const writes=[];const errors=[];let page;let review=null;
let editorWorkspace={id:'journey-w',run_id:'run',document_id:null,version_id:null,requirement_id:'root',title:'软件需求说明书',label:'V1.0',base_id:'base',folder_id:null,content_json:null,content:'# 需求正文\n根据业务依据编写的正文',revision:0,confirmed_revision:null,messages:[],proposals:[],sources:[]};
function textOf(node){return (node.text||'')+(node.content||[]).map(textOf).join('\n');}
function latest(){return documents.find(d=>d.kind==='specification')?.versions[0]||null;}
const initialTasks=['clarification','impact','specification','ledger_fill'];
let initialization=null;
let relatedRuns=[];
function initializeFixture(data){
 assert.equal(data.source_version_id,sourceVersion.id);
 const createdCount=initialization.missing.length;
 for(const workflow of initialization.missing){
  const running=workflow==='specification';
  relatedRuns.push({...run,id:workflow,workflow,status:running?'running':'pending',stage:'generating',stage_label:running?'运行中':'已排队',result:{},inputs:{task:workflow}});
 }
 initialization.missing=[];
 return {created_count:createdCount,task_ids:Object.fromEntries(relatedRuns.map(item=>[item.workflow,item.id]))};
}
function workspace(){const version=latest();return {requirement:root,children:[child],task_initialization:initialization,source:{...sourceVersion,title:'业务原件'},documents,runs:initialization?relatedRuns:[{...run,stage_label:run.result.editor_draft?'编辑中 · 已保存进度':'版本已确认',next_action:'继续编辑'}],reviews:review?[review]:[],questions:[],unresolved_questions:0,needs_revision:false,latest_specification:version,stage:{code:version?.status==='pending_review'?'reviewing':version?'version_confirmed':'registered',label:version?.status==='pending_review'?'会签审核中':version?'版本已确认 · 未提交审核':'需求已登记',next_action:version?'提交会签':'准备资料并生成文档'}};}
try{
 page=await browser.newPage({locale:'zh-CN',viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
 await page.route('**/api/**',async route=>{
   const request=route.request(),path=new URL(request.url()).pathname.slice(4),method=request.method();const body=request.headers()['content-type']?.includes('application/json')?request.postDataJSON():null;if(method!=='GET')writes.push({path,body});let data;
   if(path==='/auth/me')data=user;
   else if(path==='/auth/csrf')data={csrf_token:'test-only'};
   else if(path==='/dashboard')data={counts:{业务需求:1},charts:{},recent:{documents:[],reviews:[],conversations:[]}};
   else if(path==='/work-items')data=run.result.saved_version_id&&!run.result.editor_draft?[]:[{id:'work',title:'继续需求文档编辑',stage:'document_ready',label:'正文已生成 · 待编辑确认',action:'继续编辑',created_at:now,destination:{page:'run',id:'run'}}];
   else if(path.startsWith('/conversations'))data=[];
   else if(path==='/notifications')data=notifications;
   else if(path==='/notifications/notice/read'){notifications[0].read=true;data=notifications[0];}
   else if(path==='/knowledge-bases')data=[{id:'base',name:'软件需求说明书库',public:true}];
   else if(path==='/knowledge-bases/base/folders')data=[];
   else if(path==='/documents')data=documents;
   else if(path==='/requirements')data=[root,working,child];
   else if(path==='/requirements/root/workspace')data=workspace();
   else if(path==='/requirements/root/initialize-tasks')data=initializeFixture(body);
   else if(path==='/records/agent_run/impact'&&method==='DELETE'){
     assert.equal(body.confirm,true);
     relatedRuns=relatedRuns.filter(item=>item.id!=='impact');
     initialization.missing=['impact'];
     data={deleted:true,mode:'logical'};
   }
   else if(path==='/requirements/root/metrics')data=[];
   else if(path==='/requirements/root/candidates')data={runs:[run]};
   else if(path==='/clarification/questions'||path==='/relations')data=[];
   else if(path==='/skills')data=[skill];
   else if(path==='/agent-runs')data=[run];
   else if(path==='/agent-runs/run')data=run;
   else if(path==='/processing-tasks')data=[{...run,requirement_id:'root',requirement:root,task_revision:1,skill_name:'软需生成',stage:'document_ready',stage_label:'正文已生成',output_count:0}];
   else if(path==='/processing-tasks/run')data={...run,requirement_id:'root',requirement:root,task_revision:1,skill_name:'软需生成',stage:'document_ready',stage_label:'正文已生成',documents:[],output_count:0};
   else if(path==='/skills/skill/execute'){assert.equal(body.requirement_id,'root');assert(body.source_version_ids.includes('input-v'));assert.match(body.task,/保留处理记录/);data=run;}
   else if(path==='/document-workspaces/open')data=editorWorkspace;
   else if(path==='/document-workspaces/journey-w/comments')data=[];
   else if(path==='/document-workspaces/journey-w'&&method==='PUT'){
     assert.equal(body.expected_revision,editorWorkspace.revision);editorWorkspace={...editorWorkspace,...body,revision:editorWorkspace.revision+1};editorWorkspace.content=textOf(body.content_json);run.result.editor_draft={content:editorWorkspace.content};data=editorWorkspace;
   }
   else if(path==='/document-workspaces/journey-w/confirm'){
     assert.equal(body.expected_revision,editorWorkspace.revision);assert.match(editorWorkspace.content,/页面刷新恢复内容/);
     const version={...sourceVersion,id:'spec-v',document_id:'spec',filename:'软件需求说明书.md',content:editorWorkspace.content,label:editorWorkspace.label,review_status:'not_submitted',publish_status:'not_published',index_status:'not_built',warnings:[],provenance:{},change_note:'人工确认'};
     documents.push({id:'spec',title:editorWorkspace.title,owner_id:user.id,base_id:'base',kind:'specification',folder_id:null,requirement_id:'root',versions:[version],created_at:now});root.state='specified';run.result.saved_version_id='spec-v';delete run.result.editor_draft;data={...version,requirement_id:'root'};
   }
   else if(path==='/documents/spec/versions/spec-v')data=latest();
   else if(path==='/reviewers')data=[{id:'reviewer',display_name:'审核员',username:'reviewer'}];
   else if(path==='/versions/spec-v/submit'||path==='/documents/batch-submit'){
     assert.deepEqual(body.reviewer_ids,['reviewer']);latest().status='pending_review';latest().review_status='pending';review={id:'review',version_id:'spec-v',submitter_id:user.id,status:'pending',note:body.note,created_at:now,document:documents.find(d=>d.id==='spec'),version:latest(),tasks:[{id:'review-task',reviewer_id:'reviewer',reviewer_name:'审核员',decision:'pending',comment:''}]};data=review;
   }
   else if(path==='/reviews')data=review?[review]:[];
   else if(path==='/reviews/review')data=review;
   else throw new Error('Unhandled fixture request '+method+' '+path);
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto(url,{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'继续处理',exact:true}).waitFor();
 await page.getByRole('button',{name:'开启新工作',exact:true}).click();
 await page.getByRole('dialog',{name:'开启新工作'}).waitFor();
 assert.equal(writes.filter(w=>w.path.startsWith('/conversations')).length,0);
 await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'需求分析与关联',exact:true}).click();
 assert.equal(await page.getByRole('row').filter({hasText:'未确认的生成草稿'}).count(),0);
 assert.equal(await page.getByRole('row').filter({hasText:'查询明细'}).count(),0);
 await page.getByRole('button',{name:'业务需求',exact:true}).click();
 await page.getByRole('button',{name:root.title,exact:true}).click();
 assert.match(page.url(),/page=requirement&id=root/);
 await page.getByRole('button',{name:'生成需求文档',exact:true}).click();
 await page.getByRole('dialog',{name:'运行 /软需生成',exact:true}).waitFor();
 await page.getByRole('textbox').filter({visible:true}).first().waitFor();
 const task=page.getByRole('dialog').locator('textarea');
 await page.waitForFunction(()=>document.querySelector('[role=dialog] textarea')?.value.includes('保留处理记录'));
 assert.match(await task.inputValue(),/按条件检索成功/);
 assert.equal(await page.getByRole('checkbox').filter({hasText:''}).count()>0,true);
 await page.getByRole('button',{name:'开始执行',exact:true}).click();
 await page.getByRole('button',{name:'继续编辑文档',exact:true}).click();
 const editor=page.getByRole('textbox',{name:'文档正文',exact:true});await editor.waitFor();
 await editor.fill('# 需求正文\n人工未保存内容');
 await page.getByRole('button',{name:'技能库',exact:true}).click();
 await page.getByRole('dialog',{name:'保存编辑后离开？'}).waitFor();
 await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 assert.match(await editor.textContent(),/人工未保存内容/);
 await page.getByRole('button',{name:'技能库',exact:true}).click();
 await page.getByRole('button',{name:'保存并离开',exact:true}).click();
 await page.getByRole('heading',{name:'技能库',exact:true}).waitFor();
 assert.match(run.result.editor_draft.content,/人工未保存内容/);
 await page.goBack();
 await editor.waitFor();assert.match(await editor.textContent(),/人工未保存内容/);
 await editor.fill('# 需求正文\n页面刷新恢复内容');
 await page.waitForFunction(()=>Object.keys(sessionStorage).some(k=>k.startsWith('document-workspace:')&&sessionStorage.getItem(k).includes('页面刷新恢复内容')));
 await page.reload({waitUntil:'networkidle'});
 await editor.waitFor();await page.getByRole('button',{name:'核对本页暂存',exact:true}).click();
 await page.getByRole('button',{name:'恢复到正文并核对',exact:true}).click();assert.match(await editor.textContent(),/页面刷新恢复内容/);
 await page.getByRole('button',{name:'确认版本并返回任务',exact:true}).click();
 await page.waitForFunction(()=>location.hash.includes('page=task'));
 await page.getByRole('button',{name:'REQ-001 授信记录保留',exact:true}).click();
 await page.getByText('版本已确认 · 未提交审核',{exact:true}).waitFor();
 await page.reload({waitUntil:'networkidle'});assert.match(page.url(),/page=requirement&id=root/);
 await page.getByRole('heading',{name:root.title,exact:true}).waitFor();
 await page.screenshot({path:'test-results/requirement-workspace.png',fullPage:true});
 await page.getByRole('button',{name:'提交会签',exact:true}).click();
 await page.getByRole('checkbox').check();
 await page.getByRole('dialog').getByRole('button',{name:'确认提交审核',exact:true}).click();
 await page.getByText('会签审核中',{exact:true}).waitFor();
 assert.equal(latest().status,'pending_review');
 await page.getByRole('button',{name:'通知',exact:true}).click();
 await page.getByRole('button',{name:/请查看审核进度/}).click();
 await page.waitForURL('**/#page=reviews&id=review');
 assert.match(page.url(),/page=reviews&id=review/);
 await page.getByRole('dialog').getByText('审核员',{exact:true}).waitFor();
 initialization={missing:initialTasks.slice(1),sources:[{...sourceVersion,title:'业务原件'}],
   suggested_source_id:sourceVersion.id,target_system:'业务系统',skills:[{id:skill.id,name:skill.name,human_confirmation:true}]};
 relatedRuns=[{...run,id:'prior-clarification',workflow:'clarification',stage:'analysis_ready',stage_label:'已完成'}];
 await page.goto(url+'/#page=requirement&id=root',{waitUntil:'domcontentloaded'});
 await page.getByRole('heading',{name:root.title,exact:true}).waitFor();
 const initialize=page.getByRole('button',{name:'初始化任务',exact:true});
 assert.equal(await initialize.count(),0);
 await page.getByRole('button',{name:'关联任务',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'单独生成需求文档',exact:true}).count(),0);
 await initialize.click();
 const rows=page.locator('.requirement-workspace .initialization-step');
 await rows.filter({hasText:'澄清台账自动填报'}).waitFor();
 assert.deepEqual(await rows.locator('strong').allTextContents(),['需求缺口识别','变更影响分析','生成软需草稿','澄清台账自动填报']);
 assert.equal(writes.filter(w=>w.path==='/requirements/root/initialize-tasks').length,1);
 assert.equal(relatedRuns[0].id,'prior-clarification');
 assert.ok(await initialize.isDisabled());
 assert.ok(await rows.filter({hasText:'生成软需草稿'}).getByRole('button',{name:'删除',exact:true}).isDisabled());
 const impactRow=rows.filter({hasText:'变更影响分析'});
 await impactRow.getByRole('button',{name:'删除',exact:true}).click();
 await page.getByRole('dialog',{name:'确认删除执行任务',exact:true}).getByRole('button',{name:'确认删除',exact:true}).click();
 await impactRow.waitFor({state:'detached'});
 await initialize.click();
 await impactRow.waitFor();
 assert.equal(writes.filter(w=>w.path==='/requirements/root/initialize-tasks').length,2);
 assert.equal(relatedRuns.length,4);
 assert.equal(errors.length,0,errors.join('\n'));
 console.log(JSON.stringify({intentCreatesNoEmptyChat:true,hierarchyViews:true,contextInherited:true,leaveProtection:true,saveAndResume:true,browserBack:true,refreshRestoresDraft:true,deepLinkRestored:true,submitFromRequirement:true,notificationDeepLink:true,initializationAddsOnlyMissingRows:true,pageErrors:errors,productionWrites:0}));
}catch(error){if(page){await page.screenshot({path:'test-results/journey-ui-failure.png',fullPage:true});console.log((await page.locator('main').innerText()).slice(-3500));console.log(errors);}throw error;}finally{await browser.close();}
