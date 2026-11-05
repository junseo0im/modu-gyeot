"""Bounded official candidate retrieval, not automatic product identification."""

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request

from .connectivity import FOOD_BASE, ProbeError, request_json

FIELDS = ('PRDLST_REPORT_NO', 'PRDLST_NM', 'BSSH_NM', 'LCNS_NO',
          'PRDLST_DCNM', 'PRDLST_CDNM', 'PRIMARY_FNCLTY', 'LAST_UPDT_DTM',
          'PRMS_DT', 'PRODUCTION')


def search_products(settings, service, *, name='', number='', manufacturer='', limit=10,
                    transport=request_json):
    if service not in ('I0030', 'I1250'):
        raise ValueError('Only product services may be searched')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Limit must be between 1 and 20')
    filters = {}
    for key, value in (('PRDLST_NM', name), ('PRDLST_REPORT_NO', number), ('BSSH_NM', manufacturer)):
        if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid search text')
        if value.strip():
            filters[key] = value.strip()
    if not name.strip() and not number.strip():
        raise ValueError('Product name or report number required')
    base = dict(service=service, filters=filters, retrieved_at=datetime.now(timezone.utc).isoformat(),
                identification='NOT_CONFIRMED', assessment_status='NOT_ASSESSED',
                candidates=[], requested_limit=limit, reported_total_count=None, truncated=None,
                source_url=f'https://www.foodsafetykorea.go.kr/api/openApiInfo.do?svc_no={service}')
    if not settings.food_api_key:
        return dict(base, status='UNAVAILABLE', reason='KEY_NOT_CONFIGURED')
    suffix = '&'.join(key + '=' + quote(value, safe='') for key, value in filters.items())
    url = f'{FOOD_BASE}/{quote(settings.food_api_key, safe="")}/{service}/json/1/{limit}/{suffix}'
    try:
        data = transport(Request(url, headers={'Accept': 'application/json'}))
        payload = data.get(service, data)
        if not isinstance(payload, dict) or not isinstance(payload.get('RESULT'), dict):
            raise ProbeError('INVALID_RESPONSE')
        code = payload['RESULT'].get('CODE')
        if code == 'INFO-200':
            return dict(base, status='NOT_FOUND', reason='NO_RECORDS_FOR_QUERY', truncated=False)
        if code != 'INFO-000':
            safe_code = code if isinstance(code, str) and re.fullmatch(r'(INFO|ERROR)-\d{3}', code) else 'API_REJECTED'
            return dict(base, status='UNAVAILABLE', reason=safe_code)
        rows = payload.get('row')
        if not isinstance(rows, list) or len(rows) > limit:
            raise ProbeError('INVALID_RESPONSE')
        candidates = []
        for row in rows:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip()
                                                  for k in ('PRDLST_REPORT_NO', 'PRDLST_NM', 'BSSH_NM')):
                raise ProbeError('INVALID_PRODUCT_IDENTITY')
            record = {key: row[key] for key in FIELDS if key in row and isinstance(row[key], str)}
            # Food manufacturing records must not inherit functionality from another source.
            if service == 'I1250':
                record.pop('PRIMARY_FNCLTY', None)
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            candidates.append(dict(key=service + ':' + row['PRDLST_REPORT_NO'], record=record,
                                   record_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                                   match_status='CANDIDATE_ONLY'))
        raw_total = payload.get('total_count')
        total = int(raw_total) if isinstance(raw_total, (str, int)) and str(raw_total).isdigit() else None
        base.update(candidates=candidates, reported_total_count=total,
                    truncated=total > len(rows) if total is not None else None)
        return dict(base, status='CANDIDATES' if rows else 'NOT_FOUND',
                    reason='VERIFY_IDENTITY_AND_APPLICABILITY' if rows else 'NO_RECORDS_FOR_QUERY')
    except ProbeError as error:
        return dict(base, status='UNAVAILABLE', reason=str(error))