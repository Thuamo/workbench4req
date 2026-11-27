// Browser regression against compiled UI with API fixtures. No production writes/model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const now='2026-10-26T04:00:00';
const user={id:'ui-user',username:'fixture',display_name:'页面测试',role:'requirement_member'};
const requirement={id:'req-ui',number:'UI-001',title:'页面流程测试',description:'测试夹具',tags:{},state:'clarifying',revision:1};
const target={...requirement,id:'target-ui',number:'UI-002',title:'关联目标'};
const task={id:'task-ui',fields:{需求名称:'自定义字段测试',需求编号:'UI-001',额外业务字段:'初始内容',工作量:0},status:'pending',requirement_id:requirement.id,revision:1};
const run={id:'run-ui',status:'awaiting_confirmation',workflow:'specification',skill_version_id:'skill-v1',created_at:now,inputs:{task:'测试生成文档',requirement_id:requirement.id},result:{workflow:'specification',outline:Array.from({length:39},(_,i)=>'第'+(i+1)+'章'),sections:[{title:'技能输出标题',content:'仅展示技能生成正文'}],analysis:{items:[{title:'结构化候选',description:'保留处理记录',tags:{}}]},clarification:{questions:[{description:'保存期限？',blocking:true}]},impact:{relations:[{kind:'接口依赖',description:'影响接口'}]}},citations:[],steps:[],error:'',model_trace:{}};
const skill={id:'skill-ui',name:'测试技能',command:'/测试生成',description:'UI fixture',public:false,owner_id:user.id,enabled:true,current_version_id:'skill-v1',config:{workflow:'specification',system_prompt:'原始 Skill 指令',user_template:'{task}',allowed_tools:['search'],base_ids:[],model_parameters:{temperature:0.2},human_confirmation:true}};
const documents=[];const writes=[];const questions=[];const errors=[];const relations=[];
const plan={sources:[{id:'business-ready',title:'业务说明',label:'V1.0',parse_status:'ready'}],suggested_source_id:'business-ready',target_system:'测试系统',missing:['impact'],skills:[],extra_skills:[{id:'analysis-skill',name:'业务需求解析',workflow:'analysis'},{id:'quality-skill',name:'软需质量核查',workflow:'quality'}],quality_versions:[{id:'spec-ready',title:'测试软需',label:'V1.1',parse_status:'ready'}]};
let page;
try {
  page=await browser.newPage({locale:'zh-CN',viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname.slice(4),method=request.method();
    const body=request.headers()['content-type']?.includes('application/json')?request.postDataJSON():null;
    if(method!=='GET')writes.push({path,method,body});
    let data;
    if(path==='/auth/me')data=user;
    else if(path==='/work-items')data=[];
    else if(path==='/auth/csrf')data={csrf_token:'test-only-csrf'};
    else if(path==='/dashboard')data={counts:{需求:1},charts:{},recent:{documents:[],conversations:[],reviews:[]}};
    else if(path.startsWith('/conversations')||path==='/notifications')data=[];
    else if(path==='/relations')data=relations;
    else if(path==='/relations/relation-ui'&&method==='PATCH'){relations[0].status=body.status;data=relations[0];}
    else if(path==='/knowledge-bases')data=[{id:'base-ui',name:'软件需求说明书库',public:true}];
    else if(path==='/knowledge-bases/base-ui/folders')data=[{id:'folder-ui',name:'接口需求',base_id:'base-ui'}];
    else if(path==='/documents')data=documents;
    else if(path==='/documents/doc-ui/versions/version-ui')data=documents[0].versions[0];
    else if(path==='/requirements')data=[requirement,target];
    else if(path==='/requirements/req-ui/metrics')data=[];
    else if(path==='/requirements/req-ui/workspace')data={requirement,children:[],source:null,documents:[],runs:[run],reviews:[],questions,unresolved_questions:questions.filter(q=>q.status==='open').length,task_initialization:plan,stage:{code:'registered',label:'需求已登记',next_action:'查看任务'}};
    else if(path==='/processing-tasks')data=[{...run,requirement_id:requirement.id,requirement,task_revision:1,skill_name:skill.name,stage:'outline',stage_label:'等待确认提纲',output_count:0}];
    else if(path==='/processing-tasks/run-ui')data={...run,requirement_id:requirement.id,requirement,task_revision:1,skill_name:skill.name,stage:'outline',stage_label:'等待确认提纲',documents:[],output_count:0};
    else if(path==='/requirements/req-ui/launch-tasks'){assert.equal(body.quality_version_id,'spec-ready');assert.deepEqual(body.skill_ids,['quality-skill']);data={created_count:1,task_ids:{}};}
    else if(path==='/clarification/columns')data={columns:Object.keys(task.fields)};
    else if(path==='/clarification/tasks')data=[task];
    else if(path==='/clarification/tasks/task-ui'&&method==='PATCH'){Object.assign(task,body,{revision:task.revision+1});data=task;}
    else if(path==='/clarification/questions')data=questions;
    else if(path==='/skills/import-preview')data={name:'测试技能',description:'fixture',workflow:null,files:['SKILL.md'],capabilities:['生成文本正文'],notice:'脚本不自动执行'};
    else if(path==='/skills/import')data=skill;
    else if(path==='/document-workspaces/open')data={id:'editing-ui',run_id:run.id,document_id:null,version_id:null,title:'软需',label:'V1.0',base_id:'base-ui',folder_id:null,revision:0,confirmed_revision:null,content_json:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'仅展示技能生成正文'}]}]},content:'仅展示技能生成正文',messages:[],proposals:[],sources:[]};
    else if(path==='/document-workspaces/editing-ui/comments')data=[];
    else if(path==='/skills')data=[skill];
    else if(path==='/skills/skill-ui/versions'&&method==='POST'){Object.assign(skill,body);data={id:'skill-v2',config:body.config};}
    else if(path==='/agent-runs')data=[run];
    else if(path==='/agent-runs/run-ui')data=run;
    else if(path==='/agent-runs/run-ui/resume'){assert.equal(body.outline.length,39);run.status='completed';data=run;}
    else if(path==='/agent-runs/run-ui/document-draft'){run.result.editor_draft=body;data={saved:true};}
    else if(path==='/agent-runs/run-ui/edit-document')data={content:body.content+'\n\nAI 编辑建议正文',requires_confirmation:true};
    else if(path==='/agent-runs/run-ui/save'){
      assert.match(body.content,/人工补充内容/);assert.match(body.content,/AI 编辑建议正文/);
      const version={id:'version-ui',document_id:'doc-ui',label:body.label,status:'draft',content:body.content,created_at:now};
      documents.push({id:'doc-ui',title:body.title,base_id:'base-ui',requirement_id:requirement.id,kind:'specification',versions:[version],created_at:now});
      run.result.saved_version_id=version.id;requirement.state='specified';data={...version,requirement_id:requirement.id};
    }
    else if(path==='/agent-runs/run-ui/save-relations'){assert.equal(body.target_id,target.id);run.result.saved_relation_keys=['0:'+target.id];relations.push({id:'relation-ui',source_id:requirement.id,target_id:target.id,kind:'接口依赖',status:'candidate',evidence:{candidate:{description:'影响接口'}}});data={relations};}
    else if(path==='/agent-runs/run-ui/save-questions'){questions.push({id:'question-ui',requirement_id:requirement.id,description:'保存期限？',status:'open',evidence:{}});run.result.saved_question_indices=[0];data={questions};}
    else throw new Error('Unhandled test request '+method+' '+path);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://localhost:3000',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'需求澄清计划',exact:true}).click();
  await page.getByRole('columnheader').filter({hasText:'额外业务字段'}).waitFor();
  await page.getByTitle('编辑全部字段',{exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('额外业务字段',{exact:true}).fill('完整字段已修改');
  await dialog.getByRole('combobox',{name:'关联需求',exact:true}).click();
  await page.getByRole('textbox',{name:'搜索选项'}).fill('关联目标');
  assert.equal(await page.getByRole('option',{name:/页面流程测试/}).count(),0);
  await page.getByRole('option',{name:'UI-002 关联目标',exact:true}).click();
  await dialog.getByRole('button',{name:'保存',exact:true}).click();
  await page.getByText('完整字段已修改',{exact:true}).waitFor();
  assert.equal(task.fields.工作量,0);
  await page.getByTitle('双击修改：额外业务字段',{exact:true}).dblclick();
  await page.getByRole('textbox',{name:'修改额外业务字段',exact:true}).fill('单元格已修改');
  await page.getByTitle('保存字段',{exact:true}).click();
  await page.getByText('单元格已修改',{exact:true}).waitFor();
  await page.getByRole('button',{name:'技能库',exact:true}).click();
  await page.getByRole('button',{name:'编辑',exact:true}).click();
  await page.getByLabel('Skill 指令 / 文档输出要求',{exact:true}).fill('修改后的文档输出指令');
  await page.getByRole('combobox',{name:'技能工作流',exact:true}).click();
  await page.getByRole('textbox',{name:'搜索选项'}).fill('文档');
  await page.getByRole('option',{name:'需求文档生成',exact:true}).click();
  await page.getByRole('button',{name:'保存技能',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.locator('input[type=file][accept=".zip,.skill,.json,.md"]').setInputFiles({name:'测试技能.md',mimeType:'text/markdown',buffer:Buffer.from('# 测试 Skill')});
  await page.getByRole('heading',{name:'确认技能导入配置',exact:true}).waitFor();
  await page.getByRole('combobox',{name:'导入技能工作流',exact:true}).click();
  await page.getByRole('option',{name:'需求文档生成',exact:true}).click();
  await page.getByRole('button',{name:'确认导入',exact:true}).click();
  await page.getByText('技能已按所选工作流导入',{exact:true}).waitFor();
  await page.getByRole('button',{name:/测试生成文档/}).click();
  assert.equal((await page.getByRole('textbox',{name:'需求文档提纲',exact:true}).inputValue()).split('\n').length,39);
  assert.equal(await page.getByRole('checkbox').count(),0);
  await page.getByRole('button',{name:'确认提纲并继续',exact:true}).click();
  await page.getByRole('heading',{name:'软需文档编辑工作台',exact:true}).waitFor();
  assert.equal(await page.getByText('结构化需求确认',{exact:true}).count(),0);
  assert.match(await page.getByRole('textbox',{name:'文档正文',exact:true}).textContent(),/仅展示技能生成正文/);
  await page.getByRole('button',{name:'需求分析与关联',exact:true}).click();
  await page.getByRole('button',{name:'业务需求',exact:true}).click();
  await page.getByRole('heading',{name:'需求分析与关联',exact:true}).waitFor();
  await page.getByRole('row').filter({hasText:'页面流程测试'}).getByRole('button',{name:'需求详情',exact:true}).click();
  await page.getByRole('button',{name:'澄清与关联',exact:true}).click();
  await page.getByText('暂无待处理澄清问题',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'运行影响分析',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'软需质量核查',exact:true}).count(),0);
  await page.getByRole('button',{name:'前往关联任务查看候选结果',exact:true}).click();
  await page.getByRole('button',{name:'发起任务',exact:true}).click();
  await page.getByRole('checkbox',{name:'软需质量核查',exact:true}).check();
  await page.getByRole('button',{name:'下一步（1 项）',exact:true}).click();
  await page.getByRole('combobox',{name:'待核查软需版本',exact:true}).waitFor();
  await page.getByRole('button',{name:'确认发起',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'查看结果',exact:true}).click();
  await page.getByRole('button',{name:'结构化需求（1）',exact:true}).waitFor();
  assert.match(new URL(page.url()).hash,/page=task.*id=run-ui.*tab=analysis/);
  await page.getByRole('button',{name:'澄清问题（1）',exact:true}).click();
  await page.getByRole('combobox',{name:'候选状态筛选',exact:true}).click();
  await page.getByRole('option',{name:'阻塞项',exact:true}).click();
  const questionBox=page.getByRole('checkbox',{name:/保存期限/});
  await questionBox.check();
  await page.getByRole('button',{name:'保存所选澄清问题',exact:true}).click();
  await page.getByText('已保存',{exact:true}).waitFor();
  await page.getByRole('button',{name:'影响候选（1）',exact:true}).click();
  await page.getByRole('combobox',{name:'关联目标需求',exact:true}).click();
  await page.getByRole('option',{name:/UI-002/}).click();
  await page.getByRole('checkbox',{name:/影响接口/}).check();
  await page.getByRole('button',{name:'保存所选关联候选',exact:true}).click();
  await page.getByText('已保存',{exact:true}).waitFor();
  await page.getByRole('button',{name:'查看需求的澄清与关联',exact:true}).click();
  await page.getByRole('heading',{name:'保存期限？',exact:true}).waitFor();
  await page.getByRole('button',{name:'需求关联',exact:true}).click();
  await page.getByRole('button',{name:'确认关联',exact:true}).click();
  await page.getByText('已确认',{exact:true}).waitFor();
  await page.getByRole('button',{name:'需求概览',exact:true}).click();
  await page.getByRole('button',{name:'查看待确认明细',exact:true}).click();
  await page.getByRole('checkbox',{name:/结构化候选/}).waitFor();
  assert.match(new URL(page.url()).hash,/tab=requirements/);
  assert.equal(errors.length,0,errors.join('\n'));
  assert(writes.some(write=>write.path==='/skills/import'));
  assert(writes.some(write=>write.path==='/skills/skill-ui/versions'&&write.body.config.system_prompt==='修改后的文档输出指令'));
  console.log(JSON.stringify({customColumnsEditable:true,searchableDropdown:true,skillEditAndImport:true,outline39Accepted:true,documentOnlyEditor:true,independentEditor:true,candidateReviewInTask:true,followUpInRequirement:true,qualityLaunchInTaskWizard:true,pageErrors:errors,productionWrites:0}));
} catch(error) {
  if(page){await page.screenshot({path:'test-results/editing-ui-failure.png',fullPage:true});console.log(await page.locator('[role=dialog]').innerText().catch(()=>''));console.log(await page.locator('label').evaluateAll(items=>items.map(item=>item.textContent)));}
  throw error;
} finally {await browser.close();}
