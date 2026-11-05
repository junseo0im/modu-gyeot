// Real local OCR on generated text. --search also calls the official food API.
// Never requests an external AI comparison.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
(async()=>{
  const withSearch=process.argv.includes('--search');
  const out=path.resolve(__dirname,'../private/ocr-validation');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_BROWSER||undefined});
  const context=await browser.newContext({viewport:{width:390,height:900}});const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto('http://localhost:3000');await page.waitForFunction(()=>!document.querySelector('#name').disabled);
    const image=await page.evaluate(async()=>{
      await document.fonts.load('48px Pretendard');
      const c=document.createElement('canvas');c.width=1100;c.height=420;
      const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,c.width,c.height);x.fillStyle='black';x.font='48px Pretendard';
      x.fillText('합성 시험 광고',50,90);x.fillText('알부민967',50,180);x.fillText('관절 건강에 도움을 줄 수 있음',50,280);
      return c.toDataURL('image/png').split(',')[1];
    });
    const buffer=Buffer.from(image,'base64');fs.writeFileSync(path.join(out,'synthetic.png'),buffer);
    await page.locator('#photo').setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer});
    await page.locator('#photo-input input[type=checkbox]').check();
    await page.getByRole('button',{name:'사진 글자 읽기',exact:true}).click();
    await page.locator('#ocr-text').waitFor({timeout:90000});
    const original=await page.locator('#ocr-text').inputValue();
    // TSV word boxes can split Korean syllables; check characters, preserve raw spacing.
    const compact=original.replace(/\s/g,'');
    assert(compact.includes('알부민967'),original);
    assert(compact.includes('관절건강에도움을줄수있음'),original);
    await page.locator('#ocr-text').fill(original+'\n사용자 수정 시험');
    await page.getByRole('button',{name:'수정한 글자 저장',exact:true}).click();
    await page.getByText('수정본을 저장했어요. OCR 원문은 별도로 유지됩니다.',{exact:true}).waitFor();
    const list=await page.evaluate(async()=> (await fetch('/backend/v2/jobs')).json());
    const job=list.jobs.find(j=>j.kind==='OCR');assert(job);
    assert(job.result.corrected_text.includes('사용자 수정 시험'));
    const other=await browser.newContext();
    await other.request.post('http://localhost:3000/backend/v2/session',{data:{},headers:{Origin:'http://localhost:3000','X-Gyeot-Request':'1'}});
    assert.equal((await other.request.get('http://localhost:3000/backend/v2/jobs/'+job.id+'/image')).status(),404);
    await other.close();
    await page.reload();await page.getByRole('button',{name:'열기',exact:true}).first().click();
    await page.locator('#ocr-text').waitFor();assert((await page.locator('#ocr-text').inputValue()).includes('사용자 수정 시험'));
    await page.locator('#search-form summary').click();
    await page.locator('#number').fill('old-number');await page.locator('#manufacturer').fill('old-maker');
    await page.locator('#service').selectOption('I0030');
    await page.locator('#photo-product').fill('알부민967');await page.locator('#photo-claims').fill('합성 시험 문구');
    await page.getByRole('button',{name:'확인한 내용을 검색칸으로 옮기기',exact:true}).click();
    await page.getByText('확인한 내용을 저장하고 검색칸에 옮겼어요. 아래에서 제품 찾기를 눌러 주세요.',{exact:true}).waitFor();
    assert.equal(await page.locator('#name').inputValue(),'알부민967');
    assert.equal(await page.locator('#number').inputValue(),'');assert.equal(await page.locator('#manufacturer').inputValue(),'');
    assert.equal(await page.locator('#service').inputValue(),'both');
    await page.reload();await page.getByRole('button',{name:'열기',exact:true}).first().click();
    await page.locator('#photo-product').waitFor();
    assert.equal(await page.locator('#photo-product').inputValue(),'알부민967');
    assert.equal(await page.locator('#photo-claims').inputValue(),'합성 시험 문구');
    await page.getByRole('button',{name:'확인한 내용을 검색칸으로 옮기기',exact:true}).click();
    await page.getByText('확인한 내용을 저장하고 검색칸에 옮겼어요. 아래에서 제품 찾기를 눌러 주세요.',{exact:true}).waitFor();
    if(withSearch){
      await page.locator('#search-form summary').click();await page.locator('#service').selectOption('I1250');
      await page.getByRole('button',{name:'제품 찾기 →',exact:true}).click();
      await page.getByRole('button',{name:'같은 제품이에요',exact:true}).first().waitFor({timeout:65000});
      await page.getByRole('button',{name:'같은 제품이에요',exact:true}).first().click();
      await page.locator('.selected').waitFor();
      const jobs=await page.evaluate(async()=> (await fetch('/backend/v2/jobs')).json());
      const search=jobs.jobs.find(j=>j.kind==='SEARCH');assert(search);
      assert.deepEqual(search.search_input.reviewed_claims,['합성 시험 문구']);
      await page.reload();await page.getByRole('button',{name:'열기',exact:true}).first().click();
      await page.locator('.selected').waitFor();
      assert.equal(await page.locator('#name').inputValue(),'알부민967');
      assert.equal(await page.locator('#service').inputValue(),'I1250');
      const restored=await page.evaluate(async id=>(await fetch('/backend/v2/jobs/'+id)).json(),search.id);
      assert.deepEqual(restored.search_input.reviewed_claims,['합성 시험 문구']);
      await page.getByRole('button',{name:'이 검색과 관련 결과 삭제',exact:true}).click();
      await page.locator('.selected').waitFor({state:'hidden'});
      assert.equal(await page.evaluate(async id=>(await fetch('/backend/v2/jobs/'+id)).status,search.id),404);
      await page.getByRole('button',{name:'열기',exact:true}).first().click();await page.locator('#ocr-text').waitFor();
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(out,'ocr-mobile.png'),fullPage:true});
    await page.getByRole('button',{name:'사진과 글자 기록 삭제',exact:true}).click();
    await page.locator('#ocr-text').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(async id=>(await fetch('/backend/v2/jobs/'+id+'/image')).status,job.id),404);
    assert.deepEqual(errors,[]);
    const report={input:'SYNTHETIC',ocrText:original,wordCount:job.result.words.length,correctedRestored:true,
      crossSessionDenied:true,deleted:true,reviewedInputRestored:true,staleSearchFiltersCleared:true,
      searchJourney:withSearch?'passed':'not-run',externalAIRequests:0,foodRequests:withSearch?1:0,errors};
    fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});