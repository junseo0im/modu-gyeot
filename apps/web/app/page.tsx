'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, Job, SearchResult, ComparisonResult, Candidate } from '../lib/api';
import PhotoInput from './PhotoInput';

const pending=(job:Job|null)=>!!job && ['QUEUED','RUNNING'].includes(job.status);
const labels:Record<string,string>={WITHIN_SCOPE:'공식 원문 범위 안으로 추정',OVERSTATED:'표현 범위 초과 가능성',OTHER_DIFFERENCE:'다른 의미·조건 차이',NOT_ASSESSED:'비교 보류'};

export default function Home(){
  const [ready,setReady]=useState(false);
  const [large,setLarge]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('연결을 확인하고 있어요.');
  const [name,setName]=useState('');
  const [number,setNumber]=useState('');
  const [manufacturer,setManufacturer]=useState('');
  const [service,setService]=useState('both');
  const [claims,setClaims]=useState('');
  const [consent,setConsent]=useState(false);
  const [search,setSearch]=useState<Job|null>(null);
  const [comparison,setComparison]=useState<Job|null>(null);
  const [history,setHistory]=useState<Job[]>([]);
  const [photo,setPhoto]=useState<Job|null>(null);
  const [deletedPhoto,setDeletedPhoto]=useState<string|null>(null);
  const photoDraft=useRef<{name:string;claims:string[]}|null>(null);
  const operation=useRef(false);
  const epoch=useRef(0);
  const searchRequest=useRef<{signature:string;key:string}|null>(null);
  const compareRequest=useRef<{signature:string;key:string}|null>(null);
  const resultRef=useRef<HTMLElement>(null);

  async function connect(){
    try{
      await api('/v2/session','POST');
      const list=await api<{jobs:Job[]}>('/v2/jobs');
      setHistory(list.jobs);setReady(true);setMessage('');
      setLarge(localStorage.getItem('gyeot-large-text')==='true');
    }catch{setReady(false);setMessage('연결하지 못했어요. 서버가 켜져 있는지 확인한 뒤 다시 연결해 주세요.');}
  }
  useEffect(()=>{void connect();},[]);

  useEffect(()=>{
    if(!pending(search)&&!pending(comparison)) return;
    let active=true;
    let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      const generation=epoch.current;
      try{
        const jobs=[search,comparison].filter((j):j is Job=>!!j&&pending(j));
        for(const job of jobs){
          const updated=await api<Job>('/v2/jobs/'+job.id);
          if(!active||generation!==epoch.current)return;
          if(job.kind==='SEARCH')setSearch(updated);else setComparison(updated);
          if(!pending(updated)){
            setMessage(updated.status==='FAILED'?'처리를 마치지 못했어요. 자동 재시도하지 않았습니다. 다시 요청할 수 있어요.':updated.status==='CANCELLED'?'작업을 취소했어요.':'처리를 마쳤어요.');
            setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);
            resultRef.current?.focus();
          }
        }
      }catch{if(active)setMessage('진행 상태를 확인하지 못했어요. 작업은 저장돼 있습니다. 연결되면 다시 확인합니다.');}
      if(active)timer=setTimeout(poll,1500);
    }
    timer=setTimeout(poll,800);
    return()=>{active=false;clearTimeout(timer);};
  },[search,comparison]);

  const sr=search?.kind==='SEARCH'&&search.result?search.result as SearchResult:null;
  const selected=sr?.selected;
  const cr=comparison?.result?comparison.result as ComparisonResult:null;
  const working=pending(search)||pending(comparison);

  async function act(fn:()=>Promise<void>){
    if(operation.current)return;
    operation.current=true;setBusy(true);
    try{await fn();}catch(e){setMessage(e instanceof Error?e.message:'다시 시도해 주세요.');}
    finally{operation.current=false;setBusy(false);}
  }
  async function submitSearch(e:FormEvent){
    e.preventDefault();
    const input={name:name.trim(),number:number.trim(),manufacturer:manufacturer.trim(),service,
      reviewed_claims:photoDraft.current?.name===name.trim()?photoDraft.current.claims:[]};
    if(!input.name&&!input.number){setMessage('제품명 또는 품목번호를 입력해 주세요.');return;}
    await act(async()=>{
      const signature=JSON.stringify(input);
      if(searchRequest.current?.signature!==signature)searchRequest.current={signature,key:crypto.randomUUID()};
      const job=await api<Job>('/v2/jobs/search','POST',input,searchRequest.current.key);
      epoch.current++;setSearch(job);setComparison(null);setClaims(input.reviewed_claims.join('\n'));setConsent(false);
      searchRequest.current=null;compareRequest.current=null;
      setMessage('접수했어요. 이 창을 새로고침해도 진행 기록을 다시 열 수 있어요.');
      setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);
    });
  }
  async function choose(c:Candidate){
    await act(async()=>{
      if(!search)return;
      const job=await api<Job>(`/v2/jobs/${search.id}/selection`,'POST',{product_key:c.key});
      epoch.current++;setSearch(job);setComparison(null);setClaims(job.search_input?.reviewed_claims?.join('\n')??'');setConsent(false);compareRequest.current=null;
      setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);setMessage('선택한 기록이에요. 포장의 제조업체·번호와 다시 확인해 주세요.');
    });
  }
  async function submitComparison(e:FormEvent){
    e.preventDefault();if(!search||!selected)return;
    const lines=claims.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(!consent||!lines.length||lines.length>3||lines.some(s=>s.length>300)){setMessage('300자 이내 문구를 최대 3개 입력하고 외부 전송을 확인해 주세요.');return;}
    await act(async()=>{
      const input={product_key:selected.product_key,claims:lines,consent_external:true};
      const signature=search.id+JSON.stringify(input);
      if(compareRequest.current?.signature!==signature)compareRequest.current={signature,key:crypto.randomUUID()};
      setComparison(await api<Job>(`/v2/jobs/${search.id}/comparison`,'POST',input,compareRequest.current.key));
      compareRequest.current=null;setMessage('비교를 접수했어요. 문구와 공식 원문을 외부 AI로 보냅니다.');
      setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);
    });
  }
  async function restore(job:Job){
    await act(async()=>{
      if(job.kind==='OCR'){setPhoto(await api<Job>('/v2/jobs/'+job.id));setMessage('사진 기록을 열었어요.');return;}
      const parent=await api<Job>('/v2/jobs/'+(job.kind==='COMPARE'?job.parent_id:job.id));
      const child=job.kind==='COMPARE'?await api<Job>('/v2/jobs/'+job.id):null;
      epoch.current++;setConsent(false);compareRequest.current=null;searchRequest.current=null;
      photoDraft.current=null;
      setSearch(parent);setComparison(child);
      setName(parent.search_input?.name??'');setNumber(parent.search_input?.number??'');
      setManufacturer(parent.search_input?.manufacturer??'');setService(parent.search_input?.service??'both');
      setClaims((child?.comparison_input?.claims??parent.search_input?.reviewed_claims??[]).join('\n'));
      setMessage('저장된 진행 기록을 열었어요.');
    });
  }
  async function remove(job:Job){
    await act(async()=>{
      epoch.current++;await api('/v2/jobs/'+job.id,'DELETE');
      if(job.kind==='OCR'){setDeletedPhoto(job.id);if(photo?.id===job.id)setPhoto(null);}
      if(search?.id===job.id){setSearch(null);setComparison(null);setClaims('');setConsent(false);photoDraft.current=null;}
      else if(comparison?.id===job.id)setComparison(null);
      setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);
      setMessage('서버 기록을 삭제했어요. 이미 전송된 외부 AI 자료의 삭제를 보장하지는 않습니다.');
    });
  }
  async function cancel(job:Job){await act(async()=>{
    const updated=await api<Job>(`/v2/jobs/${job.id}/cancel`,'POST');
    epoch.current++;if(job.kind==='SEARCH')setSearch(updated);else setComparison(updated);
    setMessage('취소했어요. 이미 시작된 외부 호출은 끝날 수 있지만 결과를 다시 저장하지 않아요.');
    setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);
  });}

  return <main className={large?'large':''}>
    <a className="skip" href="#search-form">제품 찾기로 바로가기</a>
    <header><a href="/" className="brand">곁 <small>GYEOT</small></a><span className="badge">새 서비스 기반 · 개발 중</span></header>
    <div className="hero"><h1>궁금한 제품,<br/><em>함께 확인해요.</em></h1><p>공식 기록부터 차근차근 살펴보세요.</p>
      <button className="secondary" aria-pressed={large} onClick={()=>{setLarge(!large);localStorage.setItem('gyeot-large-text',String(!large));}}>{large?'기본 글자 크기':'글자 더 크게'}</button></div>
    <aside className="notice">실험용 서비스입니다. 사진 인식과 AI 해석이 틀릴 수 있어요. 결과는 구매·섭취 안전을 보장하지 않아요.</aside>
    <p role="status" aria-live="polite">{message}</p>
    {!ready&&<button onClick={()=>void connect()}>다시 연결하기</button>}
    <PhotoInput restored={photo} deletedId={deletedPhoto} disabled={!ready||busy||working} onRefresh={async()=>{setHistory((await api<{jobs:Job[]}>('/v2/jobs')).jobs);}} onApply={(product,text)=>{epoch.current++;setName(product);setNumber('');setManufacturer('');setService('both');photoDraft.current={name:product,claims:text?text.split('\n'):[]};searchRequest.current=null;compareRequest.current=null;setClaims(text);setSearch(null);setComparison(null);setConsent(false);document.getElementById('name')?.focus();}}/>
    <section><h2>1. 제품을 찾아볼까요?</h2><form id="search-form" onSubmit={submitSearch}>
      <fieldset disabled={!ready||busy||working}><label htmlFor="name">제품명</label><input id="name" value={name} onChange={e=>{setName(e.target.value);photoDraft.current=null;}} maxLength={200} placeholder="예: 알부민967"/>
      <details><summary>번호·제조업체로 더 정확히 찾기</summary>
        <label htmlFor="number">품목제조번호</label><input id="number" value={number} onChange={e=>setNumber(e.target.value)} maxLength={40}/>
        <label htmlFor="manufacturer">제조업체 (판매자와 다를 수 있어요)</label><input id="manufacturer" value={manufacturer} onChange={e=>setManufacturer(e.target.value)} maxLength={200}/>
        <label htmlFor="service">검색 범위</label><select id="service" value={service} onChange={e=>setService(e.target.value)}><option value="both">둘 다 찾기</option><option value="I0030">건강기능식품</option><option value="I1250">일반식품</option></select>
      </details><p className="hint">제품 정보만 식품안전나라에 보내요. 개인정보는 넣지 마세요.</p><button className="wide" type="submit">제품 찾기 →</button></fieldset>
    </form></section>
    {search&&<section tabIndex={-1} ref={resultRef}><h2>2. 제품과 기록 확인</h2>
      {pending(search)&&<><p>공식 자료를 찾고 있어요. 잠시 기다려 주세요.</p><button className="secondary" disabled={busy} onClick={()=>void cancel(search)}>검색 취소</button></>}
      {search.status==='FAILED'&&<p>검색 처리가 중단됐어요. 다시 검색해 주세요. 근거가 없다는 뜻은 아니에요.</p>}
      {search.status==='CANCELLED'&&<p>취소한 검색이에요.</p>}
      {sr&&<><p>{sr.status==='NOT_FOUND'?'찾지 못했어요. 제품명·번호를 고쳐 보세요. 미등록이나 안전이라는 뜻은 아니에요.':sr.status==='UNAVAILABLE'?'공식 자료를 불러오지 못했어요. 나중에 다시 찾아보세요.':sr.status==='PARTIAL'?'일부 자료를 불러오지 못했어요. 아래 결과가 전부는 아니에요.':'이름·제조업체·번호를 포장과 비교해 주세요.'}</p>
        <details><summary>검색 범위·제한</summary>{sr.sources.map(s=><p key={s.service}>{s.service}: {s.status} · 보고 총량 {s.reported_total_count??'미제공'}{s.truncated?' · 일부 결과만 표시':''}</p>)}<p>출처별 최대 10개만 표시하며 수입·직구 등 모든 제품을 포괄하지 않습니다.</p></details>
        {sr.candidates.map(c=><article key={c.key}><h3>{c.name}</h3><p>만든 곳: {c.manufacturer}</p><p>품목번호: {c.number}</p><button disabled={busy||working} onClick={()=>void choose(c)}>같은 제품이에요</button></article>)}
      </>}
      {selected&&<article className="selected"><h3>{selected.record.PRDLST_NM}</h3><p>선택한 제품의 공식 기능성 원문</p><blockquote>{selected.quote||'비교할 기능성 원문이 없어요. 효과 없음·안전·위법 판정은 아닙니다.'}</blockquote><p className="notice">제품 선택은 사용자 확인입니다. 동일 제품·근거 적용성의 독립 검증 완료가 아닙니다.</p><details><summary>출처·조회 시각</summary><p>{selected.retrieved_at}</p><p>원천 수정일 {selected.record.LAST_UPDT_DTM||'미제공'} · 과거 광고 당시의 기록을 입증하지 않습니다.</p><a href={selected.source_url} target="_blank" rel="noreferrer">공식 출처 열기</a></details></article>}
      <button className="secondary" disabled={busy} onClick={()=>void remove(search)}>이 검색과 관련 결과 삭제</button>
    </section>}
    {selected?.evidence_availability==='PRESENT'&&<section><h2>3. 광고 문구와 비교하기</h2><p>선택 기능이에요. AI가 틀릴 수 있어요.</p><form onSubmit={submitComparison}><fieldset disabled={busy||working}>
      <label htmlFor="claims">광고 문구 · 한 줄에 하나씩 최대 3개</label><textarea id="claims" value={claims} onChange={e=>{setClaims(e.target.value);setComparison(null);}} maxLength={902} rows={4}/>
      <p className="notice">외부 AI의 보관·학습·삭제 정책은 미확인입니다. 개인정보 없는 시험 문구 또는 외부 처리 권한이 있는 문구만 입력하세요.</p>
      <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} required/>문구와 공식 원문을 팀 Gateway 및 모델 제공자에게 보내는 데 동의해요.</label>
      <p className="hint">팀 포인트가 사용됩니다. 동의가 자료 이용 권한을 대신하지는 않습니다.</p><button type="submit" className="wide">AI로 비교하기 →</button></fieldset></form>
      {pending(comparison)&&comparison&&<><p>비교 중이에요. 새로고침해도 기록에서 다시 열 수 있어요.</p><button disabled={busy} className="secondary" onClick={()=>void cancel(comparison)}>비교 취소</button></>}
      {comparison?.status==='FAILED'&&<p>비교가 중단됐어요. 자동 재호출하지 않았습니다.</p>}
      {cr&&<div><h3>{cr.status==='EXPERIMENTAL_AI_RESULT'?'AI 비교 초안':'비교 보류'}</h3>{cr.claims.map((c,i)=><article key={i}><h3>{labels[c.relation??'NOT_ASSESSED']}</h3><blockquote>{c.ad_quote}</blockquote>{c.evidence_quote&&<><p>비교한 공식 원문</p><blockquote>{c.evidence_quote}</blockquote></>}<details><summary>이 결과의 뜻</summary><p>{c.explanation}</p></details></article>)}<p className="notice">인용·출력 형식만 검사했습니다. AI 의미 해석의 정확성은 보장되지 않습니다.</p></div>}
    </section>}
    {history.length>0&&<section><h2>이 브라우저의 진행 기록</h2><p>글자·결과는 24시간, 사진은 1시간 동안 다시 열 수 있어요.</p>{history.map(job=><div className="history" key={job.id}><span>{job.kind==='OCR'?'사진 읽기':job.kind==='SEARCH'?'제품 검색':'문구 비교'} · {({QUEUED:'대기',RUNNING:'처리 중',SUCCEEDED:'처리 완료',FAILED:'중단',CANCELLED:'취소'})[job.status]}<small>{new Date(job.created_at).toLocaleString('ko-KR')}</small></span><button className="secondary" disabled={busy||working} onClick={()=>void restore(job)}>열기</button><button className="secondary" disabled={busy} onClick={()=>void remove(job)}>삭제</button></div>)}</section>}
    <footer><details><summary>자료 보관과 서비스 한계</summary><p>검색 조건·광고 문구·공식 기록·결과는 로컬 PostgreSQL에 최대 24시간 보관합니다. 작업자는 만료 기록을 정리하며, 꺼져 있으면 다음 시작 때 정리합니다. 조회는 만료 즉시 차단됩니다. 세션 쿠키는 HttpOnly이며 7일 만료됩니다. 삭제는 DB의 논리 삭제로, 백업·디스크 및 외부 AI 보관분의 즉시 물리 삭제를 보장하지 않습니다. 공개 운영 전 보관·동의·백업 정책을 추가 검증해야 합니다.</p></details></footer>
  </main>;
}