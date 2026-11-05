from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from gyeot.app import create_app
from gyeot.config import Config
from gyeot.db import Conflict, Limited, fingerprint, public_job
from gyeot.schemas import Search
from gyeot.worker import process, run_once

PAYLOAD = Search(name='합성 시험').model_dump()


def fake_search(config, service, **kwargs):
    record={'PRDLST_NM':'합성 시험','BSSH_NM':'가상 제조사','PRDLST_REPORT_NO':'123'}
    if service=='I0030':
        record['PRIMARY_FNCLTY']='합성 기능성 원문'
    return dict(service=service,status='CANDIDATES',reason='CANDIDATE_ONLY',reported_total_count=1,
                truncated=False,retrieved_at='2026-11-03T00:00:00Z',source_url='https://www.foodsafetykorea.go.kr/',
                candidates=[dict(key=service+':123',record=record,record_sha256=fingerprint(record))])


def complete_search(store,owner):
    job=store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)
    claimed=store.claim()
    result=process(Config('unused'),claimed,searcher=fake_search)
    assert store.finish(claimed['id'],claimed['lease_token'],result)
    return store.select(owner,job['id'],'I0030:123')


def test_migrations_idempotent_and_durable(store):
    store.migrate()
    token=store.session(); owner=store.owner(token)
    row=store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)
    # Separate Store instance / connection simulates server restart without losing queue.
    restored=type(store)(store.url)
    assert restored.get(owner,row['id'])['status']=='QUEUED'
    assert restored.owner(token)==owner


def test_idempotency_and_conflict(store):
    owner=store.owner(store.session()); key=str(uuid4())
    first=store.enqueue(owner,key,'SEARCH',PAYLOAD)
    assert store.enqueue(owner,key,'SEARCH',PAYLOAD)['id']==first['id']
    with pytest.raises(Conflict):
        store.enqueue(owner,key,'SEARCH',dict(PAYLOAD,name='다름'))
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM call_budget').fetchone()['n']==1


def test_two_workers_claim_once(store):
    owner=store.owner(store.session())
    for _ in range(2):store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)
    with ThreadPoolExecutor(2) as pool:
        claimed=list(pool.map(lambda _:store.claim(),range(2)))
    assert len({j['id'] for j in claimed})==2
    assert store.claim() is None


def test_cancel_and_delete_fence_late_completion(store):
    owner=store.owner(store.session())
    job=store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD); lease=store.claim()
    store.cancel(owner,job['id'])
    assert not store.finish(job['id'],lease['lease_token'],{'late':True})
    assert store.get(owner,job['id'])['payload']=={}
    store.remove(owner,job['id'])
    assert not store.finish(job['id'],lease['lease_token'],{'late':True})
    with pytest.raises(KeyError):store.get(owner,job['id'])


def test_stale_worker_not_automatically_billed_twice(store):
    owner=store.owner(store.session())
    job=store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD); lease=store.claim()
    with store.connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(job['id'],))
    assert store.claim() is None
    assert store.get(owner,job['id'])['error_code']=='WORKER_INTERRUPTED'
    assert not store.finish(job['id'],lease['lease_token'],{})


def test_snapshot_and_comparison_relationship(store):
    owner=store.owner(store.session()); parent=complete_search(store,owner)
    assert 'record' not in public_job(parent)['result']['candidates'][0]
    selected=parent['result']['selected']; assert selected['quote']=='합성 기능성 원문'
    child=store.enqueue(owner,str(uuid4()),'COMPARE',dict(product_key='I0030:123',claims=['시험'],consent_external=True),parent['id'])
    assert child['payload']['selected']['record_sha256']==selected['record_sha256']
    store.select(owner,parent['id'],'I1250:123')
    with pytest.raises(KeyError):store.get(owner,child['id'])
    assert store.get(owner,parent['id'])['result']['selected']['evidence_availability']=='MISSING'


def test_foreign_owner_and_expiry(store):
    a=store.owner(store.session()); b=store.owner(store.session())
    row=store.enqueue(a,str(uuid4()),'SEARCH',PAYLOAD)
    with pytest.raises(KeyError):store.get(b,row['id'])
    with pytest.raises(KeyError):store.select(b,row['id'],'I0030:123')
    with pytest.raises(KeyError):store.remove(b,row['id'])
    with store.connect() as conn:
        conn.execute("UPDATE jobs SET expires_at=now()-interval '1 second' WHERE id=%s",(row['id'],))
    with pytest.raises(KeyError):store.get(a,row['id'])
    assert store.claim() is None


def test_budget_shared_across_store_instances(store):
    owner=store.owner(store.session())
    for _ in range(5):store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)
    restored=type(store)(store.url)
    with pytest.raises(Limited):restored.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)


def test_worker_catches_errors_without_details(store):
    owner=store.owner(store.session()); row=store.enqueue(owner,str(uuid4()),'SEARCH',PAYLOAD)
    def broken(*args):raise ValueError('SECRET-DO-NOT-LOG')
    assert run_once(store,Config('unused'),handler=broken)
    failed=store.get(owner,row['id'])
    assert failed['error_code']=='PROCESSING_FAILED' and failed['result'] is None


def test_http_session_ownership_and_csrf(store):
    cfg=Config('unused',web_origin='http://localhost:3000')
    headers={'Origin':cfg.web_origin,'X-Gyeot-Request':'1'}
    with TestClient(create_app(cfg,store)) as a, TestClient(create_app(cfg,store)) as b:
        assert a.post('/v2/session',json={}).status_code==403
        assert a.post('/v2/session',json={},headers=headers).status_code==200
        cookie=a.cookies.get('gyeot_session'); assert cookie
        key=str(uuid4())
        row=a.post('/v2/jobs/search',json=PAYLOAD,headers=dict(headers,**{'Idempotency-Key':key}))
        assert row.status_code==202
        job_id=row.json()['id']
        assert a.get('/v2/jobs/'+job_id).status_code==200
        assert b.get('/v2/jobs/'+job_id).status_code==401
        b.post('/v2/session',json={},headers=headers)
        assert b.get('/v2/jobs/'+job_id).status_code==404
        assert a.post('/v2/jobs/search',json=PAYLOAD,headers=dict(headers,**{'Idempotency-Key':key})).json()['id']==job_id
        assert a.post('/v2/jobs/search',content=b'x'*17000,headers=dict(headers,**{'Content-Type':'application/json'})).status_code==413
        assert a.delete('/v2/jobs/'+job_id,headers=headers).status_code==204
        assert a.get('/v2/jobs/'+job_id).status_code==404