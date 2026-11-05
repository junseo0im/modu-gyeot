import argparse
import time

from .adapters.food_search import search_products
from .adapters.comparison import compare_claims
from .config import load_config
from .db import Store, fingerprint
from .adapters.ocr import extract_text


def process(config, job, searcher=search_products, comparer=compare_claims):
    p = job['payload']
    if job['kind']=='COMPARE':
        selected = p['selected']
        if fingerprint(selected['record'])!=selected['record_sha256']:
            raise ValueError('Invalid snapshot')
        expected = selected['record'].get('PRIMARY_FNCLTY','') if selected['product_key'].startswith('I0030:') else ''
        if selected['quote']!=expected:
            raise ValueError('Invalid quote')
        return comparer(config,selected,p['claims'])
    services=('I0030','I1250') if p['service']=='both' else (p['service'],)
    sources=[]
    candidates=[]
    for service in services:
        result=searcher(config,service,name=p['name'],number=p['number'],manufacturer=p['manufacturer'])
        sources.append({k:result[k] for k in ('service','status','reason','reported_total_count','truncated','retrieved_at')})
        for c in result['candidates']:
            r=c['record']
            if p['number'] and p['number']!=r['PRDLST_REPORT_NO']:
                continue
            candidates.append(dict(**c,service=service,name=r['PRDLST_NM'],manufacturer=r['BSSH_NM'],
                number=r['PRDLST_REPORT_NO'],source_url=result['source_url'],retrieved_at=result['retrieved_at']))
    failed=any(s['status']=='UNAVAILABLE' for s in sources)
    status=('PARTIAL' if failed else 'CANDIDATES') if candidates else ('UNAVAILABLE' if failed else 'NOT_FOUND')
    return dict(status=status,candidates=candidates,sources=sources,selected=None,assessment_status='NOT_ASSESSED')


def run_once(store, config, handler=process):
    job=store.claim()
    if not job:
        return False
    try:
        if job['kind']=='OCR':
            image=store.image(job['owner_hash'],job['id'])
            result=extract_text(bytes(image['image_bytes']))
            result.update(width=image['width'],height=image['height'],review_required=True)
        else:
            result=handler(config,job)
        store.finish(job['id'],job['lease_token'],result=result)
    except Exception:
        # Do not log user data, keys, provider bodies or URLs.
        store.finish(job['id'],job['lease_token'],error='PROCESSING_FAILED')
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    config=load_config(); store=Store(config.database_url)
    while True:
        try:
            worked=run_once(store,config)
        except Exception:
            worked=False
            print('Worker storage unavailable; retrying without request details',flush=True)
        if args.once:
            break
        if not worked:
            time.sleep(1)