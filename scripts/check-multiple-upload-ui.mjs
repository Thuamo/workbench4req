// All APIs are fixtures: no production uploads, edits, or model requests.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'batch-owner',username:'fixture',display_name:'多选测试',role:'requirement_member'};
const requirement={id:'req',number:'R-001',title:'多文件输入',description:'fixture',acceptance:'',tags:{},state:'draft',revision:1};
const docs=[];const attempts=[];let rejectBeta=true;
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.slice(4);let body=[];let status=200;
 if(p==='/auth/me')body=user;else if(p==='/auth/csrf')body={csrf_token:'fixture'};
 else if(p==='/knowledge-bases')body=[{id:'base',name:'需求资料库'}];
 else if(p==='/knowledge-bases/base/folders')body=[{id:'child',base_id:'base',parent_id:null,name:'批量资料'}];
 else if(p==='/requirements/req/workspace')body={requirement,children:[],source:null,documents:docs,runs:[],reviews:[],questions:[],unresolved_questions:0,stage:{code:'draft',label:'需求登记',next_action:'上传资料'}};
 else if(p==='/documents')body=docs;
 else if(p==='/documents/upload'){
  const raw=request.postDataBuffer().toString('utf8');const filename=raw.match(/filename="([^"]+)"/)[1];attempts.push(filename);
  for(const [key,value] of [['base_id','base'],['folder_id','child'],['requirement_id','req'],['kind','business'],['label','V1.0']])assert.ok(raw.includes('name="'+key+'"\r\n\r\n'+value),key);
  if(filename==='alpha.txt')assert.ok(raw.includes('name="title"\r\n\r\n重命名甲'));
  await new Promise(resolve=>setTimeout(resolve,400));
  if(filename==='beta.txt'&&rejectBeta){rejectBeta=false;status=503;body={detail:'模拟上传失败，可重试'};}
  else{const id=filename.replace('.txt','');docs.push({id,title:filename,base_id:'base',folder_id:'child',base_name:'需求资料库',folder_path:[{id:'child',name:'批量资料'}],location_path:'需求资料库 / 批量资料',kind:'business',owner_id:user.id,versions:[{id,document_id:id,label:'V1.0',filename,parse_status:'pending',status:'draft'}]});body={id,document_id:id};}
 }
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto('http://localhost:3000/#page=requirement&id=req',{waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'输入资料',exact:true}).click();await page.getByRole('button',{name:'上传并关联资料',exact:true}).click();
 const upload=page.getByRole('dialog',{name:'上传知识文件',exact:true});const input=upload.locator('input[type=file]');assert.equal(await input.getAttribute('multiple'),'');
 await input.setInputFiles(['alpha.txt','beta.txt','gamma.txt'].map(name=>({name,mimeType:'text/plain',buffer:Buffer.from(name)})));
 assert.equal(await upload.locator('.upload-entry').count(),3);await upload.getByRole('button',{name:'移除 gamma.txt',exact:true}).click();await upload.getByLabel('文档资产名称：alpha.txt',{exact:true}).fill('重命名甲');
 await upload.getByRole('combobox',{name:'目录',exact:true}).click();await page.getByRole('option',{name:'批量资料',exact:true}).click();
 await upload.getByRole('button',{name:'上传并解析',exact:true}).click();await upload.getByRole('status').waitFor();assert.ok(await upload.getByRole('button',{name:'上传中…',exact:true}).isDisabled());
 await upload.getByText('模拟上传失败，可重试',{exact:true}).waitFor();await upload.getByRole('button',{name:'重试未成功文件',exact:true}).waitFor();assert.deepEqual(attempts,['alpha.txt','beta.txt']);
 assert.equal(await upload.getByLabel('文档资产名称：alpha.txt',{exact:true}).isDisabled(),true);assert.equal(docs.length,1);
 await page.screenshot({path:'test-results/multiple-file-upload.png'});
 await upload.getByRole('button',{name:'重试未成功文件',exact:true}).click();await upload.waitFor({state:'hidden'});assert.deepEqual(attempts,['alpha.txt','beta.txt','beta.txt']);assert.equal(docs.length,2);
 // Both completed uploads immediately appear in the original source selector.
 await page.getByRole('button',{name:'选择来源版本',exact:true}).click();const chooser=page.getByRole('dialog',{name:'关联来源版本',exact:true});await chooser.getByText(/alpha.txt V1.0/).waitFor();await chooser.getByText(/beta.txt V1.0/).waitFor();assert.equal(await chooser.locator('.document-choice').count(),2);assert.equal(await chooser.getByRole('radio').first().isDisabled(),true);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({multipleSelection:true,removeBeforeUpload:true,perFileTitles:true,sharedFolderAndRequirement:true,perFileResult:true,partialFailureRetryOnly:true,successfulFilesNotDuplicated:true,originalPageUpdated:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
