"""Real HTTP/DB/worker integration; synthetic OCR/search/model boundaries only."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from gyeot.app import create_app
from gyeot.config import Config
from gyeot.adapters.comparison import compare_claims
from gyeot.adapters.connectivity import ProbeError
from gyeot.worker import process, run_once
from test_foundation import fake_search
from test_images import picture


@pytest.fixture
def flow(store,monkeypatch):
    cfg=Config('unused',ai_gateway_api_key='synthetic-not-a-real-key')
    headers={'Origin':cfg.web_origin,'X-Gyeot-Request':'1'}
    monkeypatch.setattr('gyeot.worker.extract_text',lambda image:dict(
        status='TEXT_EXTRACTED',text='합성 시험',words=[],engine='synthetic',languages='kor'))
    with TestClient(create_app(cfg,store)) as client:
        assert client.post('/v2/session',json={},headers=headers).status_code==200
        def post(path,data):
            return client.post(path,json=data,headers=dict(headers,**{'Idempotency-Key':str(uuid4())}))
        response=client.post('/v2/jobs/ocr',content=picture(),headers=dict(headers,**{
            'Content-Type':'image/png','X-Image-Consent':'confirmed','Idempotency-Key':str(uuid4())}))
        assert response.status_code==202
        photo='/v2/jobs/'+response.json()['id']
        assert run_once(store,cfg)
        assert post(photo+'/correction',{'corrected_text':'사용자 수정'}).status_code==200
        review={'product_name':'합성 시험','claims':['사진에서 확인한 문구']}
        assert post(photo+'/review',review).status_code==200
        saved=client.get(photo).json()['result']['reviewed_input']
        response=post('/v2/jobs/search',dict(name=saved['product_name'],reviewed_claims=saved['claims']))
        assert response.status_code==202
        search='/v2/jobs/'+response.json()['id']
        assert run_once(store,cfg,handler=lambda config,job:process(config,job,searcher=fake_search))
        assert post(search+'/selection',{'product_key':'I0030:123'}).status_code==200
        yield client,post,search,photo,cfg,headers


def model_reply(request,wrong_quote=False):
    payload=json.loads(request.data)
    data=json.loads(payload['messages'][1]['content'])
    assert set(data)=={'claims','official_quote'}
    assert data['official_quote']=='합성 기능성 원문'
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'claims':[
        dict(claim_index=i,ad_quote=claim,relation='WITHIN_SCOPE',
             evidence_quote='조작된 인용' if wrong_quote else data['official_quote'])
        for i,claim in enumerate(data['claims'])]})}}]}


def comparison(post,search,**changes):
    return post(search+'/comparison',dict(product_key='I0030:123',claims=['비교 직전에 수정한 문구'],
                                        consent_external=True,**changes))


def test_photo_to_comparison_restore_and_delete(store,flow):
    client,post,search,photo,cfg,headers=flow
    denied=post(search+'/comparison',dict(product_key='I0030:123',claims=['시험'],consent_external=False))
    assert denied.status_code==422
    response=comparison(post,search);assert response.status_code==202
    child='/v2/jobs/'+response.json()['id']
    calls=[]
    def transport(request):
        calls.append(request)
        return model_reply(request)
    assert run_once(store,cfg,handler=lambda config,job:process(config,job,
        comparer=lambda config,selected,claims:compare_claims(config,selected,claims,transport=transport)))
    restored=client.get(child).json()
    assert restored['status']=='SUCCEEDED'
    assert restored['result']['status']=='EXPERIMENTAL_AI_RESULT'
    assert restored['result']['semantic_correctness_verified'] is False
    assert restored['comparison_input']=={'claims':['비교 직전에 수정한 문구']}
    assert 'consent_external' not in restored['comparison_input']
    assert len(calls)==1 and store.claim() is None
    with TestClient(create_app(cfg,store)) as other:
        other.post('/v2/session',json={},headers=headers)
        assert other.get(child).status_code==404
    assert client.delete(search,headers=headers).status_code==204
    assert client.get(child).status_code==404
    assert client.get(photo).status_code==200
    assert client.delete(photo,headers=headers).status_code==204
    assert client.get(photo+'/image').status_code==404


@pytest.mark.parametrize('mode,reason',[
    ('invalid','MODEL_OUTPUT_REJECTED'),('unavailable','MODEL_UNAVAILABLE'),
    ('missing','NO_PRODUCT_FUNCTIONALITY')])
def test_comparison_held_without_unsafe_result_or_retry(store,flow,mode,reason):
    client,post,search,photo,cfg,headers=flow
    key='I1250:123' if mode=='missing' else 'I0030:123'
    if mode=='missing':assert post(search+'/selection',{'product_key':key}).status_code==200
    response=post(search+'/comparison',dict(product_key=key,claims=['시험'],consent_external=True))
    assert response.status_code==202
    calls=[]
    def transport(request):
        calls.append(request)
        if mode=='unavailable':raise ProbeError('NETWORK_ERROR')
        return model_reply(request,wrong_quote=True)
    assert run_once(store,cfg,handler=lambda config,job:process(config,job,
        comparer=lambda config,selected,claims:compare_claims(config,selected,claims,transport=transport)))
    result=client.get('/v2/jobs/'+response.json()['id']).json()['result']
    assert result['status']=='NOT_ASSESSED' and result['reason']==reason
    assert all(c['evidence_quote']=='' for c in result['claims'])
    assert len(calls)==(0 if mode=='missing' else 1)
    assert not run_once(store,cfg)


@pytest.mark.parametrize('action',['cancel','delete','change_product'])
def test_comparison_late_result_never_reappears(store,flow,action):
    client,post,search,photo,cfg,headers=flow
    response=comparison(post,search);assert response.status_code==202
    child='/v2/jobs/'+response.json()['id'];lease=store.claim()
    if action=='cancel':assert post(child+'/cancel',{}).status_code==200
    elif action=='delete':assert client.delete(search,headers=headers).status_code==204
    else:assert post(search+'/selection',{'product_key':'I1250:123'}).status_code==200
    assert not store.finish(lease['id'],lease['lease_token'],{'late':True})
    if action=='cancel':
        restored=client.get(child).json()
        assert restored['status']=='CANCELLED' and restored['result'] is None
        assert restored['comparison_input']=={'claims':[]}
    else:assert client.get(child).status_code==404