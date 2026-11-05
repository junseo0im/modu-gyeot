export type Candidate = {key:string; service:string; name:string; manufacturer:string; number:string};
export type Selected = {product_key:string; record:Record<string,string>; quote:string;
  evidence_availability:'PRESENT'|'MISSING'; source_url:string; retrieved_at:string};
export type ClaimResult = {ad_quote:string; evidence_quote:string; relation:string|null; explanation:string};
export type SearchResult = {status:string; candidates:Candidate[]; selected:Selected|null;
  sources:{service:string;status:string;truncated:boolean|null;reported_total_count:number|null}[]};
export type ComparisonResult = {status:string;reason:string;claims:ClaimResult[];semantic_correctness_verified:false};
export type OCRResult = {status:'TEXT_EXTRACTED'|'NO_TEXT';text:string;corrected_text?:string;review_status?:string;
  reviewed_input?:{product_name:string;claims:string[]};
  words:{text:string;x:number;y:number;width:number;height:number;confidence:number;line_id:string}[];
  width:number;height:number;engine:string;languages:string;review_required:true};
export type Job = {id:string;kind:'SEARCH'|'COMPARE'|'OCR';status:'QUEUED'|'RUNNING'|'SUCCEEDED'|'FAILED'|'CANCELLED';
  comparison_input?:{claims:string[]}|null;
  search_input?:{name:string;number:string;manufacturer:string;service:string;reviewed_claims?:string[]}|null;
  result:SearchResult|ComparisonResult|OCRResult|null;error_code:string|null;parent_id:string|null;created_at:string;expires_at:string};

export async function uploadImage(file:File,key:string):Promise<Job>{
  const response=await fetch('/backend/v2/jobs/ocr',{method:'POST',credentials:'same-origin',
    headers:{'X-Gyeot-Request':'1','X-Image-Consent':'confirmed','Idempotency-Key':key,'Content-Type':file.type},
    body:file,signal:AbortSignal.timeout(30000)});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'사진 전송을 확인해 주세요.');
  return result as Job;
}

export async function api<T>(path:string, method='GET', data?:unknown, idempotencyKey?:string):Promise<T> {
  const response=await fetch('/backend'+path,{method,credentials:'same-origin',cache:'no-store',
    headers:{'X-Gyeot-Request':'1',...(method==='POST'?{'Content-Type':'application/json'}:{}),
      ...(idempotencyKey?{'Idempotency-Key':idempotencyKey}:{})},
    body:method==='POST'?JSON.stringify(data??{}):undefined,signal:AbortSignal.timeout(15000)});
  if(response.status===204) return undefined as T;
  const result=await response.json();
  if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'입력을 확인하고 다시 시도해 주세요.');
  return result as T;
}