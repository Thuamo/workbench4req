// Headless test of this newly built local app only. No user browser profile is opened.
import { createRequire } from 'node:module';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const root=path.resolve('.');
const output=path.join(root,'test-results','ui');
await fs.mkdir(output,{recursive:true});
const username='ui_check_'+Date.now();
const password=randomBytes(18).toString('base64url');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},locale:'zh-CN'});
const page=await context.newPage();
const errors=[];
page.on('pageerror',error=>errors.push(error.message));
try {
  await page.goto('http://localhost:3000',{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'欢迎回来'}).waitFor();
  await page.screenshot({path:path.join(output,'01-login.png'),fullPage:true});
  await page.getByRole('button',{name:'注册账号',exact:true}).click();
  await page.getByLabel('用户名',{exact:true}).fill(username);
  await page.getByLabel('显示名称',{exact:true}).fill('本地验收账号');
  await page.getByLabel('密码',{exact:true}).fill(password);
  await page.getByLabel('确认密码',{exact:true}).fill(password);
  await page.getByRole('button',{name:'注册并登录',exact:true}).click();
  await page.getByRole('heading',{name:'欢迎回来，本地验收账号'}).waitFor({timeout:20000});
  await page.screenshot({path:path.join(output,'02-dashboard.png'),fullPage:true});
  const results=[];
  for(const [navigation,heading] of [['需求澄清计划','需求澄清计划'],['需求知识库','需求知识库'],['技能库','技能库'],['需求分析与关联','需求分析与关联']]) {
    await page.locator('nav').getByRole('button',{name:navigation,exact:true}).click();
    await page.getByRole('heading',{name:heading,exact:true}).waitFor();
    await page.waitForLoadState('networkidle');
    await page.screenshot({path:path.join(output,navigation+'.png'),fullPage:true});
    results.push({page:navigation,loaded:true});
  }
  await page.locator('nav').getByRole('button',{name:'新聊天',exact:true}).click();
  await page.getByPlaceholder('描述您的需求，输入 / 调用技能').waitFor();
  await page.getByPlaceholder('描述您的需求，输入 / 调用技能').fill('/');
  await page.getByRole('button',{name:'/软需生成'}).waitFor();
  await page.screenshot({path:path.join(output,'06-chat-slash.png'),fullPage:true});
  await page.getByPlaceholder('描述您的需求，输入 / 调用技能').fill('测试未配置模型的明确错误');
  await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'尚未配置'}).waitFor();
  await page.getByRole('button',{name:'切换主题'}).click();
  await page.screenshot({path:path.join(output,'07-dark-chat.png'),fullPage:true});
  await page.setViewportSize({width:430,height:932});
  await page.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().width<=79);
  await page.screenshot({path:path.join(output,'08-mobile.png'),fullPage:true});
  if(errors.length)throw new Error('Browser errors: '+errors.join('; '));
  await fs.writeFile(path.join(output,'results.json'),JSON.stringify({username,results,slash:true,missingModelError:true,browserErrors:errors},null,2));
  console.log(JSON.stringify({results,slash:true,missingModelError:true,browserErrors:errors,output}));
} finally {
  // Log out through the same-origin API. Account cleanup is an explicit local test operation.
  try {await page.evaluate(async()=>{const token=document.cookie.split('; ').find(c=>c.startsWith('csrf='))?.slice(5);await fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':decodeURIComponent(token||'')}});});}catch{}
  await browser.close();
}
