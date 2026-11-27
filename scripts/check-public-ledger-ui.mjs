// Fixture-only UI verification. No real ledger writes, imports or model calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
let user={id:'other',username:'other',display_name:'用户乙',role:'requirement_member'};
const now='2026-11-04T07:00:00';
const tasks=[{id:'a',owner_id:'member',owner_name:'用户甲',fields:{需求编号:'50059',需求名称:'公共计划甲',备注:'甲登记的规则'},status:'pending',requirement_id:'private-req',revision:1,created_at:now},{id:'b',owner_id:'other',owner_name:'用户乙',fields:{需求编号:'50060',需求名称:'公共计划乙',备注:'乙登记的规则'},status:'pending',requirement_id:null,revision:1,created_at:now}];
const columns=['需求编号','需求名称','备注'];const updates=[];let reads=0;
const page=await browser.newPage({viewport:{width:1500,height:1050},locale:'zh-CN'});page.setDefaultTimeout(15000);
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);let body=[];let status=200;
 if(path==='/auth/me')body=user;
 else if(path==='/auth/csrf')body={csrf_token:'fixture'};
 else if(path==='/dashboard')body={counts:{},charts:{},recent:{documents:[],reviews:[],conversations:[]}};
 else if(path==='/clarification/tasks'&&request.method()==='POST'){
  const value=request.postDataJSON();
  assert.equal(value.fields.需求编号,'53681');
  assert.equal(value.requirement_id,null);
  body={id:'new',owner_id:user.id,owner_name:user.display_name,fields:value.fields,status:value.status,
   requirement_id:'matching-req',revision:1,created_at:now};
  tasks.push(body);
 }
 else if(path==='/clarification/tasks'){reads++;body=tasks.map(t=>({...t,can_edit:t.owner_id===user.id,can_delete:t.owner_id===user.id||user.role==='super_admin',can_open_requirement:t.owner_id===user.id&&!!t.requirement_id}));}
 else if(path==='/clarification/columns')body={columns,own_columns:columns,visibility:'public'};
 else if(path==='/clarification/tasks/a/history')body=[{fields:tasks[0].fields,revision:tasks[0].revision,actor_id:'member'}];
 else if(path==='/clarification/batch'){updates.push(request.postDataJSON());body={updated:1};}
 else if(path==='/clarification/tasks/a'&&request.method()==='PATCH'){
  const value=request.postDataJSON();updates.push(value);
  if(value.expected_revision!==tasks[0].revision){status=409;body={detail:'台账已经修改，请刷新'};}
  else{Object.assign(tasks[0],value,{revision:tasks[0].revision+1});body=tasks[0];}
 }
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto('http://localhost:3000/#page=clarification',{waitUntil:'domcontentloaded'});
 const a=page.getByRole('row').filter({hasText:'公共计划甲'}),b=page.getByRole('row').filter({hasText:'公共计划乙'});
 await a.waitFor();assert.ok(await a.getByRole('checkbox').isDisabled());assert.ok(await b.getByRole('checkbox').isEnabled());
 assert.ok(await b.getByRole('button',{name:'关联需求',exact:true}).isVisible());
 assert.equal(await a.getByRole('button',{name:'编辑全部字段',exact:true}).count(),0);assert.equal(await a.getByRole('button',{name:/删除/}).count(),0);
 assert.ok(await a.getByRole('button',{name:'需求详情',exact:true}).isDisabled());
 await a.getByText('甲登记的规则',{exact:true}).dblclick();assert.equal(await a.getByRole('textbox').count(),0);
 await a.getByRole('button',{name:'修改记录',exact:true}).click();await page.getByRole('dialog',{name:'台账修改历史',exact:true}).waitFor();await page.getByRole('dialog').getByRole('button',{name:'返回',exact:true}).click();
 await page.getByRole('checkbox',{name:'选择当前页',exact:true}).check();assert.ok(await b.getByRole('checkbox').isChecked());assert.ok(!(await a.getByRole('checkbox').isChecked()));
 await page.getByRole('button',{name:'取消选择',exact:true}).click();await page.screenshot({path:'test-results/public-clarification-ledger.png'});
 // Another account's updates become visible without reloading this page.
 tasks[0].fields.备注='甲更新后的公共规则';await a.getByText('甲更新后的公共规则',{exact:true}).waitFor();
 user={id:'member',username:'member',display_name:'用户甲',role:'requirement_member'};await page.reload({waitUntil:'domcontentloaded'});
 const own=page.getByRole('row').filter({hasText:'公共计划甲'});await own.getByText('甲更新后的公共规则',{exact:true}).dblclick();await own.getByRole('textbox',{name:'修改备注'}).fill('本页未保存修改');
 assert.equal(await own.getByRole('button',{name:'关联需求',exact:true}).count(),0);
 assert.ok(await own.getByRole('button',{name:'需求详情',exact:true}).isEnabled());
 const oldReads=reads;tasks[0].fields.备注='另一窗口保存的内容';tasks[0].revision=2;
 await page.waitForFunction(()=>true);await page.getByRole('columnheader').filter({hasText:'登记人'}).waitFor();
 const started=Date.now();while(reads===oldReads&&Date.now()-started<12000)await new Promise(r=>setTimeout(r,100));assert.ok(reads>oldReads);
 await own.getByRole('button',{name:'保存字段',exact:true}).click();await page.getByText('台账已经修改，请刷新',{exact:true}).waitFor();assert.equal(updates.at(-1).expected_revision,1);assert.equal(tasks[0].fields.备注,'另一窗口保存的内容');
 await page.getByRole('button',{name:'新增计划',exact:true}).click();
 const create=page.getByRole('dialog',{name:'新增澄清计划',exact:true});
 assert.equal(await create.getByRole('combobox',{name:'关联需求',exact:true}).count(),0);
 await create.getByRole('textbox',{name:'需求编号',exact:true}).fill('53681');
 await create.getByRole('textbox',{name:'需求名称',exact:true}).fill('编号自动关联计划');
 await create.getByRole('button',{name:'保存',exact:true}).click();
 const added=page.getByRole('row').filter({hasText:'编号自动关联计划'});
 await added.waitFor();
 assert.ok(await added.getByRole('button',{name:'需求详情',exact:true}).isEnabled());
 assert.equal(await added.getByRole('button',{name:'关联需求',exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({publicRowsVisible:true,foreignRowsReadOnly:true,privateRequirementNotOpened:true,publicHistory:true,batchOnlyOwnRows:true,crossUserPolling:true,staleEditorRevisionGuard:true,automaticLinkOnCreate:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
