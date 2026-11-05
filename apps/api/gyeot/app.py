from uuid import UUID

import psycopg
from fastapi import FastAPI, Request, Response, HTTPException, Header
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import load_config
from .db import Store, Conflict, Limited, public_job
from .schemas import Search, Selection, Compare, OCRCorrection, OCRReview
from .images import normalize_image, InvalidImage, MAX_BYTES
from starlette.concurrency import run_in_threadpool


def create_app(config=None, store=None):
    config=config or load_config()
    store=store or Store(config.database_url)
    app=FastAPI(title='GYEOT service foundation',version='0.2.0',docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.method in ('POST','DELETE','PATCH'):
            if request.headers.get('origin')!=config.web_origin or request.headers.get('x-gyeot-request')!='1':
                return JSONResponse({'detail':'같은 서비스 화면에서 요청해 주세요.'},403)
            if request.method=='POST':
                image_upload=request.url.path=='/v2/jobs/ocr'
                content_type=request.headers.get('content-type','').split(';')[0]
                if content_type not in (('image/png','image/jpeg') if image_upload else ('application/json',)):
                    return JSONResponse({'detail':'JSON 요청만 허용합니다.'},415)
                if image_upload:
                    try: store.owner(request.cookies.get('gyeot_session'))
                    except PermissionError:return JSONResponse({'detail':'세션을 다시 시작해 주세요.'},401)
                # Stream-cap body before framework JSON parsing, including chunked requests.
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>(MAX_BYTES if image_upload else 16384):
                        return JSONResponse({'detail':'입력이 너무 큽니다.'},413)
                request._body=bytes(body)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({'detail':'결과가 없거나 만료됐어요.'},404)

    @app.exception_handler(PermissionError)
    async def unauthenticated(request,error):
        return JSONResponse({'detail':'브라우저 세션을 다시 시작해 주세요.'},401)

    @app.exception_handler(Conflict)
    async def conflict(request,error):
        return JSONResponse({'detail':str(error)},409)

    @app.exception_handler(Limited)
    async def limited(request,error):
        return JSONResponse({'detail':'요청 한도에 도달했어요. 잠시 후 다시 시도해 주세요.'},429)

    @app.exception_handler(psycopg.Error)
    async def database_error(request,error):
        return JSONResponse({'detail':'저장소 연결을 확인하고 다시 시도해 주세요.'},503)

    def owner(request):
        return store.owner(request.cookies.get('gyeot_session'))

    @app.get('/health')
    def health():
        with store.connect() as conn:
            conn.execute('SELECT 1')
        return {'status':'ok','storage':'postgresql'}

    @app.post('/v2/session')
    def session(request:Request,response:Response):
        token=store.session(request.cookies.get('gyeot_session'))
        response.set_cookie('gyeot_session',token,max_age=604800,httponly=True,secure=config.cookie_secure,samesite='strict',path='/')
        return {'ready':True}

    @app.get('/v2/jobs')
    def list_jobs(request:Request):
        return {'jobs':[public_job(row) for row in store.list(owner(request))]}

    @app.post('/v2/jobs/search',status_code=202)
    def search(payload:Search,request:Request,idempotency_key:UUID=Header()):
        return public_job(store.enqueue(owner(request),str(idempotency_key),'SEARCH',payload.model_dump()))

    @app.post('/v2/jobs/ocr',status_code=202)
    async def upload(request:Request,idempotency_key:UUID=Header(),x_image_consent:str=Header(default='')):
        if x_image_consent!='confirmed':
            raise HTTPException(422,'사진의 개인정보·이용 권한 및 로컬 보관 안내를 확인해 주세요.')
        try:
            image=await run_in_threadpool(normalize_image,await request.body(),request.headers.get('content-type','').split(';')[0])
        except InvalidImage as error:
            raise HTTPException(422,str(error)) from None
        payload=dict(image_sha256=image['sha256'],width=image['width'],height=image['height'],
                     consent_local_processing=True,policy_version='local-ocr-0.1')
        user=await run_in_threadpool(owner,request)
        job=await run_in_threadpool(store.enqueue,user,str(idempotency_key),'OCR',payload,None,image)
        return public_job(job)

    @app.get('/v2/jobs/{job_id}/image')
    def get_image(job_id:UUID,request:Request):
        image=store.image(owner(request),job_id)
        return Response(bytes(image['image_bytes']),media_type='image/png',
                        headers={'Content-Disposition':'inline; filename="advertisement.png"'})

    @app.post('/v2/jobs/{job_id}/correction')
    def correction(job_id:UUID,payload:OCRCorrection,request:Request):
        return public_job(store.correct_ocr(owner(request),job_id,payload.corrected_text))

    @app.get('/v2/jobs/{job_id}')
    def get_job(job_id:UUID,request:Request):
        return public_job(store.get(owner(request),job_id))

    @app.post('/v2/jobs/{job_id}/review')
    def review(job_id:UUID,payload:OCRReview,request:Request):
        return public_job(store.correct_ocr(owner(request),job_id,review=payload.model_dump()))

    @app.post('/v2/jobs/{job_id}/selection')
    def selection(job_id:UUID,payload:Selection,request:Request):
        return public_job(store.select(owner(request),job_id,payload.product_key))

    @app.post('/v2/jobs/{job_id}/comparison',status_code=202)
    def compare(job_id:UUID,payload:Compare,request:Request,idempotency_key:UUID=Header()):
        return public_job(store.enqueue(owner(request),str(idempotency_key),'COMPARE',payload.model_dump(),job_id))

    @app.post('/v2/jobs/{job_id}/cancel')
    def cancel(job_id:UUID,request:Request):
        return public_job(store.cancel(owner(request),job_id))

    @app.delete('/v2/jobs/{job_id}',status_code=204)
    def delete(job_id:UUID,request:Request):
        store.remove(owner(request),job_id)
        return Response(status_code=204)

    return app


app=create_app()