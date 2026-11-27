// Browser fixture with no writes to the workbench.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';

const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const url=process.env.WORKBENCH_SMOKE_URL||'http://localhost:3000';
const user={id:'admin',username:'fixture',display_name:'管理员测试',role:'super_admin'};
const version={id:'version',document_id:'doc',creator_id:user.id,label:'V1.0',filename:'已发布软需.md',
 content:'已发布的软需正文',status:'published',parse_status:'ready',review_status:'approved',publish_status:'published',
 index_status:'ready',revision:1,created_at:'2026-11-26T03:00:00',blocks:[],warnings:[],provenance:{}};
const doc={id:'doc',title:'已发布软需',owner_id:user.id,base_id:'base',kind:'specification',
 current_version_id:version.id,versions:[version]};
const errors=[];
const page=await browser.newPage({locale:'zh-CN',viewport:{width:1440,height:1000}});
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const path=new URL(route.request().url()).pathname.slice(4);
 const responses={'/auth/me':user,'/knowledge-bases':[{id:'base',name:'测试知识库',enabled:true}],
  '/documents':[doc],'/documents/doc':doc,'/documents/doc/versions':[version],'/documents/doc/versions/version':version};
 await route.fulfill({contentType:'application/json',body:JSON.stringify(responses[path]??[])});
});

try{
 await page.goto(url+'/#page=knowledge',{waitUntil:'domcontentloaded'});
 await page.locator('.file-name').filter({hasText:doc.title}).click();
 const panel=page.getByRole('dialog',{name:version.filename,exact:true});
 await panel.getByText(version.content,{exact:true}).waitFor();
 assert.equal(await panel.getByRole('button',{name:/废止|归档/}).count(),0);
 assert.ok(await panel.getByRole('button',{name:'创建修订 / 恢复',exact:true}).isVisible());
 assert.ok(await panel.getByRole('link',{name:'原始文件',exact:true}).isVisible());
 await panel.getByRole('button',{name:'版本历史',exact:true}).click();
 await panel.locator('.version-row').getByText('已发布',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 console.log('Published version toolbar and version history verified for administrators.');
}finally{
 await browser.close();
}
