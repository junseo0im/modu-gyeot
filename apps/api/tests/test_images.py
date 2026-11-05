import io
from uuid import uuid4

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from gyeot.app import create_app
from gyeot.config import Config
from gyeot.images import normalize_image, InvalidImage, MAX_BYTES


def picture(fmt='PNG',size=(200,100)):
    out=io.BytesIO(); im=Image.new('RGB',size,'white')
    exif=Image.Exif();exif[270]='private metadata'
    im.save(out,format=fmt,exif=exif)
    return out.getvalue()


def test_metadata_removed_and_normalized():
    result=normalize_image(picture('JPEG'),'image/jpeg')
    assert result['data'].startswith(b'\x89PNG')
    with Image.open(io.BytesIO(result['data'])) as im:
        assert not im.getexif() and not im.info
        assert im.size==(200,100)


@pytest.mark.parametrize('raw,mime',[(b'broken','image/png'),(b'x'*(MAX_BYTES+1),'image/png'),
    (picture(),'image/jpeg'),(picture(size=(10,10)),'image/png'),(picture(),'image/svg+xml')])
def test_invalid_images_rejected(raw,mime):
    with pytest.raises(InvalidImage):normalize_image(raw,mime)


def test_animated_png_rejected():
    out=io.BytesIO(); first=Image.new('RGB',(64,64),'white');second=Image.new('RGB',(64,64),'black')
    first.save(out,format='PNG',save_all=True,append_images=[second],duration=100,loop=0)
    with pytest.raises(InvalidImage):normalize_image(out.getvalue(),'image/png')


def test_image_lifecycle_and_correction(store):
    image=normalize_image(picture(),'image/png')
    owner=store.owner(store.session());other=store.owner(store.session())
    payload=dict(image_sha256=image['sha256'],consent_local_processing=True)
    key=str(uuid4());job=store.enqueue(owner,key,'OCR',payload,image=image)
    assert store.enqueue(owner,key,'OCR',payload,image=image)['id']==job['id']
    assert bytes(store.image(owner,job['id'])['image_bytes'])==image['data']
    with pytest.raises(KeyError):store.image(other,job['id'])
    lease=store.claim()
    assert store.finish(job['id'],lease['lease_token'],dict(text='오독 원문',words=[],status='TEXT_EXTRACTED'))
    corrected=store.correct_ocr(owner,job['id'],'수정본')
    assert corrected['result']['text']=='오독 원문'
    assert corrected['result']['corrected_text']=='수정본'
    store.remove(owner,job['id'])
    with pytest.raises(KeyError):store.image(owner,job['id'])


def test_cancel_removes_image_and_fences_result(store):
    image=normalize_image(picture(),'image/png');owner=store.owner(store.session())
    job=store.enqueue(owner,str(uuid4()),'OCR',{'image_sha256':image['sha256']},image=image)
    lease=store.claim();store.cancel(owner,job['id'])
    with pytest.raises(KeyError):store.image(owner,job['id'])
    assert not store.finish(job['id'],lease['lease_token'],{'text':'late'})


def test_image_expiry_independent_of_text(store):
    image=normalize_image(picture(),'image/png');owner=store.owner(store.session())
    job=store.enqueue(owner,str(uuid4()),'OCR',{'image_sha256':image['sha256']},image=image)
    with store.connect() as conn:
        conn.execute("UPDATE job_images SET expires_at=now()-interval '1 second' WHERE job_id=%s",(job['id'],))
    with pytest.raises(KeyError):store.image(owner,job['id'])
    assert store.get(owner,job['id'])['status']=='QUEUED'
    store.claim()
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM job_images').fetchone()['n']==0


def test_http_upload_boundary_and_ownership(store):
    cfg=Config('unused');headers={'Origin':cfg.web_origin,'X-Gyeot-Request':'1'}
    with TestClient(create_app(cfg,store)) as a,TestClient(create_app(cfg,store)) as b:
        a.post('/v2/session',json={},headers=headers);b.post('/v2/session',json={},headers=headers)
        h=dict(headers,**{'Content-Type':'image/png','Idempotency-Key':str(uuid4())})
        assert a.post('/v2/jobs/ocr',content=picture(),headers=h).status_code==422
        h['X-Image-Consent']='confirmed'
        response=a.post('/v2/jobs/ocr',content=picture(),headers=h)
        assert response.status_code==202
        path='/v2/jobs/'+response.json()['id']
        assert a.get(path+'/image').status_code==200
        assert a.get(path+'/image').headers['cache-control']=='no-store'
        assert b.get(path+'/image').status_code==404
        assert a.post('/v2/jobs/ocr',content=b'x'*(MAX_BYTES+1),headers=h).status_code==413
        assert a.post('/v2/jobs/ocr',content=b'not-image',headers=h).status_code==422
        a.delete(path,headers=headers)
        assert a.get(path+'/image').status_code==404