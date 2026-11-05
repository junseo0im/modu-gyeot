// Live official product search only. Never invokes the AI comparison endpoint.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const out=path.resolve(__dirname,'../private/browser-check');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_BROWSER||undefined});
  const context=await browser.newContext({viewport:{width:390,height:900}});
  const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto('http://localhost:3000');
    await page.locator('#name').waitFor();
    await page.waitForFunction(()=>!document.querySelector('#name').disabled);
    await page.getByRole('button',{name:'글자 더 크게',exact:true}).click();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('#name').fill('알부민967');
    await page.locator('summary').first().click();
    await page.locator('#service').selectOption('I1250');
    await page.getByRole('button',{name:'제품 찾기 →',exact:true}).click();
    await page.getByRole('button',{name:'같은 제품이에요',exact:true}).first().waitFor({timeout:65000});
    await page.getByRole('button',{name:'같은 제품이에요',exact:true}).first().click();
    await page.locator('.selected').waitFor();
    assert((await page.locator('.selected').innerText()).includes('기능성 원문이 없어요'));
    const cookies=await context.cookies();
    assert(cookies.some(c=>c.name==='gyeot_session'&&c.httpOnly&&c.sameSite==='Strict'));
    const jobs=await page.evaluate(async()=> (await fetch('/backend/v2/jobs')).json());
    const current=jobs.jobs.find(j=>j.kind==='SEARCH');assert(current);
    const other=await browser.newContext();
    await other.request.post('http://localhost:3000/backend/v2/session',{data:{},headers:{Origin:'http://localhost:3000','X-Gyeot-Request':'1'}});
    assert.equal((await other.request.get('http://localhost:3000/backend/v2/jobs/'+current.id)).status(),404);
    await other.close();
    await page.reload();
    await page.getByRole('button',{name:'열기',exact:true}).first().waitFor();
    assert.equal(await page.getByRole('button',{name:'기본 글자 크기',exact:true}).getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'열기',exact:true}).first().click();
    await page.locator('.selected').waitFor();
    await page.screenshot({path:path.join(out,'restored-mobile.png'),fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'이 검색과 관련 결과 삭제',exact:true}).click();
    await page.locator('.selected').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(async id=>(await fetch('/backend/v2/jobs/'+id)).status,current.id),404);
    await page.setViewportSize({width:1280,height:900});
    await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const report={liveFoodRequests:1,aiRequests:0,sessionIsolation:'passed',reloadRestore:'passed',delete:'passed',mobileOverflow:false,errors};
    fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});