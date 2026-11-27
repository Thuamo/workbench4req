// Browser regression of non-JSON auth/proxy failures. No auth POST reaches the DB.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try {
    const page=await browser.newPage({locale:'zh-CN'});
    const errors=[];
    let csrfFails=true;
    let loginPosts=0;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/auth/csrf',async route=>{
        if(csrfFails)return route.fulfill({status:500,contentType:'text/plain',body:'Internal Server Error'});
        return route.continue();
    });
    await page.route('**/api/auth/login',async route=>{
        loginPosts++;
        return route.fulfill({status:500,contentType:'text/plain',body:'Internal Server Error'});
    });
    await page.route('**/api/auth/register',async route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'数据库繁忙，请保存并关闭数据库连接后重试。'})}));
    await page.goto('http://localhost:3000',{waitUntil:'networkidle'});
    await page.getByLabel('用户名',{exact:true}).fill('auth_error_form_only');
    await page.locator('input[name="password"]').fill('Abc123');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'HTTP 500'}).waitFor();
    assert.equal(loginPosts,0);
    csrfFails=false;
    await page.getByRole('alert').getByRole('button',{name:'关闭通知'}).click();
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'HTTP 500'}).waitFor();
    assert.equal(loginPosts,1);
    await page.getByRole('button',{name:'注册账号',exact:true}).click();
    await page.getByLabel('显示名称',{exact:true}).fill('表单错误验证');
    await page.locator('input[name="confirm_password"]').fill('Abc123');
    await page.getByRole('button',{name:'注册并登录',exact:true}).click();
    await page.locator('.auth-card').getByText('数据库繁忙，请保存并关闭数据库连接后重试。',{exact:true}).waitFor();
    assert.equal(errors.length,0,errors.join('; '));
    assert.equal((await page.locator('body').innerText()).includes('Unexpected token'),false);
    console.log(JSON.stringify({csrfPlain500:true,loginPlain500:true,registrationJson503:true,browserErrors:errors,productionAccountsCreated:0}));
} finally {
    await browser.close();
}
