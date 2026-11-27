// Fixture-only: never approves or returns real business documents.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
let user={id:'admin',username:'admin',display_name:'审核测试',role:'super_admin'};const now='2026-11-04T08:00:00';
function row(id,assigned=true,extra=false){
 const version={id:'v-'+id,document_id:id,creator_id:'author',filename:id+'.md',label:'V1.0',content:'# 审核正文\n规则需要保留原始记录。',warnings:[],blocks:[],status:'pending_review',parse_status:'ready',review_status:'pending',publish_status:'not_published',index_status:'not_built',revision:1,created_at:now,provenance:{}};
 const tasks=[{id:'task-'+id,reviewer_id:assigned?'admin':'reviewer',reviewer_name:assigned?'审核测试':'其他审核员',decision:'pending',comment:''}];
 if(extra)tasks.push({id:'other-'+id,reviewer_id:'other',reviewer_name:'会签人乙',decision:'pending',comment:''});
 return {id:'r-'+id,version_id:version.id,submitter_id:'author',locked_hash:'a'.repeat(64),status:'pending',note:'请核对规则',version,document:{id,title:'审核文件'+id,base_id:'base',owner_id:'author',kind:'reference',versions:[version]},tasks,created_at:now};
}
function fixtures(){const done=row('d');done.status='approved';done.tasks[0].decision='approved';const self=row('e');self.submitter_id='admin';return [row('a'),row('b',true,true),row('c',false),done,self];}
let rows=fixtures(),reject=true;const batches=[];
const page=await browser.newPage({viewport:{width:1500,height:1050},locale:'zh-CN'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);let body=[];
 if(path==='/auth/me')body=user;
 else if(path==='/auth/csrf')body={csrf_token:'fixture'};
 else if(path==='/dashboard')body={counts:{},charts:{},recent:{documents:[],reviews:[],conversations:[]}};
 else if(path==='/reviews')body=rows;
 else if(path==='/review-tasks/batch-decision'){
  const data=request.postDataJSON();batches.push(data);
  assert.deepEqual(data.items.map(x=>x.task_id),['task-a','task-b']);assert.ok(data.items.every(x=>x.locked_hash==='a'.repeat(64)));
  if(reject){reject=false;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{message:'本次批量审核未应用，所有已选任务均未变更',reason:'任务状态已变化，请重新核对',filename:'b.md'}})});return;}
  const results=[];
  for(const r of rows.filter(r=>['r-a','r-b'].includes(r.id))){
   r.tasks[0].decision=data.decision;r.tasks[0].comment=data.comment;
   if(data.decision==='returned'){r.status='returned';r.tasks.filter(t=>t.decision==='pending').forEach(t=>t.decision='cancelled');}
   else{r.status=r.tasks.every(t=>t.decision==='approved')?'approved':'in_review';if(r.status==='approved')r.version.publish_status='queued';}
   results.push({request_id:r.id,status:r.status});
  }body={decided:2,results};
 }else if(/^\/documents\/[^/]+\/versions\//.test(path)){body=rows.find(r=>r.document.id===path.split('/')[2])?.version;}
 else if(/^\/documents\/[^/]+\/versions$/.test(path))body=rows.find(r=>r.document.id===path.split('/')[2])?.document.versions;
 else if(/^\/documents\/[^/]+$/.test(path))body=rows.find(r=>r.document.id===path.split('/')[2])?.document;
 await route.fulfill({contentType:'application/json',body:JSON.stringify(body??[])});
});
try{
 await page.goto('http://localhost:3000/#page=reviews',{waitUntil:'domcontentloaded'});
 for(const id of ['a','b'])assert.ok(await page.getByRole('row').filter({hasText:'审核文件'+id}).getByRole('checkbox').isEnabled());
 for(const id of ['c','d','e'])assert.ok(await page.getByRole('row').filter({hasText:'审核文件'+id}).getByRole('checkbox').isDisabled());
 await page.getByRole('checkbox',{name:'全选可审核文件（最多50份）',exact:true}).check();await page.getByRole('button',{name:'批量通过',exact:true}).click();
 let modal=page.getByRole('dialog',{name:'批量审核通过',exact:true});await modal.getByRole('button',{name:'查看内容',exact:true}).first().click();
 const source=page.getByRole('dialog',{name:'a.md',exact:true});await source.getByText('规则需要保留原始记录。',{exact:true}).waitFor();await source.getByRole('button',{name:'返回',exact:true}).click();await modal.getByRole('button',{name:'取消',exact:true}).click();assert.equal(batches.length,0);
 await page.getByRole('button',{name:'批量退回',exact:true}).click();modal=page.getByRole('dialog',{name:'批量退回审核',exact:true});assert.ok(await modal.getByRole('button',{name:'确认批量退回',exact:true}).isDisabled());
 await modal.getByRole('textbox',{name:'统一退回原因',exact:true}).fill('缺少异常处理规则，请补充');await page.screenshot({path:'test-results/batch-review-confirmation.png'});await modal.getByRole('button',{name:'确认批量退回',exact:true}).click();
 await page.getByText(/本次批量审核未应用/).waitFor();assert.equal(rows[0].status,'pending');assert.equal(await modal.getByRole('textbox',{name:'统一退回原因',exact:true}).inputValue(),'缺少异常处理规则，请补充');
 await modal.getByRole('button',{name:'确认批量退回',exact:true}).click();await modal.waitFor({state:'hidden'});assert.equal(rows[1].tasks[1].decision,'cancelled');assert.equal(rows[0].status,'returned');
 rows=fixtures();await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('checkbox',{name:'全选可审核文件（最多50份）',exact:true}).check();await page.screenshot({path:'test-results/batch-review-list.png'});await page.getByRole('button',{name:'批量通过',exact:true}).click();
 modal=page.getByRole('dialog',{name:'批量审核通过',exact:true});await modal.getByRole('textbox',{name:'统一审核意见',exact:true}).fill('规则已核对');await modal.getByRole('button',{name:'确认批量通过',exact:true}).click();await modal.waitFor({state:'hidden'});
 assert.equal(rows[0].status,'approved');assert.equal(rows[0].version.publish_status,'queued');assert.equal(rows[1].status,'in_review');assert.equal(rows[1].version.publish_status,'not_published');
 user={id:'author',username:'author',display_name:'提交人',role:'requirement_member'};await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('heading',{name:'我的审核申请',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'批量通过',exact:true}).count(),0);assert.equal(await page.getByRole('checkbox').count(),0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({assignedOnly:true,noSelfReview:true,previewAndCancel:true,returnReasonRequired:true,conflictKeepsComment:true,batchReturnCancelsCosigners:true,batchApprovalRetainsCosignatureGate:true,memberCannotDecide:true,pageErrors:errors,productionDecisions:0}));
}finally{await browser.close();}
