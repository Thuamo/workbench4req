// Browser fixture with no production writes or model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';

const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const now='2026-11-26T03:00:00';
const user={id:'owner',username:'fixture',display_name:'软需变更测试',role:'requirement_member'};
const requirement={id:'req',number:'R-001',title:'软需变更向导',kind:'business',state:'draft',tags:{},revision:1};
const baseline={id:'baseline',title:'已确认软需',filename:'baseline.md',label:'V1.0',parse_status:'ready'};
const source={id:'new-version',title:'新版需求说明书文件',filename:'new.md',label:'V2.0',parse_status:'ready'};
const plan={sources:[source],baseline_versions:[baseline],skills:[],extra_skills:[],missing:['impact'],target_system:''};
const stages={clarification:{documents:[],runs:[]},specification:{documents:[],runs:[]},consolidation:{documents:[],runs:[]}};
const pack={id:'pack',number:'B01',name:'变更包',can_change:true,stages,questions:[],children:[],reviews:[],
 review_versions:[],publish_jobs:[],initialization:plan};
const launches=[];
const applied=[];
const errors=[];
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});
page.setDefaultTimeout(15000);
page.on('pageerror',error=>errors.push(error.message));

await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);
 let body=[];
 if(path==='/auth/me')body=user;
 else if(path==='/auth/csrf')body={csrf_token:'fixture'};
 else if(path==='/knowledge-bases')body=[{id:'base',name:'资料库',enabled:true}];
 else if(path==='/requirements/req/workspace')body={requirement,packs:[pack]};
 else if(path==='/requirements/req/packs/pack/launch-tasks'){
  const data=request.postDataJSON();
  launches.push(data);
  body={task_ids:{specification_change:data.change.mode}};
 }else if(path==='/agent-runs/partial/apply-local-change'){
  applied.push(request.postDataJSON());
  body={workspace_id:'ws-partial'};
 }else if(path.startsWith('/processing-tasks/')){
  const id=path.split('/').at(-1);
  const result=id==='partial'?{local_change:{format:'rich',items:[
   {id:1,section:'提交校验',before:'证件号必填。',after:'证件号选填。',reason:'字段变化'},
   {id:2,section:'验收用例',before:'旧验收口径。',after:'建议调整验收。',reason:'验收联动'},
  ],unresolved:['接口是否同时调整待确认']},...(applied.length?{local_change_application:{workspace_id:'ws-partial'}}:{})}:{};
  body={id,status:'completed',workflow:'specification',result,inputs:{task:'软需变更',_specification_change_mode:id},
   skill_name:'软需变更',requirement,requirement_id:requirement.id,created_at:now,stage_label:'局部变更建议待核对',steps:[],documents:[]};
 }else if(path==='/document-workspaces/open'){
  const {run_id}=request.postDataJSON();
  const content_json={type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'基线工作草稿'}]}]};
  body={id:'ws-'+run_id,run_id,document_id:'doc',version_id:'baseline',requirement_id:'req',title:'已确认软需',label:'V1.1',
   base_id:'base',revision:0,content:'基线工作草稿',content_json,messages:[],sources:[],proposals:[]};
 }
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
});

async function openWizard(){
 await page.goto(url+'/#page=requirement&id=req&tab=specification-tasks&pack=pack',{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'发起任务',exact:true}).click();
 const selection=page.getByRole('dialog',{name:'发起任务 · 选择任务',exact:true});
 await selection.getByRole('checkbox',{name:/^软需变更/}).check();
 await selection.getByRole('button',{name:'下一步（1 项）',exact:true}).click();
 return page.getByRole('dialog',{name:'发起任务 · 确认设置',exact:true});
}

try{
 let wizard=await openWizard();
 for(const width of [1440,375]){
  await page.setViewportSize({width,height:1000});
  const layout=await wizard.locator('.change-mode-picker').evaluate(picker=>{
   const options=[...picker.querySelectorAll('label')];
   return {
    scrolls:picker.scrollWidth>picker.clientWidth||picker.scrollHeight>picker.clientHeight,
    positions:options.map(label=>label.querySelector('input').getBoundingClientRect().toJSON()),
    titleLines:options.map(label=>{
     const text=document.createRange();
     text.selectNodeContents(label.querySelector('strong'));
     return text.getClientRects().length;
    }),
   };
  });
  assert.equal(layout.scrolls,false,`change mode picker scrolls at ${width}px`);
  assert.deepEqual(layout.titleLines,[1,1,1]);
  assert.ok(layout.positions.every((position,index,positions)=>Math.abs(position.y-positions[0].y)<1
   &&(!index||position.x>positions[index-1].x)));
 }
 await page.setViewportSize({width:1440,height:1000});
 assert.ok(await wizard.getByRole('radio',{name:/^局部变更/}).isChecked());
 assert.ok(await wizard.getByRole('button',{name:'生成变更建议',exact:true}).isDisabled());
 await wizard.getByLabel('目标章节（可选）',{exact:true}).fill('提交校验');
 await wizard.getByLabel('变更说明',{exact:true}).fill('将证件号改为选填');
 await wizard.getByRole('button',{name:'生成变更建议',exact:true}).click();
 const review=page.getByRole('region',{name:'局部变更建议',exact:true});
 await review.getByText('接口是否同时调整待确认',{exact:true}).waitFor();
 assert.equal(launches[0].change.mode,'partial');
 assert.equal(launches[0].change.section,'提交校验');
 await review.getByRole('button',{name:'编辑这条建议',exact:true}).first().click();
 await review.getByLabel('编辑第 1 条建议',{exact:true}).fill('证件号改为 **选填**。');
 await review.getByRole('checkbox',{name:/采纳第 1 条/}).check();
 await review.getByRole('button',{name:'应用所选 1 条并编辑',exact:true}).click();
 await page.getByRole('heading',{name:'软需文档编辑工作台',exact:true}).waitFor();
 assert.equal(applied[0].changes.length,1);
 const [edit]=applied[0].changes;
 assert.equal(edit.id,1);
 assert.equal(edit.replacement,'证件号改为 **选填**。');
 assert.deepEqual(edit.content_json.content[0].content[1].marks,[{type:'bold'}]);

 wizard=await openWizard();
 await wizard.getByRole('radio',{name:/^手动改版/}).check();
 assert.equal(await wizard.getByRole('button',{name:'关联 / 上传文件',exact:true}).count(),0);
 await wizard.getByLabel('改版备注（可选）',{exact:true}).fill('调整措辞');
 await wizard.getByRole('button',{name:'创建草稿并编辑',exact:true}).click();
 await page.getByRole('heading',{name:'软需文档编辑工作台',exact:true}).waitFor();
 assert.equal(launches[1].change.mode,'manual');
 assert.equal(launches[1].change.baseline_version_id,'baseline');

 wizard=await openWizard();
 await wizard.getByRole('radio',{name:/^整版重编/}).check();
 const full=wizard.getByRole('button',{name:'生成整版草稿',exact:true});
 assert.ok(await full.isDisabled());
 await wizard.getByRole('checkbox',{name:/新版需求说明书文件/}).check();
 assert.ok(await full.isDisabled());
 await wizard.getByRole('combobox',{name:'新版需求说明书',exact:true}).click();
 await page.getByRole('option',{name:'新版需求说明书文件 · V2.0',exact:true}).click();
 await full.click();
 await wizard.waitFor({state:'hidden'});
 assert.equal(launches[2].change.mode,'full');
 assert.equal(launches[2].change.primary_change_version_id,'new-version');
 assert.deepEqual(errors,[]);
 console.log('Manual draft, scoped review and selective application, and full rework settings verified.');
}finally{
 await browser.close();
}
