"""Private loopback OCR sidecar. No cloud calls or persistent image storage."""
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CAP=5*1024*1024
gate=threading.BoundedSemaphore(1)


def recognize(data):
    with tempfile.TemporaryDirectory(prefix='ocr-') as temp:
        source=Path(temp)/'input.png'
        source.write_bytes(data)
        # Files, not pipes, bound parent memory consumption. /tmp is a limited tmpfs.
        with (Path(temp)/'out.tsv').open('wb') as output:
            run=subprocess.run(['tesseract',str(source),'stdout','-l','kor+eng','--psm','6','tsv'],
                stdout=output,stderr=subprocess.DEVNULL,timeout=45,check=False,
                env=dict(os.environ,OMP_THREAD_LIMIT='1'))
        if run.returncode!=0:
            raise ValueError('OCR_FAILED')
        path=Path(temp)/'out.tsv'
        if path.stat().st_size>2_000_000:
            raise ValueError('OCR_OUTPUT_TOO_LARGE')
        words=[];lines={};characters=0
        for row in csv.DictReader(io.StringIO(path.read_text(encoding='utf-8')),delimiter='\t'):
            text=(row.get('text') or '').strip()
            if row.get('level')!='5' or not text:
                continue
            characters+=len(text)
            if len(words)>=2000 or characters>16000:
                raise ValueError('OCR_OUTPUT_TOO_LARGE')
            key=tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
            line_id='-'.join(key)
            word=dict(text=text,confidence=float(row['conf']),line_id=line_id,
                x=int(row['left']),y=int(row['top']),width=int(row['width']),height=int(row['height']))
            words.append(word);lines.setdefault(line_id,[]).append(text)
        text='\n'.join(' '.join(items) for items in lines.values())
        return dict(status='TEXT_EXTRACTED' if words else 'NO_TEXT',text=text,words=words,
                    engine='tesseract',languages='kor+eng',psm=6,
                    image_sha256=hashlib.sha256(data).hexdigest(),
                    note='OCR confidence is an engine score, not verified accuracy.')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def send_json(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

    def do_GET(self):
        if self.path!='/health':return self.send_json(404,{'error':'NOT_FOUND'})
        self.send_json(200,{'status':'ok','engine':'tesseract','languages':['kor','eng']})

    def do_POST(self):
        if self.path!='/ocr':return self.send_json(404,{'error':'NOT_FOUND'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.send_json(400,{'error':'INVALID_LENGTH'})
        if not 0<length<=CAP or self.headers.get('Content-Type')!='image/png':
            return self.send_json(413,{'error':'INVALID_IMAGE'})
        if not gate.acquire(blocking=False):return self.send_json(429,{'error':'OCR_BUSY'})
        try:
            self.connection.settimeout(10)
            data=self.rfile.read(length)
            if len(data)!=length or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                return self.send_json(400,{'error':'INVALID_IMAGE'})
            self.send_json(200,recognize(data))
        except subprocess.TimeoutExpired:self.send_json(504,{'error':'OCR_TIMEOUT'})
        except (OSError,ValueError,KeyError):self.send_json(422,{'error':'OCR_FAILED'})
        finally:gate.release()


if __name__=='__main__':
    ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()