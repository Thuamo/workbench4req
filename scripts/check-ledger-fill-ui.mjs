// Independent task/requirement UI fixtures. Every API request is intercepted.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'ledger-owner',username:'fixture',display_name:'填报测试',role:'requirement_member'};
const columns=['需求编号','需求名称','申请部门','业务对接人','澄清周','业务紧急程度','实施对接人','软需负责人','澄清时间','澄清结果','会议结论','备注','关注程度','软需进展','软需完成时间','业务对象','业务阶段','产品名称','需求价值目标','科技属性','改进方向','价值度量-客观价值','战略关联度-主观优先级','工作量'];
const fields=Object.fromEntries(columns.map(c=>[c,null]));Object.assign(fields,{'需求编号':'RM_00053002','需求名称':'已登记需求','申请部门':'已登记部门','工作量':0});
const task={id:'ledger-run',workflow:'ledger_fill',skill_name:'澄清台账自动填报',status:'completed',inputs:{task:'RM_00053002-澄清台账自动填报'},result:{clarification:{questions:[{description:'旧错误候选'}]}},requirement_id:null,requirement:null,task_revision:1,documents:[],created_at:'2026-11-02T08:00:00',stage_label:'填报内容待确认',output_count:0};
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));let generation=0;let confirmed=0;let stale=true;let saved;
await page.route('**/api/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.slice(4);let data;try{data=request.postDataJSON();}catch{}let body=[];let status=200;
 if(p==='/auth/me')body=user;else if(p==='/auth/csrf')body={csrf_token:'fixture'};
 else if(p==='/processing-tasks/ledger-run'||p==='/agent-runs/ledger-run')body=task;
 else if(p.endsWith('/ledger-preview')){generation++;task.result.ledger_preview={columns,fields:{...fields},baseline:{task_id:'existing',fields:{'需求编号':fields['需求编号'],'需求名称':fields['需求名称'],'申请部门':fields['申请部门'],'工作量':0}},revision:'preview-1'};body=task.result.ledger_preview;}
 else if(p.endsWith('/ledger-confirm')){assert.equal(data.confirm,true);assert.deepEqual(Object.keys(data.fields),columns);assert.equal(data.fields['工作量'],0);assert.equal(data.fields['业务对象'],'人工核对分类');if(stale){status=409;body={detail:'原表列或同编号台账已变化，请重新生成预览，当前台账未修改'};stale=false;}else{saved=data.fields;confirmed++;task.result.saved_ledger_task_id='existing';task.result.saved_ledger_fields=data.fields;task.result.saved_ledger_columns=columns;body={task_id:'existing'};}}
 else if(p==='/clarification/tasks')body=saved?[{id:'existing',fields:saved,status:'pending',revision:2,requirement_id:null}]:[];
 else if(p==='/clarification/columns')body={columns};
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto('http://localhost:3000/#page=task&id=ledger-run',{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'生成24列填报预览',exact:true}).click();await page.getByLabel('填报 需求编号',{exact:true}).waitFor();assert.equal(generation,1);assert.equal(confirmed,0);
 assert.deepEqual(await page.locator('.ledger-fill-result tbody th').allTextContents(),columns);assert.equal(await page.locator('.ledger-fill-result input').count(),24);
 assert.equal(await page.getByLabel('填报 工作量',{exact:true}).inputValue(),'0');assert.equal(await page.getByLabel('填报 工作量',{exact:true}).getAttribute('readonly'),'');
 await page.getByLabel('填报 业务对象',{exact:true}).fill('人工核对分类');await page.getByText('查看按原表顺序排列的单行 TSV（24列）',{exact:true}).click();assert.equal((await page.locator('.ledger-fill-result pre').textContent()).split('\t').length,24);
 await page.screenshot({path:'test-results/ledger-fill-24-columns.png',fullPage:true});
 await page.getByRole('button',{name:'确认内容并写入澄清计划',exact:true}).click();await page.getByRole('alert').getByText(/原表列或同编号台账已变化/).waitFor();assert.equal(confirmed,0);assert.equal(await page.getByLabel('填报 业务对象',{exact:true}).inputValue(),'人工核对分类');
 await page.getByRole('button',{name:'确认内容并写入澄清计划',exact:true}).click();await page.getByText('已确认24列内容（本次快照）',{exact:true}).waitFor();await page.getByRole('button',{name:'查看澄清计划',exact:true}).click();await page.getByRole('row').filter({hasText:'RM_00053002'}).waitFor();assert.equal(confirmed,1);assert.equal(await page.getByRole('row').filter({hasText:'RM_00053002'}).count(),1);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({legacyGenerateEntry:true,exact24ColumnOrder:true,registeredAndZeroLocked:true,editablePreview:true,tsv24Cells:true,explicitConfirmOnly:true,conflictPreservesEdits:true,viewInsertedLedgerRow:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
