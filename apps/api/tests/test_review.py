from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from gyeot.app import create_app
from gyeot.config import Config
from gyeot.db import public_job
from gyeot.schemas import Search
from gyeot.worker import process
from test_images import picture


def test_review_persists_without_overwriting_ocr_and_is_owner_only(store):
    cfg=Config('unused')
    headers={'Origin':cfg.web_origin,'X-Gyeot-Request':'1'}
    with TestClient(create_app(cfg,store)) as a, TestClient(create_app(cfg,store)) as b:
        for client in (a,b):
            assert client.post('/v2/session',json={},headers=headers).status_code==200
        upload=a.post('/v2/jobs/ocr',content=picture(),headers=dict(headers,**{
            'Content-Type':'image/png','X-Image-Consent':'confirmed','Idempotency-Key':str(uuid4())}))
        assert upload.status_code==202
        path='/v2/jobs/'+upload.json()['id']
        review={'product_name':'합성 제품','claims':['합성 시험 문구']}
        assert a.post(path+'/review',json=review,headers=headers).status_code==409
        lease=store.claim()
        assert store.finish(lease['id'],lease['lease_token'],{'text':'OCR 원문','words':[],'status':'TEXT_EXTRACTED'})
        assert a.post(path+'/review',json=review).status_code==403
        assert b.post(path+'/review',json=review,headers=headers).status_code==404
        assert a.post(path+'/review',json=review,headers=headers).status_code==200
        assert a.post(path+'/correction',json={'corrected_text':'수정 원문'},headers=headers).status_code==200
        result=a.get(path).json()['result']
        assert result['reviewed_input']==review
        assert result['text']=='OCR 원문' and result['corrected_text']=='수정 원문'
        # Updating the confirmed input preserves the correction, including empty claims.
        review['claims']=[]
        result=a.post(path+'/review',json=review,headers=headers).json()['result']
        assert result['reviewed_input']==review and result['corrected_text']=='수정 원문'
        assert a.delete(path,headers=headers).status_code==204
        assert a.post(path+'/review',json=review,headers=headers).status_code==404


@pytest.mark.parametrize('review',[
    {'product_name':'   ','claims':[]},
    {'product_name':'x'*201,'claims':[]},
    {'product_name':'시험','claims':['x']*4},
    {'product_name':'시험','claims':['x'*301]},
    {'product_name':'시험','claims':['   ']},
    {'product_name':'시험','claims':[],'consent_external':True},
])
def test_invalid_review_rejected_at_http_boundary(store,review):
    cfg=Config('unused');headers={'Origin':cfg.web_origin,'X-Gyeot-Request':'1'}
    with TestClient(create_app(cfg,store)) as client:
        client.post('/v2/session',json={},headers=headers)
        assert client.post('/v2/jobs/'+str(uuid4())+'/review',json=review,headers=headers).status_code==422


def test_search_restores_confirmed_claims_without_sending_them_to_food_api(store):
    payload=Search(name='합성 제품',reviewed_claims=['합성 시험 문구']).model_dump()
    owner=store.owner(store.session())
    job=store.enqueue(owner,str(uuid4()),'SEARCH',payload)
    assert public_job(store.get(owner,job['id']))['search_input']==payload
    calls=[]
    def searcher(config,service,**kwargs):
        calls.append(kwargs)
        return dict(service=service,status='NOT_FOUND',reason='NO_MATCH',reported_total_count=0,
                    truncated=False,retrieved_at='2026-11-03T00:00:00Z',candidates=[])
    process(Config('unused'),store.claim(),searcher=searcher)
    assert len(calls)==2
    assert all(call==dict(name='합성 제품',number='',manufacturer='') for call in calls)
    store.cancel(owner,job['id'])
    assert public_job(store.get(owner,job['id']))['search_input']=={}