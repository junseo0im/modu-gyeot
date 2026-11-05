"""Validate, orient and re-encode uploads. Never preserve EXIF or original filenames."""
import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_SIDE = 8000


class InvalidImage(ValueError):
    pass


def normalize_image(raw: bytes, content_type: str):
    if not raw or len(raw)>MAX_BYTES:
        raise InvalidImage('사진은 5MB 이하로 보내 주세요.')
    expected = {'image/jpeg':'JPEG','image/png':'PNG'}.get(content_type)
    if not expected:
        raise InvalidImage('PNG 또는 JPEG 사진만 사용할 수 있어요.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format!=expected or getattr(im,'n_frames',1)!=1:
                    raise InvalidImage('사진 형식을 확인해 주세요. 움직이는 이미지는 지원하지 않아요.')
                w,h=im.size
                if w<32 or h<32 or w*h>MAX_PIXELS or max(w,h)>MAX_SIDE:
                    raise InvalidImage('가로·세로 32px 이상, 1,200만 화소 이하 사진을 사용해 주세요.')
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
                oriented=ImageOps.exif_transpose(im).convert('RGBA')
                background=Image.new('RGB',oriented.size,'white')
                background.paste(oriented,mask=oriented.getchannel('A'))
                # New image has no EXIF, ICC, comments or original metadata.
                out=io.BytesIO()
                background.save(out,format='PNG')
                data=out.getvalue()
                if len(data)>MAX_BYTES:
                    raise InvalidImage('처리한 사진이 너무 커요. 필요한 광고 영역만 잘라 다시 보내 주세요.')
                return dict(data=data,sha256=hashlib.sha256(data).hexdigest(),
                            width=background.width,height=background.height)
    except InvalidImage:
        raise
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise InvalidImage('사진을 읽지 못했어요. 다른 PNG 또는 JPEG 파일을 선택해 주세요.') from None