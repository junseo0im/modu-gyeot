import hashlib
import json
import secrets
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class Conflict(Exception):
    pass


class Limited(Exception):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, url):
        self.url = url

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5,
                               options='-c statement_timeout=10000 -c lock_timeout=5000')

    def migrate(self):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(798113)')
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, sha256 text NOT NULL)')
            for path in sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql')):
                content = path.read_text(encoding='utf-8')
                sha = hashlib.sha256(content.encode()).hexdigest()
                row = conn.execute('SELECT sha256 FROM schema_migrations WHERE version=%s', (path.name,)).fetchone()
                if row:
                    if row['sha256'] != sha:
                        raise RuntimeError('Applied migration changed')
                    continue
                conn.execute(content)
                conn.execute('INSERT INTO schema_migrations VALUES (%s,%s)', (path.name, sha))

    def session(self, token=None):
        with self.connect() as conn:
            if token and len(token) <= 128:
                row = conn.execute('SELECT token_hash FROM sessions WHERE token_hash=%s AND expires_at>now()',
                                   (token_hash(token),)).fetchone()
                if row:
                    return token
            conn.execute('SELECT pg_advisory_xact_lock(798114)')
            if conn.execute("SELECT count(*) AS n FROM sessions WHERE created_at>now()-interval '1 hour'").fetchone()['n'] >= 100:
                raise Limited()
            token = secrets.token_urlsafe(32)
            conn.execute('INSERT INTO sessions(token_hash) VALUES (%s)', (token_hash(token),))
            return token

    def owner(self, token):
        if not token or len(token)>128:
            raise PermissionError()
        owner = token_hash(token)
        with self.connect() as conn:
            if not conn.execute('SELECT 1 FROM sessions WHERE token_hash=%s AND expires_at>now()', (owner,)).fetchone():
                raise PermissionError()
        return owner

    def enqueue(self, owner, request_key, kind, payload, parent_id=None, image=None):
        request_hash = fingerprint({'kind':kind, 'payload':payload, 'parent_id':str(parent_id) if parent_id else None})
        with self.connect() as conn:
            # Serialize per session; duplicate submission doesn't reserve another quota unit.
            if not conn.execute('SELECT 1 FROM sessions WHERE token_hash=%s AND expires_at>now() FOR UPDATE', (owner,)).fetchone():
                raise PermissionError()
            existing = conn.execute('SELECT * FROM jobs WHERE owner_hash=%s AND request_key=%s AND expires_at>now()',
                                    (owner,request_key)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise Conflict('동일 요청 번호에 다른 입력을 사용할 수 없습니다.')
                return existing
            # Do not let an expired idempotency key silently create different work.
            if conn.execute('SELECT 1 FROM jobs WHERE owner_hash=%s AND request_key=%s', (owner,request_key)).fetchone():
                raise Conflict('만료된 요청 번호입니다. 새 요청으로 시작해 주세요.')
            if kind == 'COMPARE':
                parent = conn.execute('SELECT * FROM jobs WHERE id=%s AND owner_hash=%s AND expires_at>now() FOR UPDATE',
                                      (parent_id,owner)).fetchone()
                if not parent:
                    raise KeyError()
                selected = (parent['result'] or {}).get('selected')
                if parent['status'] != 'SUCCEEDED' or not selected or selected['product_key'] != payload['product_key']:
                    raise Conflict('먼저 같은 제품의 기록을 선택해 주세요.')
                payload = dict(payload, selected=selected, parent_id=str(parent_id))
            conn.execute('SELECT pg_advisory_xact_lock(798115)')
            if conn.execute("SELECT count(*) AS n FROM jobs WHERE status IN ('QUEUED','RUNNING') AND expires_at>now()").fetchone()['n'] >= 50:
                raise Limited()
            per_user = conn.execute("SELECT count(*) AS n FROM jobs WHERE owner_hash=%s AND created_at>now()-interval '1 hour'", (owner,)).fetchone()['n']
            if per_user >= 20:
                raise Limited()
            units = 2 if kind=='SEARCH' and payload['service']=='both' else 1
            minute, hour = (10,80) if kind=='SEARCH' else (3,20)
            budget = conn.execute("""SELECT COALESCE(sum(units),0) AS hour,
                COALESCE(sum(units) FILTER (WHERE reserved_at>now()-interval '1 minute'),0) AS minute
                FROM call_budget WHERE kind=%s AND reserved_at>now()-interval '1 hour'""", (kind,)).fetchone()
            if budget['minute']+units > minute or budget['hour']+units > hour:
                raise Limited()
            conn.execute('INSERT INTO call_budget(kind,units) VALUES (%s,%s)', (kind,units))
            job = conn.execute("""INSERT INTO jobs(id,owner_hash,request_key,request_hash,kind,status,payload)
                VALUES (%s,%s,%s,%s,%s,'QUEUED',%s) RETURNING *""",
                (uuid4(),owner,request_key,request_hash,kind,Jsonb(payload))).fetchone()
            if kind=='OCR':
                if image is None or image['sha256']!=payload.get('image_sha256'):
                    raise Conflict('이미지 검증에 실패했어요.')
                conn.execute('INSERT INTO job_images(job_id,image_bytes,sha256,width,height) VALUES (%s,%s,%s,%s,%s)',
                             (job['id'],image['data'],image['sha256'],image['width'],image['height']))
            return job

    def image(self, owner, job_id):
        with self.connect() as conn:
            row=conn.execute('''SELECT i.image_bytes,i.sha256,i.width,i.height FROM job_images i
                JOIN jobs j ON j.id=i.job_id WHERE j.id=%s AND j.owner_hash=%s
                AND j.expires_at>now() AND i.expires_at>now()''',(job_id,owner)).fetchone()
            if not row:raise KeyError()
            return row

    def correct_ocr(self, owner, job_id, text=None, review=None):
        with self.connect() as conn:
            row=conn.execute('SELECT * FROM jobs WHERE id=%s AND owner_hash=%s AND expires_at>now() FOR UPDATE',
                             (job_id,owner)).fetchone()
            if not row:raise KeyError()
            if row['kind']!='OCR' or row['status']!='SUCCEEDED':
                raise Conflict('사진 읽기가 끝난 뒤 수정해 주세요.')
            result=row['result']
            if review is not None:
                result['reviewed_input']=review
            else:
                result['corrected_text']=text
                result['review_status']='USER_EDITED_NOT_GOLD'
            return conn.execute('UPDATE jobs SET result=%s,updated_at=now() WHERE id=%s RETURNING *',
                                (Jsonb(result),job_id)).fetchone()

    def get(self, owner, job_id):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=%s AND owner_hash=%s AND expires_at>now()', (job_id,owner)).fetchone()
            if not row:
                raise KeyError()
            return row

    def list(self, owner):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM jobs WHERE owner_hash=%s AND expires_at>now() ORDER BY created_at DESC LIMIT 50', (owner,)).fetchall()

    def select(self, owner, job_id, product_key):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=%s AND owner_hash=%s AND expires_at>now() FOR UPDATE', (job_id,owner)).fetchone()
            if not row:
                raise KeyError()
            if row['kind']!='SEARCH' or row['status']!='SUCCEEDED':
                raise Conflict('검색이 완료된 뒤 제품을 선택해 주세요.')
            result = row['result']
            candidate = next((c for c in result['candidates'] if c['key']==product_key),None)
            if not candidate:
                raise Conflict('이번 검색의 후보가 아닙니다.')
            record = candidate['record']
            if fingerprint(record)!=candidate['record_sha256'] or candidate['key']!=candidate['service']+':'+record['PRDLST_REPORT_NO']:
                raise Conflict('공식 기록 검증에 실패했습니다.')
            quote = record.get('PRIMARY_FNCLTY','') if candidate['service']=='I0030' else ''
            result['selected'] = dict(product_key=product_key, record=record, record_sha256=candidate['record_sha256'],
                quote=quote, evidence_availability='PRESENT' if quote.strip() else 'MISSING',
                source_field='PRIMARY_FNCLTY' if quote.strip() else None, source_url=candidate['source_url'],
                retrieved_at=candidate['retrieved_at'], selection_status='USER_SELECTED_NOT_INDEPENDENTLY_VERIFIED')
            # Old comparison snapshots must not reappear after a product change.
            conn.execute("DELETE FROM jobs WHERE owner_hash=%s AND payload->>'parent_id'=%s", (owner,str(job_id)))
            return conn.execute('UPDATE jobs SET result=%s,updated_at=now() WHERE id=%s RETURNING *', (Jsonb(result),job_id)).fetchone()

    def remove(self, owner, job_id):
        with self.connect() as conn:
            if not conn.execute('SELECT 1 FROM jobs WHERE id=%s AND owner_hash=%s FOR UPDATE', (job_id,owner)).fetchone():
                raise KeyError()
            conn.execute("DELETE FROM jobs WHERE owner_hash=%s AND (id=%s OR payload->>'parent_id'=%s)", (owner,job_id,str(job_id)))

    def cancel(self, owner, job_id):
        with self.connect() as conn:
            row = conn.execute("""UPDATE jobs SET status='CANCELLED',payload='{}',result=NULL,
                lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s AND owner_hash=%s
                AND expires_at>now() AND status IN ('QUEUED','RUNNING') RETURNING *""", (job_id,owner)).fetchone()
            if not row:
                raise Conflict('진행 중인 작업만 취소할 수 있습니다.')
            conn.execute('DELETE FROM job_images WHERE job_id=%s',(job_id,))
            return row

    def claim(self):
        with self.connect() as conn:
            conn.execute('DELETE FROM job_images WHERE expires_at<=now()')
            conn.execute('DELETE FROM jobs WHERE expires_at<=now()')
            conn.execute('DELETE FROM sessions WHERE expires_at<=now()')
            conn.execute("DELETE FROM call_budget WHERE reserved_at<now()-interval '24 hours'")
            # No automatic re-execution of an uncertain billable call after a crash.
            conn.execute("""UPDATE jobs SET status='FAILED',error_code='WORKER_INTERRUPTED',
                lease_token=NULL,lease_until=NULL,updated_at=now()
                WHERE status='RUNNING' AND lease_until<=now()""")
            row = conn.execute("SELECT id FROM jobs WHERE status='QUEUED' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if not row:
                return None
            return conn.execute("""UPDATE jobs SET status='RUNNING',attempts=attempts+1,lease_token=%s,
                lease_until=now()+interval '2 minutes',updated_at=now() WHERE id=%s RETURNING *""", (uuid4(),row['id'])).fetchone()

    def finish(self, job_id, lease, result=None, error=None):
        with self.connect() as conn:
            return conn.execute("""UPDATE jobs SET status=%s,result=%s,error_code=%s,lease_token=NULL,
                lease_until=NULL,updated_at=now() WHERE id=%s AND lease_token=%s AND status='RUNNING'
                AND lease_until>now() AND expires_at>now() RETURNING id""",
                ('FAILED' if error else 'SUCCEEDED',Jsonb(result) if result is not None else None,error,job_id,lease)).fetchone() is not None


def public_job(row):
    result = json.loads(json.dumps(row['result'])) if row['result'] is not None else None
    if row['kind']=='SEARCH' and result:
        for c in result['candidates']:
            c.pop('record',None)
    return dict(id=str(row['id']),kind=row['kind'],status=row['status'],result=result,error_code=row['error_code'],
                created_at=row['created_at'].isoformat(),expires_at=row['expires_at'].isoformat(),
                parent_id=row['payload'].get('parent_id'),
                comparison_input={'claims':row['payload'].get('claims',[])} if row['kind']=='COMPARE' else None,
                search_input={k:row['payload'][k] for k in ('name','number','manufacturer','service','reviewed_claims')
                              if k in row['payload']} if row['kind']=='SEARCH' else None)