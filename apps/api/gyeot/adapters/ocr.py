import hashlib
import json
from urllib.request import Request, build_opener
from urllib.error import URLError, HTTPError

from .connectivity import NoRedirect


def extract_text(image):
    # Fixed loopback only: no arbitrary URL, shell argument or external model input.
    request=Request('http://127.0.0.1:8767/ocr',data=image,method='POST',headers={'Content-Type':'image/png'})
    try:
        with build_opener(NoRedirect).open(request,timeout=55) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError()
        result=json.loads(raw)
        if (not isinstance(result,dict) or result.get('image_sha256')!=hashlib.sha256(image).hexdigest()
                or result.get('status') not in ('TEXT_EXTRACTED','NO_TEXT')
                or not isinstance(result.get('text'),str) or len(result['text'])>20000
                or not isinstance(result.get('words'),list) or len(result['words'])>2000):
            raise ValueError()
        for word in result['words']:
            if not isinstance(word,dict) or not isinstance(word.get('text'),str):raise ValueError()
            if any(type(word.get(k)) is not int or word[k]<0 for k in ('x','y','width','height')):raise ValueError()
        return result
    except (URLError,HTTPError,TimeoutError,OSError,ValueError):
        raise ValueError('OCR_UNAVAILABLE_OR_INVALID') from None