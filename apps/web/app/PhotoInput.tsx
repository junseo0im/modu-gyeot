'use client';
import {useEffect,useRef,useState} from 'react';
import {api,Job,OCRResult,uploadImage} from '../lib/api';

export default function PhotoInput({restored,deletedId,onRefresh,onApply,disabled}:{restored:Job|null;deletedId:string|null;onRefresh:()=>Promise<void>;onApply:(name:string,claims:string)=>void;disabled:boolean}){
  const [file,setFile]=useState<File|null>(null);
  const [preview,setPreview]=useState('');
  const [job,setJob]=useState<Job|null>(null);
  const [consent,setConsent]=useState(false);
  const [busy,setBusy]=useState(false);
  const [text,setText]=useState('');
  const [name,setName]=useState('');
  const [claims,setClaims]=useState('');
  const [message,setMessage]=useState('');
  const [imageExpired,setImageExpired]=useState(false);
  const requestKey=useRef<string|null>(null);
  const action=useRef(false);
  const input=useRef<HTMLInputElement>(null);
  const refresh=useRef(onRefresh);refresh.current=onRefresh;
  const running=!!job&&['QUEUED','RUNNING'].includes(job.status);
  const result=job?.result as OCRResult|null;

  function show(next:Job){setJob(next);setImageExpired(false);
    const r=next.result as OCRResult|null;setText(r?.corrected_text??r?.text??'');
    setName(r?.reviewed_input?.product_name??'');setClaims(r?.reviewed_input?.claims.join('\n')??'');}
  useEffect(()=>{if(restored){show(restored);setMessage('사진 읽기 기록을 열었어요.');}},[restored]);
  useEffect(()=>{if(deletedId&&job?.id===deletedId){setJob(null);setText('');setName('');setClaims('');setMessage('사진 기록을 삭제했어요.');}},[deletedId,job?.id]);
  useEffect(()=>{
    if(!file){setPreview('');return;}
    const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);
  },[file]);
  useEffect(()=>{
    if(!job||!running)return;
    let active=true;let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const next=await api<Job>('/v2/jobs/'+job!.id);
        if(!active)return;
        setJob(next);
        if(!['QUEUED','RUNNING'].includes(next.status)){
          const r=next.result as OCRResult|null;setText(r?.corrected_text??r?.text??'');
          setMessage(next.status==='FAILED'?'사진 읽기를 마치지 못했어요. 다시 시도하거나 직접 입력해 주세요.':'사진 읽기를 마쳤어요. 틀린 글자를 고쳐 주세요.');
          await refresh.current();return;
        }
      }catch{if(active)setMessage('진행 상태를 확인하지 못했어요. 연결 후 기록에서 다시 열 수 있어요.');}
      if(active)timer=setTimeout(poll,1500);
    }
    timer=setTimeout(poll,1000);return()=>{active=false;clearTimeout(timer);};
  },[job?.id,running]);

  async function act(fn:()=>Promise<void>){if(action.current)return;action.current=true;setBusy(true);
    try{await fn();}catch(e){setMessage(e instanceof Error?e.message:'다시 시도해 주세요.');}
    finally{action.current=false;setBusy(false);}}
  return <section id="photo-input"><h2>사진에서 글자 읽기</h2><p>사진을 보내거나 아래에서 제품명을 직접 입력하세요.</p>
    <p className="hint">PNG·JPEG, 최대 5MB / 1,200만 화소. 사진 속 이름·전화번호·대화는 먼저 가려 주세요. 자동 개인정보 마스킹은 아직 없어요.</p>
    <label htmlFor="photo">광고 사진 선택</label><input ref={input} id="photo" type="file" accept="image/png,image/jpeg" disabled={busy||running||disabled} onChange={e=>{
      const f=e.target.files?.[0]??null;setFile(null);setConsent(false);requestKey.current=null;setMessage('');
      if(f&&(!['image/png','image/jpeg'].includes(f.type)||f.size>5*1024*1024)){setMessage('5MB 이하 PNG·JPEG 사진을 선택해 주세요.');e.target.value='';return;}
      setFile(f);setJob(null);setText('');setName('');setClaims('');
    }}/>
    {preview&&!job&&<img className="ad-preview" src={preview} alt="전송 전 광고 사진 미리보기"/>}
    <label className="consent"><input type="checkbox" checked={consent} disabled={busy||running||disabled} onChange={e=>setConsent(e.target.checked)}/>개인정보를 가렸고, 사진을 이 PC 서버에서 읽고 보관하는 데 동의해요.</label>
    <p className="hint">외부 AI에는 보내지 않아요. 정리한 사진은 최대 1시간, 읽은 글자는 최대 24시간 보관해요. 메타데이터는 제거하지만 사진 속 개인정보는 자동 제거되지 않아요.</p>
    <button disabled={!file||!consent||busy||running||disabled} onClick={()=>void act(async()=>{
      requestKey.current??=crypto.randomUUID();
      const next=await uploadImage(file!,requestKey.current);show(next);requestKey.current=null;
      setFile(null);if(input.current)input.current.value='';setConsent(false);
      setMessage('사진을 접수했어요. 로컬 OCR이 글자를 읽고 있어요.');await refresh.current();
    })}>사진 글자 읽기</button>
    <p role="status" aria-live="polite">{message}</p>
    {job&&<article><h3>사진 읽기 결과</h3>
      {!imageExpired&&job.status!=='CANCELLED'&&<img className="ad-preview" src={'/backend/v2/jobs/'+job.id+'/image'} alt="메타데이터를 제거한 광고 사진" onError={()=>setImageExpired(true)}/>}
      {imageExpired&&<p>사진이 삭제·만료됐거나 불러오지 못했어요. 남아 있는 글자 기록은 아래에서 확인할 수 있어요.</p>}
      {running&&<><p>읽고 있어요. 최대 약 1분 걸릴 수 있어요.</p><button className="secondary" disabled={busy} onClick={()=>void act(async()=>{show(await api<Job>(`/v2/jobs/${job.id}/cancel`,'POST'));await refresh.current();setMessage('취소하고 저장 사진을 삭제했어요.');})}>사진 읽기 취소</button></>}
      {job.status==='FAILED'&&<p>사진을 읽지 못했어요. 필요한 부분만 크게 잘라 다시 보내거나 직접 입력해 주세요.</p>}
      {result&&<><p>{result.status==='NO_TEXT'?'글자를 찾지 못했어요. 직접 적어도 됩니다.':'잘못 읽은 글자가 있는지 사진과 비교해 주세요.'}</p>
        <label htmlFor="ocr-text">읽은 글자 수정 · 최대 4,000자</label><textarea id="ocr-text" value={text} onChange={e=>setText(e.target.value)} maxLength={4000} rows={6}/>
        {text.length>4000&&<p>읽은 글자가 많아요. 필요한 내용을 4,000자 이내로 줄여 저장해 주세요.</p>}
        <button className="secondary" disabled={busy||text.length>4000} onClick={()=>void act(async()=>{setJob(await api<Job>(`/v2/jobs/${job.id}/correction`,'POST',{corrected_text:text}));setMessage('수정본을 저장했어요. OCR 원문은 별도로 유지됩니다.');await refresh.current();})}>수정한 글자 저장</button>
        <details><summary>OCR 원문·인식 정보</summary><blockquote>{result.text||'인식한 글자 없음'}</blockquote><p>{result.engine} / {result.languages}. 단어 위치 {result.words.length}개. 인식 점수는 실제 정확도를 뜻하지 않아요.</p></details>
        <label htmlFor="photo-product">사진 속 제품명</label><input id="photo-product" maxLength={200} value={name} onChange={e=>setName(e.target.value)} placeholder="읽은 글자에서 제품 이름을 확인해 주세요"/>
        <label htmlFor="photo-claims">비교할 광고 문구 · 한 줄에 하나씩 최대 3개</label><textarea id="photo-claims" rows={3} maxLength={902} value={claims} onChange={e=>setClaims(e.target.value)}/>
        <p className="hint">제품명·주장을 자동 확정하지 않아요. 확인 버튼을 누르면 입력 내용을 사진 기록에 저장하고 검색칸으로 옮겨요. 검색과 외부 AI 전송은 별도로 요청해야 합니다.</p>
        <button disabled={busy||disabled||!name.trim()} onClick={()=>void act(async()=>{
          const lines=claims.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
          if(lines.length>3||lines.some(s=>s.length>300)){setMessage('문구는 각각 300자 이내, 최대 3개예요.');return;}
          setJob(await api<Job>(`/v2/jobs/${job.id}/review`,'POST',{product_name:name.trim(),claims:lines}));
          onApply(name.trim(),lines.join('\n'));setMessage('확인한 내용을 저장하고 검색칸에 옮겼어요. 아래에서 제품 찾기를 눌러 주세요.');
          await refresh.current();
        })}>확인한 내용을 검색칸으로 옮기기</button>
      </>}
      <button className="secondary" disabled={busy} onClick={()=>void act(async()=>{await api('/v2/jobs/'+job.id,'DELETE');setJob(null);setText('');setName('');setClaims('');await refresh.current();setMessage('사진과 읽은 글자 기록을 삭제했어요.');})}>사진과 글자 기록 삭제</button>
    </article>}
  </section>;
}