// All APIs are fixtures: no production uploads, edits, or model requests.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
let user={id:'admin',username:'admin',display_name:'管理员测试',role:'super_admin',enabled:true};
const account={id:'member',username:'member',display_name:'用户甲',role:'requirement_member',enabled:true};
const skills=[{id:'srs',name:'软需生成',command:'/软需生成',description:'编制软需',public:true,enabled:true,current_version_id:'sv1',config:{workflow:'specification'}},{id:'ledger',name:'台账自动填报',command:'/台账',description:'24列填报',public:true,enabled:true,current_version_id:'sv2',config:{workflow:'ledger_fill'}}];
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const now='2026-11-03T08:00:00';const doc={id:'doc',title:'业务输入',base_id:'base',owner_id:'member',kind:'reference',versions:[{id:'v',document_id:'doc',filename:'input.txt',label:'V1.0',status:'draft',parse_status:'ready',creator_id:'member',created_at:now}]};
let messages=[];let resets=0;const chats=[];const works=[];
const page=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.slice(4);let data;try{data=request.postDataJSON();}catch{}let body=[];
 if(p==='/auth/me')body=user;else if(p==='/auth/csrf')body={csrf_token:'fixture'};
 else if(p==='/admin/users')body=[user,account];
 else if(p==='/admin/users/member/reset-password'){resets++;body={ok:true};}
 else if(p==='/skills')body=skills;else if(p==='/documents')body=[doc];else if(p==='/knowledge-bases')body=[{id:'base',name:'业务资料库'}];
 else if(p==='/conversations')body=request.method()==='POST'?{id:'conv',title:'新聊天'}:[{id:'conv',title:'新聊天'}];
 else if(p==='/conversations/conv/messages'){
  if(request.method()==='POST'){
   chats.push(data);messages.push({id:'u'+chats.length,role:'user',content:data.content,skill_id:data.skill_id,skill_name:skills.find(s=>s.id===data.skill_id)?.name,created_at:now},{id:'a'+chats.length,role:'assistant',content:'知识问答响应',citations:[],created_at:now});
   await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({type:'token',content:'知识问答响应'})+'\n\ndata: '+JSON.stringify({type:'done'})+'\n\n'});return;
  }body=messages;
 }else if(/^\/skills\/[^/]+\/execute$/.test(p)){works.push(data);assert.ok(data.source_version_ids.length);body={id:'work-run',status:'pending'};}
 else if(p==='/processing-tasks/work-run')body={id:'work-run',status:'completed',workflow:'ledger_fill',skill_name:'台账自动填报',inputs:{task:'填报RM_00053002'},result:{},documents:[],task_revision:1,created_at:now,requirement_id:null,stage_label:'填报内容待确认'};
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
});
async function sendChat(){const done=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.getByRole('button',{name:'发送消息',exact:true}).click();await done;await page.getByRole('button',{name:'停止',exact:true}).waitFor({state:'hidden'});}
async function attach(){await page.getByRole('button',{name:'附加需求文件',exact:true}).click();const chooser=page.getByRole('dialog',{name:'选择需求附件',exact:true});await chooser.getByRole('checkbox').check();await chooser.getByRole('button',{name:'完成选择',exact:true}).click();}
try{
 await page.goto(url+'/#page=admin',{waitUntil:'domcontentloaded'});const row=page.getByRole('row').filter({hasText:'@member'});await row.getByRole('button',{name:'重置密码',exact:true}).click();const reset=page.getByRole('dialog',{name:'重置用户密码',exact:true});await reset.getByText('mima123',{exact:true}).waitFor();await page.screenshot({path:'test-results/admin-password-reset.png'});await reset.getByRole('button',{name:'取消',exact:true}).click();assert.equal(resets,0);
 await row.getByRole('button',{name:'重置密码',exact:true}).click();await reset.getByRole('button',{name:'确认重置密码',exact:true}).click();await reset.waitFor({state:'hidden'});assert.equal(resets,1);assert.equal(account.enabled,true);
 user=account;await page.goto(url+'/#page=chat&id=conv',{waitUntil:'domcontentloaded'});
 const input=page.getByPlaceholder('输入您的问题');
 await input.fill('/如何核对业务规则？');await sendChat();
 await page.getByText('知识问答响应',{exact:true}).waitFor();
 assert.deepEqual(chats[0],{content:'/如何核对业务规则？',version_ids:[],regenerate:false});
 assert.equal(await page.getByRole('combobox',{name:/问答模式|技能调用模式/}).count(),0);
 assert.equal(await page.getByRole('button',{name:'选择技能',exact:true}).count(),0);
 await attach();await input.fill('结合附件解释');await sendChat();
 assert.deepEqual(chats[1],{content:'结合附件解释',version_ids:['v'],regenerate:false});
 assert.equal(works.length,0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({resetConfirmation:true,resetCancelDoesNothing:true,plainQuestions:true,optionalFiles:true,noTaskExecution:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
