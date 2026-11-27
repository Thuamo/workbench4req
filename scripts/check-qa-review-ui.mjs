// All API routes are fixtures: no business writes or real model requests.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const user={id:'owner',username:'member',display_name:'问答送审测试',role:'requirement_member',enabled:true};
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const now='2026-11-04T02:00:00';
function asset(id,title,label='V1',parse='ready',creator='owner'){
 const version={id:'v-'+id,document_id:id,creator_id:creator,label,filename:title+label+'.md',content:'评级为空时阻断提交。',blocks:[],warnings:[],status:'draft',parse_status:parse,review_status:'not_submitted',publish_status:'not_published',index_status:'not_built',revision:1,created_at:now};
 return {id,title,owner_id:creator,base_id:'base',base_name:'业务资料库',folder_id:'folder',folder_path:[{id:'folder',name:'评级规则'}],location_path:'业务资料库 / 评级规则',kind:'reference',versions:[version],created_at:now};
}
const docs=[asset('a','51380-评级规则','V2'),asset('b','51380-评级规则','V3'),asset('pending','解析中的文档','V1','pending')];
const skill={id:'srs',name:'软需生成',description:'编制软件需求说明书',command:'/软需生成',enabled:true,public:true,config:{workflow:'specification'}};
const legacyCitation={citation_id:'old',locator:'2 历史规则',excerpt:'原历史记录的完整内容。',scope:'mine',formal:false,status:'draft'};
let messages=[{id:'old-reply',role:'assistant',qa_mode:'knowledge',generation_status:'completed',created_at:now,citations:[legacyCitation],
 content:'### 资料记载与规则依据\n\n- 历史回答正文。〔来源1〕\n  > 原文：旧版第一行\n  > 旧版第二行\n\n### 建议核实\n\n- 待确认事项。'}];
const chats=[],batches=[],works=[];let rejectBatch=true;
const page=await browser.newPage({viewport:{width:1600,height:1150},locale:'zh-CN'});page.setDefaultTimeout(15000);
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);let data;try{data=request.postDataJSON();}catch{}
 let body=[];
 if(path==='/auth/me')body=user;
 else if(path==='/auth/csrf')body={csrf_token:'fixture'};
 else if(path==='/knowledge-bases')body=[{id:'base',name:'业务资料库',public:true}];
 else if(path==='/knowledge-bases/base/folders')body=[{id:'folder',name:'评级规则',base_id:'base',parent_id:null}];
 else if(path==='/documents')body=docs;
 else if(path==='/reviewers')body=[{id:'reviewer',username:'reviewer',display_name:'审核员甲'}];
 else if(path==='/documents/batch-submit'){
  batches.push(data);
  if(rejectBatch){rejectBatch=false;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{message:'批量提交未完成，所有文件均未提交',reason:'文件已被修改，请刷新后重新选择',version_id:'v-b'}})});return;}
  for(const doc of docs)if(data.version_ids.includes(doc.versions[0].id)){doc.versions[0].status='pending_review';doc.versions[0].review_status='pending';}
  body={submitted:data.version_ids.length,requests:data.version_ids.map(id=>({id:'review-'+id,version_id:id}))};
 }else if(path==='/skills')body=[skill];
 else if(path==='/conversations')body=request.method()==='POST'?{id:'conv-new',title:'新聊天'}:[{id:'conv',title:'知识问答测试'}];
 else if(path==='/conversations/conv/messages'||path==='/conversations/conv-new/messages'){
  if(request.method()==='POST'){
   chats.push(data);const n=chats.length;
   const citations=[{citation_id:'c'+n,document_id:'a',document_version_id:'v-a',title:docs[0].title,version:'V2',locator:'3 校验规则',excerpt:'检查结果：评级为空时阻断提交。',quotes:['评级为空时阻断提交。'],scope:'selected',formal:false,status:'draft'}];
   const meta={scopes:['formal','mine',...(data.version_ids.length?['selected']:[])],document_count:1,evidence_count:1,unreviewed_count:1,retrieval:'关键词检索',warnings:['未配置向量模型，使用关键词检索。']};
   const answer='评级规则说明。〔来源1〕';
   messages.push({id:'u'+n,role:'user',content:data.content,qa_mode:data.qa_mode,scopes:data.scopes,created_at:now,version_ids:data.version_ids},{id:'a'+n,role:'assistant',content:answer,citations,candidate_citations:citations,retrieval:meta,qa_mode:data.qa_mode,generation_status:'completed',created_at:now});
   await route.fulfill({contentType:'text/event-stream',body:[{type:'retrieval',meta},{type:'token',content:answer},{type:'sources',citations},{type:'done'}].map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')});return;
  }body=messages;
 }else if(/^\/documents\/[^/]+\/versions\//.test(path)){const parts=path.split('/');body=docs.find(d=>d.id===parts[2])?.versions.find(v=>v.id===parts[4]);}
 else if(/^\/documents\/[^/]+\/versions$/.test(path))body=docs.find(d=>d.id===path.split('/')[2])?.versions;
 else if(/^\/documents\/[^/]+$/.test(path))body=docs.find(d=>d.id===path.split('/')[2]);
 else if(path==='/skills/srs/execute'){works.push(data);body={id:'new-task',status:'pending'};}
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body??[])});
});
async function send(text){await page.getByPlaceholder('输入您的问题').fill(text);const done=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.getByRole('button',{name:'发送消息',exact:true}).click();await done;await page.getByRole('button',{name:'停止',exact:true}).waitFor({state:'hidden'});}
try{
 await page.goto(url+'/#page=knowledge',{waitUntil:'domcontentloaded'});
 const pending=page.getByRole('row').filter({hasText:'解析中的文档'});assert.ok(await pending.getByRole('checkbox').isDisabled());
 assert.equal(await page.getByRole('button',{name:'提交审核',exact:true}).count(),2);
 await page.locator('.file-name').first().click();
 const detail=page.getByRole('dialog',{name:docs[0].versions[0].filename,exact:true});await detail.getByRole('button',{name:'提交审核',exact:true}).click();
 const single=page.getByRole('dialog',{name:'提交审核',exact:true});await single.getByRole('button',{name:'取消',exact:true}).click();await detail.getByRole('button',{name:'返回',exact:true}).click();assert.equal(batches.length,0);
 await page.getByRole('checkbox',{name:'全选可提交审核文件'}).check();
 await page.getByRole('button',{name:'批量提交审核',exact:true}).click();
 const submit=page.getByRole('dialog',{name:'批量提交审核',exact:true});
 await submit.getByRole('checkbox').check();await submit.getByRole('textbox',{name:'提交说明',exact:true}).fill('批量纳入正式知识');
 await page.screenshot({path:'test-results/knowledge-batch-review.png'});
 await submit.getByRole('button',{name:'确认提交审核',exact:true}).click();
 await page.getByText(/批量提交未完成，所有文件均未提交/).waitFor();assert.equal(docs[0].versions[0].status,'draft');assert.equal(docs[1].versions[0].status,'draft');
 await submit.getByRole('button',{name:'确认提交审核',exact:true}).click();await submit.waitFor({state:'hidden'});
 assert.deepEqual(batches[1].version_ids,['v-a','v-b']);assert.deepEqual(batches[1].expected_revisions,{'v-a':1,'v-b':1});
 assert.equal(await page.getByRole('button',{name:'提交审核',exact:true}).count(),0);
 // Keep the remaining tests independent of fixture publication state.
 for(const doc of docs.slice(0,2)){doc.versions[0].status='draft';doc.versions[0].review_status='not_submitted';}
 await page.goto(url+'/#page=chat&id=conv',{waitUntil:'domcontentloaded'});
 await page.getByPlaceholder('输入您的问题').waitFor();
 const legacy=page.locator('.message.assistant').filter({hasText:'历史回答正文。'});
 await legacy.getByText('历史回答正文。〔来源1〕',{exact:true}).waitFor();
 assert.equal(await legacy.getByText('资料记载与规则依据',{exact:true}).count(),0);
 assert.equal(await legacy.getByText(/原文：旧版第一行/).isVisible(),false);
 await legacy.getByText('查看依据（1 条引用）',{exact:true}).click();
 await legacy.getByText(/旧版第二行/).waitFor();
 await legacy.getByText('查看依据（1 条引用）',{exact:true}).click();
 assert.equal(await page.getByRole('combobox',{name:/问答模式|技能调用模式/}).count(),0);
 await page.getByRole('button',{name:'附加需求文件',exact:true}).click();
 const attach=page.getByRole('dialog',{name:'选择需求附件',exact:true});
 await attach.getByRole('checkbox').first().check();
 await attach.getByRole('button',{name:'完成选择'}).click();
 await send('评级为空时的处理规则');
 assert.deepEqual(chats[0],{content:'评级为空时的处理规则',version_ids:['v-a'],regenerate:false});
 const reply=page.locator('.message.assistant').filter({hasText:'评级规则说明。'});
 await reply.getByText('评级规则说明。〔来源1〕',{exact:true}).waitFor();
 const used=reply.getByText('查看依据（1 条引用）',{exact:true});
 assert.equal(await reply.getByText('检索说明',{exact:true}).isVisible(),false);
 assert.equal(await reply.evaluate(el=>Boolean(el.querySelector('.markdown').compareDocumentPosition(el.querySelector('details'))&Node.DOCUMENT_POSITION_FOLLOWING)),true);
 await used.click();
 await reply.getByText('评级为空时阻断提交。',{exact:true}).first().waitFor();
 await reply.getByText('检索说明',{exact:true}).waitFor();
 await used.click();
 assert.equal(await reply.getByText('检索说明',{exact:true}).isVisible(),false);
 assert.equal(works.length,0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({userSingleAndBatchSubmit:true,pendingDisabled:true,failedBatchNoPartialSubmit:true,selectedFileCitations:true,plainQuestions:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
