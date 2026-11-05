// Real OCR, official search and ONE explicitly opted-in external AI job.
// Synthetic advertising text only; not a model accuracy benchmark.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  if(!process.argv.includes('--allow-paid-ai'))throw new Error('Explicit --allow-paid-ai required; may consume team points.');
  const out=path.resolve(__dirname,'../private/live-comparison-validation');
  fs.mkdirSync(out,{recursive:true});
  const report={startedAt:new Date().toISOString(),mode:'LIVE_STACK_SYNTHETIC_AD',passed:false,
    searchSubmissions:0,comparisonSubmissions:0,semanticAccuracyEvaluated:false,stage:'start',cleanup:false};
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_BROWSER||undefined});
  const context=await browser.newContext({viewport:{width:390,height:900}});
  const page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  // Enforce the submission cap even if a UI regression sends duplicate requests.
  await page.route('**/backend/v2/jobs/**',async route=>{
    const request=route.request();const pathname=new URL(request.url()).pathname;
    if(request.method()==='POST'&&pathname.endsWith('/comparison')){
      report.comparisonSubmissions++;
      if(report.comparisonSubmissions>1)return route.abort();
    }
    if(request.method()==='POST'&&pathname.endsWith('/search')){
      report.searchSubmissions++;
      if(report.searchSubmissions>1)return route.abort();
    }
    return route.continue();
  });
  const headers={Origin:'http://localhost:3000','X-Gyeot-Request':'1'};
  async function jobs(){
    const response=await context.request.get('http://localhost:3000/backend/v2/jobs');
    assert.equal(response.status(),200);return (await response.json()).jobs;
  }
  async function get(id){
    const response=await context.request.get('http://localhost:3000/backend/v2/jobs/'+id);
    assert.equal(response.status(),200);return response.json();
  }
  try{
    await page.goto('http://localhost:3000');
    await page.waitForFunction(()=>document.querySelector('#name')&&!document.querySelector('#name').disabled);
    report.stage='photo';
    const image=await page.evaluate(async()=>{
      await document.fonts.load('48px Pretendard');
      const canvas=document.createElement('canvas');canvas.width=1400;canvas.height=420;
      const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,1400,420);
      ctx.fillStyle='black';ctx.font='48px Pretendard';
      ctx.fillText('합성 시험 광고 - 실제 광고 아님',40,90);
      ctx.fillText('비타민C',40,180);ctx.fillText('이 제품은 모든 질병을 치료합니다.',40,280);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#photo').setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(image,'base64')});
    await page.locator('#photo-input input[type=checkbox]').check();
    await page.getByRole('button',{name:'사진 글자 읽기',exact:true}).click();
    await page.locator('#ocr-text').waitFor({timeout:90000});
    assert((await page.locator('#ocr-text').inputValue()).trim());
    const photo=(await jobs()).find(j=>j.kind==='OCR');assert(photo);
    report.ocrEngine=photo.result.engine;
    const claim='이 제품은 모든 질병을 치료합니다.';
    await page.locator('#ocr-text').fill('합성 시험 광고\n비타민C\n'+claim);
    await page.getByRole('button',{name:'수정한 글자 저장',exact:true}).click();
    await page.getByText('수정본을 저장했어요. OCR 원문은 별도로 유지됩니다.',{exact:true}).waitFor();
    await page.locator('#photo-product').fill('비타민C');await page.locator('#photo-claims').fill(claim);
    await page.getByRole('button',{name:'확인한 내용을 검색칸으로 옮기기',exact:true}).click();
    await page.getByText('확인한 내용을 저장하고 검색칸에 옮겼어요. 아래에서 제품 찾기를 눌러 주세요.',{exact:true}).waitFor();
    report.stage='official-search';
    await page.locator('#search-form summary').click();await page.locator('#service').selectOption('I0030');
    await page.getByRole('button',{name:'제품 찾기 →',exact:true}).click();
    await page.getByRole('button',{name:'같은 제품이에요',exact:true}).first().waitFor({timeout:65000});
    const search=(await jobs()).find(j=>j.kind==='SEARCH');assert(search);
    // Select an available official record for plumbing validation, not identity verification.
    let selected;
    for(let i=0;i<search.result.candidates.length;i++){
      const response=page.waitForResponse(r=>r.url().endsWith('/selection')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'같은 제품이에요',exact:true}).nth(i).click();
      const reply=await response;assert.equal(reply.status(),200);
      selected=(await reply.json()).result.selected;
      if(selected.evidence_availability==='PRESENT'&&selected.quote.length<=8000)break;
    }
    assert(selected?.evidence_availability==='PRESENT'&&selected.quote.length<=8000,'No eligible official quote');
    report.productKey=selected.product_key;report.recordSha256=selected.record_sha256;
    await page.locator('#claims').waitFor();assert.equal(await page.locator('#claims').inputValue(),claim);
    const consent=page.getByRole('checkbox',{name:'문구와 공식 원문을 팀 Gateway 및 모델 제공자에게 보내는 데 동의해요.'});
    assert.equal(await consent.isChecked(),false);
    report.stage='external-ai';
    await consent.check();
    const submitted=page.waitForResponse(r=>r.url().endsWith('/comparison')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'AI로 비교하기 →',exact:true}).click();
    const accepted=await submitted;assert.equal(accepted.status(),202);
    const comparison=await accepted.json();
    const deadline=Date.now()+90000;
    let completed=await get(comparison.id);
    while(['QUEUED','RUNNING'].includes(completed.status)&&Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,1000));
      completed=await get(comparison.id);
    }
    report.jobStatus=completed.status;report.resultStatus=completed.result?.status;
    report.reason=completed.result?.reason;report.model=completed.result?.model_requested;
    report.latencyMs=completed.result?.latency_ms;report.usage=completed.result?.usage;
    assert.equal(completed.status,'SUCCEEDED');
    assert.equal(completed.result.status,'EXPERIMENTAL_AI_RESULT','Live model result was held; no automatic retry');
    assert.equal(completed.result.semantic_correctness_verified,false);
    for(const item of completed.result.claims){
      assert.equal(item.ad_quote,claim);
      assert.equal(item.evidence_quote,item.relation==='NOT_ASSESSED'?'':selected.quote);
    }
    report.relations=completed.result.claims.map(c=>c.relation);
    report.stage='restore-isolation-delete';
    await page.reload();
    await page.locator('.history').filter({hasText:'문구 비교'}).getByRole('button',{name:'열기',exact:true}).click();
    await page.getByRole('heading',{name:'AI 비교 초안',exact:true}).waitFor();
    assert.equal(await page.locator('#claims').inputValue(),claim);assert.equal(await consent.isChecked(),false);
    const other=await browser.newContext();
    try{
      assert.equal((await other.request.post('http://localhost:3000/backend/v2/session',{data:{},headers})).status(),200);
      assert.equal((await other.request.get('http://localhost:3000/backend/v2/jobs/'+comparison.id)).status(),404);
    }finally{await other.close();}
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(out,'result-mobile.png'),fullPage:true});
    await page.getByRole('button',{name:'이 검색과 관련 결과 삭제',exact:true}).click();
    await page.locator('.selected').waitFor({state:'hidden'});
    for(const id of [search.id,comparison.id])assert.equal((await context.request.get('http://localhost:3000/backend/v2/jobs/'+id)).status(),404);
    assert.deepEqual(errors,[]);assert.equal(report.comparisonSubmissions,1);
    report.passed=true;report.stage='complete';
  }catch(error){
    report.failure=error.message;process.exitCode=1;
  }finally{
    try{
      // Only this newly created browser session's test records; never touch other users.
      const remaining=await jobs();
      for(const job of remaining){
        const response=await context.request.delete('http://localhost:3000/backend/v2/jobs/'+job.id,{headers});
        assert([204,404].includes(response.status()));
      }
      report.cleanup=(await jobs()).length===0;
    }catch{report.cleanup=false;process.exitCode=1;}
    report.errors=errors;report.finishedAt=new Date().toISOString();
    fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));await browser.close();
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});