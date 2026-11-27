// Isolated UI contract fixtures. API calls are intercepted before they reach a backend.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const errors=[];
const file=name=>({name,mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('test-only workbook fixture')});
const oldTask={id:'old-1',fields:{需求编号:'OLD-1',需求名称:'原计划',旧字段:'原内容'},status:'pending',requirement_id:null,revision:1};
const newTask={id:'new-1',fields:{需求编号:'NEW-1',需求名称:'新计划',新字段:'新内容'},status:'pending',requirement_id:null,revision:1};
const batch={id:'batch-1',filename:'计划.xlsx',created_at:'2026-11-27T02:00:00',added:1,updated:1,undone:false};
const previewRows=[
  {sheet:'Sheet1',row:2,number:'NEW-1',name:'新计划',action:'add',reason:'',changed_fields:[]},
  {sheet:'Sheet1',row:3,number:'OLD-1',name:'更新计划',action:'update',reason:'',changed_fields:['需求名称','新字段']},
  {sheet:'Sheet1',row:4,number:'DUP',name:'重复计划',action:'conflict',reason:'Excel 中的需求编号重复',changed_fields:[]},
];
let tasks=[oldTask],batches=[],revision=1,importCount=0,undoCount=0;
let page;
const columns=['需求编号','需求名称','旧字段'];
async function multipart(request){
  return new Request(request.url(),{method:'POST',headers:request.headers(),body:request.postDataBuffer()}).formData();
}
try {
  page=await browser.newPage({locale:'zh-CN',viewport:{width:1440,height:1000}});
  page.setDefaultTimeout(15000);
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
    const request=route.request();
    const path=new URL(request.url()).pathname.slice(4);
    let body,status=200;
    if(path==='/auth/me') body={id:'ui',username:'fixture',display_name:'导入测试',role:'requirement_member'};
    else if(path==='/auth/csrf') body={csrf_token:'test-only'};
    else if(path==='/dashboard') body={counts:{},charts:{},recent:{documents:[],reviews:[],conversations:[]}};
    else if(path==='/work-items'||path==='/notifications'||path.startsWith('/conversations')||path==='/requirements'||path==='/clarification/questions') body=[];
    else if(path==='/clarification/tasks') body=tasks;
    else if(path==='/clarification/columns') body={columns:tasks.length>1?[...columns,'新字段']:columns};
    else if(path==='/clarification/import-preview'){
      const data=await multipart(request);
      if(data.get('file').name==='invalid.xlsx'){status=422;body={detail:'表格没有有效任务行'};}
      else body={incoming_count:3,snapshot:'snapshot-'+revision,added:1,updated:1,unchanged:0,conflicts:1,rows:previewRows};
    } else if(path==='/clarification/import'){
      importCount++;
      const data=await multipart(request);
      assert.equal(data.has('confirm_replace'),false);
      if(data.get('expected_snapshot')!=='snapshot-'+revision){status=409;body={detail:'台账已变化，请重新预览'};}
      else {
        tasks=[{...oldTask,revision:2,fields:{...oldTask.fields,需求名称:'更新计划',新字段:'更新值'}},newTask];
        batches=[batch];
        body={added:1,updated:1,unchanged:0,conflicts:1,batch_id:batch.id};
      }
    } else if(path==='/clarification/imports') body=batches;
    else if(path==='/clarification/imports/batch-1/undo'){
      undoCount++;
      tasks=[oldTask];
      batches=[{...batch,undone:true}];
      body={batch_id:batch.id,undone:true};
    } else throw new Error('Unhandled fixture request '+request.method()+' '+path);
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  const base=process.env.LEDGER_UI_URL||'http://localhost:3000';
  await page.goto(base+'/#page=clarification',{waitUntil:'domcontentloaded',timeout:60000});
  const input=page.locator('input[type=file][accept=".xlsx"]');
  await page.getByRole('columnheader').filter({hasText:'旧字段'}).waitFor();
  await input.setInputFiles(file('计划.xlsx'));
  const modal=page.getByRole('dialog',{name:'预览 Excel 增量导入'});
  await modal.getByRole('button',{name:'冲突 1',exact:true}).click();
  await modal.getByText('Excel 中的需求编号重复',{exact:true}).waitFor();
  assert.equal(importCount,0);
  await modal.getByRole('button',{name:'关闭',exact:true}).last().click();
  assert.equal(importCount,0);
  await input.setInputFiles(file('计划.xlsx'));
  const confirm=modal.getByRole('button',{name:'确认导入',exact:true});
  await modal.getByRole('button',{name:'更新 1',exact:true}).click();
  await modal.getByText('需求名称、新字段',{exact:true}).waitFor();
  revision++;
  await confirm.click();
  await modal.getByRole('alert').filter({hasText:'重新预览'}).waitFor();
  assert.equal(await confirm.isDisabled(),true);
  assert.deepEqual(tasks,[oldTask]);
  await modal.getByRole('button',{name:'重新预览',exact:true}).click();
  await confirm.click();
  await modal.waitFor({state:'hidden'});
  await page.getByText('更新计划',{exact:true}).waitFor();
  await page.getByText('新计划',{exact:true}).waitFor();
  assert.equal(tasks[0].id,'old-1');
  await page.getByRole('columnheader').filter({hasText:'旧字段'}).waitFor();
  await page.getByRole('columnheader').filter({hasText:'新字段'}).waitFor();

  await page.getByRole('button',{name:'导入记录',exact:true}).click();
  const history=page.getByRole('dialog',{name:'导入记录'});
  await history.getByRole('button',{name:'撤销批次'}).click();
  await page.getByRole('dialog',{name:'撤销导入批次'}).getByRole('button',{name:'确认撤销'}).click();
  await history.getByText('已撤销',{exact:true}).waitFor();
  assert.equal(undoCount,1);
  await history.getByRole('button',{name:'返回',exact:true}).click();
  await page.getByText('原计划',{exact:true}).waitFor();

  await input.setInputFiles(file('invalid.xlsx'));
  await modal.getByRole('alert').filter({hasText:'表格没有有效任务行'}).waitFor();
  assert.equal(await confirm.isDisabled(),true);
  assert.equal(importCount,2);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({previewAndConflicts:true,staleConfirmationBlocked:true,incrementalImport:true,batchUndo:true,invalidWorkbookBlocked:true}));
} catch(error) {
  if(page) console.error(await page.locator('body').innerText(), errors);
  throw error;
} finally {
  await browser.close();
}

