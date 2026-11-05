// UI regression with synthetic HTTP responses. Not a live-model or full-stack E2E.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_BROWSER||undefined});
  const context=await browser.newContext({viewport:{width:390,height:900}});
  const page=await context.newPage();const errors=[];const requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  const quote='합성 기능성 원문';const claim='비교 직전에 수정한 문구';
  const common={status:'SUCCEEDED',error_code:null,created_at:new Date().toISOString(),
    expires_at:new Date(Date.now()+86400000).toISOString(),parent_id:null};
  const parent={...common,id:'search',kind:'SEARCH',search_input:{name:'합성 제품',number:'',manufacturer:'',
    service:'I0030',reviewed_claims:['사진 단계 문구']},result:{status:'CANDIDATES',candidates:[],sources:[],
    selected:{product_key:'I0030:123',record:{PRDLST_NM:'합성 제품'},quote,evidence_availability:'PRESENT',
      source_url:'https://www.foodsafetykorea.go.kr/',retrieved_at:new Date().toISOString()}}};
  const child={...common,id:'compare',kind:'COMPARE',parent_id:'search',comparison_input:{claims:[claim]},
    result:{status:'EXPERIMENTAL_AI_RESULT',reason:'SYNTHETIC',semantic_correctness_verified:false,
      claims:[{ad_quote:claim,evidence_quote:quote,relation:'WITHIN_SCOPE',explanation:'합성 응답입니다.'}]}};
  let jobs=[child,parent];
  await page.route('**/backend/**',async route=>{
    const request=route.request();const endpoint=new URL(request.url()).pathname.replace('/backend','');
    requests.push({method:request.method(),endpoint});
    if(endpoint==='/v2/session')return route.fulfill({json:{ready:true}});
    if(endpoint==='/v2/jobs')return route.fulfill({json:{jobs}});
    if(request.method()==='DELETE'){
      jobs=[];return route.fulfill({status:204});
    }
    const job=jobs.find(j=>endpoint==='/v2/jobs/'+j.id);
    if(job)return route.fulfill({json:job});
    return route.fulfill({status:500,json:{detail:'Unexpected test request'}});
  });
  try{
    await page.goto('http://localhost:3000');
    await page.getByRole('button',{name:'열기',exact:true}).first().click();
    await page.locator('#claims').waitFor();
    assert.equal(await page.locator('#claims').inputValue(),claim);
    await page.getByRole('heading',{name:'AI 비교 초안',exact:true}).waitFor();
    const consent=page.getByRole('checkbox',{name:'문구와 공식 원문을 팀 Gateway 및 모델 제공자에게 보내는 데 동의해요.'});
    assert.equal(await consent.isChecked(),false);
    await consent.check();await page.reload();
    await page.getByRole('button',{name:'열기',exact:true}).first().click();
    await page.locator('#claims').waitFor();
    assert.equal(await page.locator('#claims').inputValue(),claim);
    assert.equal(await consent.isChecked(),false);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'이 검색과 관련 결과 삭제',exact:true}).click();
    await page.locator('#claims').waitFor({state:'hidden'});
    assert.deepEqual(errors,[]);
    assert.equal(requests.filter(r=>r.method==='POST'&&r.endpoint.endsWith('/comparison')).length,0);
    const report={mode:'SYNTHETIC_HTTP_UI_ONLY',editedClaimRestored:true,consentReset:true,
      relatedResultRemoved:true,mobileOverflow:false,externalAIRequests:0,errors};
    const out=path.resolve(__dirname,'../private/comparison-validation');fs.mkdirSync(out,{recursive:true});
    fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});