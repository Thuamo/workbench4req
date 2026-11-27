// Test the local compiled forms with intercepted auth POSTs; no account is created.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/m1775/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try {
    const page=await browser.newPage({locale:'zh-CN'});
    const submitted={register:[],login:[]};
    for(const action of ['register','login']) {
        await page.route('**/api/auth/'+action,async route=>{
            if(route.request().method()!=='POST')return route.continue();
            submitted[action].push(route.request().postDataJSON());
            await route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:action==='register'?'注册表单已通过':'登录表单已通过'})});
        });
    }
    await page.goto('http://localhost:3000',{waitUntil:'networkidle'});
    await page.getByRole('button',{name:'注册账号',exact:true}).click();
    await page.getByLabel('用户名',{exact:true}).fill('form_validation_only');
    await page.getByLabel('显示名称',{exact:true}).fill('表单验证');
    await page.locator('input[name="password"]').fill('Abc12');
    await page.getByLabel('确认密码',{exact:true}).fill('Abc12');
    await page.getByRole('button',{name:'注册并登录',exact:true}).click();
    await page.getByText('密码至少6位',{exact:true}).waitFor();
    assert.equal(submitted.register.length,0);
    await page.locator('input[name="password"]').fill('Abc123');
    await page.getByLabel('确认密码',{exact:true}).fill('Abc123');
    await page.getByRole('button',{name:'注册并登录',exact:true}).click();
    await page.getByText('注册表单已通过',{exact:true}).waitFor();
    assert.equal(submitted.register.length,1);
    assert.equal(submitted.register[0].password.length,6);
    await page.getByRole('button',{name:'立即登录',exact:true}).click();
    await page.locator('input[name="password"]').fill('Abc12');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.getByText('密码至少6位',{exact:true}).waitFor();
    assert.equal(submitted.login.length,0);
    await page.locator('input[name="password"]').fill('Abc123');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.getByText('登录表单已通过',{exact:true}).waitFor();
    assert.equal(submitted.login.length,1);
    assert.equal(submitted.login[0].password.length,6);
    console.log(JSON.stringify({registration:{fiveRejected:true,sixAccepted:true},login:{fiveRejected:true,sixAccepted:true},productionAccountsCreated:0}));
} finally {
    await browser.close();
}
