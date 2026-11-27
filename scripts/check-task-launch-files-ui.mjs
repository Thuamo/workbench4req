// API fixtures only. This does not upload business files or start live tasks.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';

const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const now='2026-11-26T03:00:00';
const user={id:'owner',username:'fixture',display_name:'任务发起测试',role:'requirement_member'};
const requirement={id:'req',number:'R-001',title:'任务输入文件测试',kind:'business',state:'draft',tags:{},revision:1};
const docs=[];
const linked=[];
const launches=[];
const uploads=[];
const errors=[];
const runs={clarification:[],specification:[],consolidation:[]};
let failUpload=true;

function addDocument(id,title,filename,parseStatus){
 const version={id,document_id:'doc-'+id,label:'V1.0',filename,parse_status:parseStatus,status:'draft',created_at:now};
 docs.push({id:version.document_id,title,kind:'reference',owner_id:user.id,base_id:'base',base_name:'资料库',versions:[version]});
 return version;
}
addDocument('existing','已有业务文件','existing.md','ready');
const consolidationOnly=addDocument('summary','已归档软需','summary.md','ready');
docs.at(-1).kind='specification';
function workspace(){
 const documents=docs.filter(doc=>linked.includes(doc.versions[0].id));
 const sources=documents.map(doc=>({...doc.versions[0],title:doc.title}));
 return {requirement,packs:[{
  id:'pack',number:'B01',name:'需求包',can_change:false,
  stages:{clarification:{documents:[],runs:runs.clarification},specification:{documents,runs:runs.specification},consolidation:{documents:[],runs:runs.consolidation}},
  questions:[],children:[],reviews:[],review_versions:[],publish_jobs:[],
  initialization:{sources,consolidation_sources:[...sources,{...consolidationOnly,title:'已归档软需'}],skills:[],
   extra_skills:[{id:'uml-skill',name:'UML 图生成',workflow:'uml'},{id:'map-skill',name:'思维导图',workflow:'mind_map'}],
   missing:runs.clarification.length?[]:['impact'],target_system:''},
 }]};
}

try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});
 page.setDefaultTimeout(15000);
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname.slice(4);
  let body=[],status=200;
  switch(path){
   case '/auth/me': body=user;break;
   case '/auth/csrf': body={csrf_token:'fixture'};break;
   case '/knowledge-bases': body=[{id:'base',name:'资料库',enabled:true}];break;
   case '/requirements/req/workspace': body=workspace();break;
   case '/documents': body=docs;break;
   case '/uml/diagram-types': body=[{id:'sequence',label:'时序图'}];break;
   case '/requirements/req/packs/pack/stages/specification/documents': {
    const {version_ids}=request.postDataJSON();
    assert.deepEqual(version_ids,['existing']);
    linked.push(...version_ids);
    body={version_ids};
    break;
   }
   case '/documents/upload': {
    const raw=request.postDataBuffer().toString('utf8');
    const filename=raw.match(/filename="([^"]+)"/)[1];
    uploads.push(filename);
    for(const [key,value] of [['requirement_id','req'],['pack_id','pack'],['pack_stage','specification'],['kind','business']]){
     assert.ok(raw.includes(`name="${key}"\r\n\r\n${value}`),key);
    }
    if(filename==='two.md'&&failUpload){
     failUpload=false;
     status=503;
     body={detail:'模拟上传失败'};
    }else{
     const id=filename.split('.')[0];
     body=addDocument(id,id,filename,'pending');
     linked.push(id);
    }
    break;
   }
   case '/requirements/req/packs/pack/launch-tasks':
    launches.push(request.postDataJSON());
    for(const [stage,workflow,title,extra] of [['clarification','impact','变更影响分析',false],
       ['specification','uml','UML 图生成',true],['consolidation','mind_map','思维导图',true]]){
     runs[stage].push({id:workflow,workflow,skill_name:title,requirement_skill_task:extra,status:'pending',
      created_at:now,stage_label:'已排队',inputs:{task:title},result:{}});
    }
    body={task_ids:{impact:'impact','skill:uml-skill':'uml','skill:map-skill':'mind_map'}};
    break;
  }
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(url+'/#page=requirement&id=req&tab=specification-documents&pack=pack',{waitUntil:'domcontentloaded'});
 const stagePanel=page.locator('.requirement-pack-main');
 await stagePanel.getByText('可在「发起任务」中选用已有文件或上传新文件。',{exact:true}).waitFor();
 assert.equal(await stagePanel.getByRole('button',{name:'关联文档',exact:true}).count(),0);
 await page.getByRole('button',{name:'发起任务',exact:true}).click();
 const selection=page.getByRole('dialog',{name:'发起任务 · 选择任务',exact:true});
 await selection.getByRole('checkbox',{name:'UML 图生成',exact:true}).check();
 await selection.getByRole('button',{name:'关联 / 上传文件',exact:true}).click();
 const picker=page.getByRole('dialog',{name:'关联文档',exact:true});
 await picker.getByRole('checkbox',{name:/已有业务文件/}).check();
 await picker.getByRole('button',{name:'确认关联',exact:true}).click();
 await selection.getByText('· 已选 1 个',{exact:true}).waitFor();
 assert.ok(await selection.getByRole('checkbox',{name:'UML 图生成',exact:true}).isChecked());

 await selection.getByRole('button',{name:'关联 / 上传文件',exact:true}).click();
 await picker.getByRole('button',{name:'上传新文档',exact:true}).click();
 const input=picker.locator('input[type=file]');
 assert.match(await input.getAttribute('accept'),/\.py/);
 await input.setInputFiles(['one.py','two.md'].map(name=>({name,mimeType:'text/plain',buffer:Buffer.from('test input')})));
 await picker.getByRole('button',{name:'上传并关联',exact:true}).click();
 await picker.getByText('模拟上传失败',{exact:true}).waitFor();
 await picker.getByRole('button',{name:'重试未成功文件',exact:true}).click();
 await selection.getByText('· 已选 3 个',{exact:true}).waitFor();
 assert.deepEqual(uploads,['one.py','two.md','two.md']);
 assert.equal(launches.length,0);

 await selection.getByRole('checkbox',{name:'变更影响分析',exact:true}).check();
 await selection.getByRole('checkbox',{name:'思维导图',exact:true}).check();
 await selection.getByRole('button',{name:'下一步（3 项）',exact:true}).click();
 const settings=page.getByRole('dialog',{name:'发起任务 · 确认设置',exact:true});
 await settings.getByRole('checkbox',{name:'时序图',exact:true}).check();
 await settings.getByRole('checkbox',{name:/已归档软需.*仅用于沉淀阶段/}).check();
 for(const name of [/已有业务文件/,/one · V1.0/,/two · V1.0/]){
  assert.ok(await settings.getByRole('checkbox',{name}).isChecked());
 }
 const confirm=settings.getByRole('button',{name:'确认发起',exact:true});
 assert.ok(await confirm.isDisabled());
 docs.forEach(doc=>{doc.versions[0].parse_status='ready';});
 await confirm.click();
 await settings.waitFor({state:'hidden'});
 assert.equal(launches.length,1);
 const [launch]=launches;
 assert.deepEqual(launch.stages.map(stage=>stage.stage),['clarification','specification','consolidation']);
 assert.deepEqual(launch.stages[0].basic_tasks,['impact']);
 assert.deepEqual(launch.stages[1].skill_ids,['uml-skill']);
 assert.deepEqual(launch.stages[2].skill_ids,['map-skill']);
 assert.deepEqual(launch.stages.map(stage=>stage.source_version_ids),[
  ['existing','one','two'],['existing','one','two'],['existing','one','two','summary'],
 ]);
 assert.deepEqual(launch.stages[1].diagram_types,['sequence']);
 const titles=['变更影响分析','UML 图生成','思维导图'];
 for(const [index,stage] of ['澄清阶段','软需阶段','沉淀阶段'].entries()){
  await page.getByRole('region',{name:stage,exact:true}).getByRole('button',{name:'关联任务',exact:true}).click();
  await stagePanel.getByText(titles[index],{exact:true}).waitFor();
  for(const title of titles.filter((_,position)=>position!==index)){
   assert.equal(await stagePanel.getByText(title,{exact:true}).count(),0);
  }
  assert.equal(await page.getByRole('button',{name:'发起任务',exact:true}).count(),1);
 }
 await page.getByRole('region',{name:'软需阶段',exact:true}).getByRole('button',{name:'关联文档',exact:true}).click();
 await stagePanel.getByRole('heading',{name:'已有业务文件',exact:true}).waitFor();
 assert.equal(await stagePanel.getByRole('button',{name:'查看版本',exact:true}).count(),3);
 assert.equal(await stagePanel.getByRole('button',{name:'关联文档',exact:true}).count(),0);
 assert.deepEqual(errors,[]);
 console.log('Package entry, one submission for three stages, upload retry, parsing, and stage task lists verified.');
}finally{
 await browser.close();
}
