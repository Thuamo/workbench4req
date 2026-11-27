// All APIs are fixtures: no production uploads, edits, or model requests.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'owner',username:'fixture',display_name:'文件测试',role:'requirement_member'};
const now='2026-10-30T08:00:00';
const requirement={id:'req',number:'B-001',title:'文件关联测试',description:'背景说明',acceptance:'历史验收字段应保留',tags:{系统:['授信系统'],业务领域:['信贷']},state:'draft',kind:'business',revision:1,source_version_id:null};
const version=(id,parse_status='ready')=>({id,document_id:id,creator_id:user.id,label:'V1.0',filename:id+'.txt',status:'draft',parse_status,review_status:'not_submitted',warnings:[],created_at:now});
const asset=(id,title,parse_status='ready')=>({id,title,owner_id:user.id,base_id:'base',base_name:'需求资料库',folder_id:'child',folder_path:[{id:'parent',name:'业务需求'},{id:'child',name:'授信资料'}],location_path:'需求资料库 / 业务需求 / 授信资料',versions:[version(id,parse_status)],created_at:now});
const docs=[asset('existing','已有业务文档'),asset('failed','解析失败文件','failed')];
let releaseUpload;let parseReady=false;let uploaded=false;let changedRequirement;
const page=await browser.newPage({viewport:{width:1440,height:1100},locale:'zh-CN'});page.setDefaultTimeout(15000);
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.slice(4);let body=[];
 if(p==='/auth/me')body=user;
 else if(p==='/auth/csrf')body={csrf_token:'fixture'};
 else if(p==='/documents/upload'){
  await new Promise(resolve=>{releaseUpload=resolve;});uploaded=true;docs.unshift(asset('new','本次新上传','pending'));body={...version('new','pending'),document_id:'new'};
 }else if(p==='/documents'){
  if(uploaded&&parseReady)docs[0].versions[0].parse_status='ready';body=docs;
 }else if(p==='/knowledge-bases')body=[{id:'base',name:'需求资料库'}];
 else if(p==='/knowledge-bases/base/folders')body=[{id:'parent',base_id:'base',parent_id:null,name:'业务需求'},{id:'child',base_id:'base',parent_id:'parent',name:'授信资料'}];
 else if(p==='/requirements/req/workspace')body={requirement,children:[],source:null,documents:[],runs:[],reviews:[],questions:[],unresolved_questions:0,stage:{code:'draft',label:'需求登记',next_action:'上传资料'}};
 else if(p==='/requirements/req'&&request.method()==='PATCH'){changedRequirement=request.postDataJSON();Object.assign(requirement,changedRequirement,{revision:requirement.revision+1});body=requirement;}
 else if(p==='/requirements')body=[requirement];
 else if(p==='/skills')body=[{id:'skill',name:'已转公共技能',description:'审核通过',command:'/test',public:true,owner_id:user.id,enabled:true,current_version_id:'sv',config:{workflow:'specification'}}];
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto('http://localhost:3000/#page=chat',{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'附加需求文件',exact:true}).click();
 const chooser=page.getByRole('dialog',{name:'选择需求附件',exact:true});
 await chooser.getByText('业务需求',{exact:true}).waitFor();await chooser.getByText('授信资料',{exact:true}).waitFor();
 assert.match(await chooser.textContent(),/位置：需求资料库 \/ 业务需求 \/ 授信资料/);
 assert.ok(await chooser.locator('label').filter({hasText:'解析失败文件'}).getByRole('checkbox').isDisabled());
 await chooser.getByRole('button',{name:'上传新文件',exact:true}).click();
 const upload=page.getByRole('dialog',{name:'上传知识文件',exact:true});
 await upload.locator('input[type=file]').setInputFiles({name:'本次新上传.txt',mimeType:'text/plain',buffer:Buffer.from('test-only')});
 await upload.getByRole('combobox',{name:'目录',exact:true}).click();await page.getByRole('option',{name:'业务需求 / 授信资料',exact:true}).click();
 await upload.getByRole('button',{name:'上传并解析',exact:true}).click();
 await upload.getByRole('status').waitFor();assert.ok(await upload.getByRole('button',{name:'上传中…',exact:true}).isDisabled());
 while(!releaseUpload)await new Promise(resolve=>setTimeout(resolve,25));releaseUpload();
 await upload.waitFor({state:'hidden'});
 const newFile=chooser.locator('label').filter({hasText:'本次新上传'});await newFile.waitFor();
 assert.ok(await newFile.getByRole('checkbox').isDisabled());await newFile.getByText(/正在解析/).waitFor();
 parseReady=true;await newFile.getByRole('checkbox').waitFor();await page.waitForFunction(()=>[...document.querySelectorAll('.document-choice')].find(e=>e.textContent.includes('本次新上传'))?.querySelector('input')?.disabled===false);
 await newFile.getByRole('checkbox').check();await page.screenshot({path:'test-results/attachment-file-tree.png',fullPage:true});
 await chooser.getByPlaceholder('搜索文件名称或目录位置').fill('授信资料');assert.equal(await chooser.locator('.document-choice').count(),3);
 await chooser.getByRole('button',{name:'完成选择',exact:true}).click();await page.locator('.attachment-tag').filter({hasText:'new.txt'}).waitFor();
 await page.goto('http://localhost:3000/#page=requirement&id=req',{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'编辑信息',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'计算需求度量',exact:true}).count(),0);assert.equal(await page.getByRole('heading',{name:'验收标准',exact:true}).count(),0);
 await page.getByRole('button',{name:'编辑信息',exact:true}).click();
 const edit=page.getByRole('dialog',{name:'编辑需求',exact:true});
 assert.deepEqual(await edit.locator('.form-fields > label').evaluateAll(labels=>labels.map(label=>label.firstChild.textContent)),
  ['需求编号','需求名称','背景与功能描述','需求整理状态']);
 await edit.getByRole('combobox',{name:'需求整理状态',exact:true}).click();
 await page.getByRole('option',{name:'澄清中',exact:true}).click();
 await edit.getByRole('button',{name:'保存需求',exact:true}).click();await edit.waitFor({state:'hidden'});
 assert.equal(changedRequirement.state,'clarifying');
 assert.equal(changedRequirement.acceptance,'历史验收字段应保留');
 assert.deepEqual(changedRequirement.tags,{系统:['授信系统'],业务领域:['信贷']});
 await page.getByRole('button',{name:'输入资料',exact:true}).click();await page.getByRole('button',{name:'选择来源版本',exact:true}).click();const source=page.getByRole('dialog',{name:'关联来源版本',exact:true});
 await source.getByRole('button',{name:'上传新文件',exact:true}).click();await upload.waitFor();assert.ok(await upload.locator('input[type=file]').isVisible());await upload.getByRole('button',{name:'取消',exact:true}).click();
 await source.locator('label').filter({hasText:'本次新上传'}).getByRole('radio').check();await source.getByRole('button',{name:'确认关联',exact:true}).click();await source.waitFor({state:'hidden'});assert.equal(changedRequirement.source_version_id,'new');
 await page.goto('http://localhost:3000/#page=skills',{waitUntil:'domcontentloaded'});await page.getByRole('heading',{name:'已转公共技能',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'复制后编辑',exact:true}).count(),1);
 await page.getByRole('button',{name:/运行技能/}).click();const run=page.getByRole('dialog',{name:'运行 /已转公共技能',exact:true});await run.locator('fieldset').filter({has:page.locator('legend').filter({hasText:'本次业务事实与系统资料'})}).getByText('授信资料',{exact:true}).waitFor();
 await page.screenshot({path:'test-results/file-selection-tree.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({uploadBusyFeedback:true,pendingVisibleAndDisabled:true,readySelectableWithoutRefresh:true,folderTreeAndFullLocation:true,failedVisible:true,requirementFieldsRemoved:true,legacyAcceptancePreserved:true,nestedUploadAccessible:true,promotedSkillCopyToEdit:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
