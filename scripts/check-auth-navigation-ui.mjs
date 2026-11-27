// Auth lifecycle fixtures; no real logins, account changes or business API writes.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const accounts={alice:{id:'auth-a',username:'alice',display_name:'测试甲',role:'requirement_member'},bravo:{id:'auth-b',username:'bravo',display_name:'测试乙',role:'requirement_member'}};
let current=null;let rejectLogout=false;let rejectPassword=false;let loads=0;const errors=[];const requests=[];
const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));page.on('load',()=>loads++);
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname.slice(4);let data;try{data=request.postDataJSON();}catch{}requests.push({path,method:request.method()});let response=[];let status=200;
 if(path==='/auth/csrf')response={csrf_token:'fixture'};
 else if(path==='/auth/me'){if(current)response=current;else{status=401;response={detail:'请先登录'};}}
 else if(path==='/auth/login'){if(data.password==='fixture123'&&accounts[data.username]){current=accounts[data.username];response=current;}else{status=401;response={detail:'用户名或密码错误'};}}
 else if(path==='/auth/logout'){if(rejectLogout){status=503;response={detail:'退出失败，请重试'};}else{current=null;response={ok:true};}}
 else if(path==='/auth/password'){if(rejectPassword){status=403;response={detail:'原密码错误'};}else{current=null;response={ok:true};}}
 else if(path==='/dashboard')response={counts:{业务需求:0},charts:{},recent:{documents:[],conversations:[],reviews:[]}};
 else if(path==='/skills')response=[{id:'skill-'+current?.id,name:current?.display_name+'的技能',command:'/test',description:'fixture',owner_id:current?.id,enabled:true,public:false,current_version_id:'sv',config:{workflow:'qa'}}];
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(response)});
});
async function login(name){await page.getByLabel('用户名',{exact:true}).fill(name);await page.getByLabel('密码',{exact:true}).fill('fixture123');const previous=loads;await page.getByRole('button',{name:'登录工作台',exact:false}).click();await page.getByRole('heading',{name:'欢迎回来，'+accounts[name].display_name,exact:true}).waitFor();assert.ok(loads>previous);assert.equal(new URL(page.url()).hash,'#page=dashboard');}
async function profile(){await page.locator('.user-profile').click();await page.getByRole('dialog',{name:'个人设置',exact:true}).waitFor();}
try{
 await page.goto('http://localhost:3000/#page=skills&id=previous');await page.getByRole('heading',{name:'欢迎回来',exact:true}).waitFor();
 const failedLoads=loads;await page.getByLabel('用户名',{exact:true}).fill('alice');await page.getByLabel('密码',{exact:true}).fill('wrong123');await page.getByRole('button',{name:'登录工作台',exact:false}).click();await page.getByText('用户名或密码错误',{exact:true}).waitFor();assert.equal(loads,failedLoads);
 await login('alice');
 await page.getByRole('button',{name:'技能库',exact:true}).click();await page.getByRole('heading',{name:'测试甲的技能',exact:true}).waitFor();await profile();
 rejectLogout=true;const logoutFailureLoads=loads;await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('alert').getByText('退出失败，请重试',{exact:true}).waitFor();assert.equal(loads,logoutFailureLoads);assert.ok(page.url().includes('page=skills'));
 rejectLogout=false;await profile();const logoutLoads=loads;await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('heading',{name:'欢迎回来',exact:true}).waitFor();assert.ok(loads>logoutLoads);assert.equal(new URL(page.url()).hash,'#page=dashboard');assert.equal(await page.locator('.sidebar').count(),0);
 await login('alice');await page.getByRole('button',{name:'技能库',exact:true}).click();await profile();await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('heading',{name:'欢迎回来',exact:true}).waitFor();
 await login('bravo');await page.getByRole('button',{name:'技能库',exact:true}).click();await page.getByRole('heading',{name:'测试乙的技能',exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'测试甲的技能',exact:true}).count(),0);
 await page.reload();await page.getByRole('heading',{name:'测试乙的技能',exact:true}).waitFor();assert.ok(page.url().includes('page=skills'));
 await profile();await page.getByRole('button',{name:'修改密码',exact:true}).click();const password=page.getByRole('dialog',{name:'修改密码',exact:true});await password.getByLabel('原密码',{exact:true}).fill('fixture123');await password.getByLabel('新密码（至少6位）',{exact:true}).fill('newfixture123');rejectPassword=true;const passwordLoads=loads;await password.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').getByText('原密码错误',{exact:true}).waitFor();assert.equal(loads,passwordLoads);
 rejectPassword=false;await password.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('heading',{name:'欢迎回来',exact:true}).waitFor();assert.ok(loads>passwordLoads);assert.equal(new URL(page.url()).hash,'#page=dashboard');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({freshLoginGoesHome:true,logoutRefreshesLogin:true,sameAccountReloginGoesHome:true,accountSwitchClearsCachedData:true,failedAuthStaysPut:true,existingSessionRefreshKeepsRoute:true,passwordChangeShowsLogin:true,pageErrors:errors,productionWrites:0}));
}finally{await browser.close();}
