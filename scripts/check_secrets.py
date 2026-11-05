"""Check Git-visible text files against locally configured secrets, without printing them."""
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
secrets=[]
for line in (root/'.env').read_text(encoding='utf-8-sig').splitlines():
    key,sep,value=line.partition('=')
    if sep and key.strip() in {'POSTGRES_PASSWORD','DATABASE_URL','FOOD_API_KEY','AI_GATEWAY_API_KEY'} and len(value.strip())>=8:
        secrets.append(value.strip().strip('"\'').encode())
names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).split(b'\0')
count=0
for raw in names:
    if not raw:continue
    file=root/raw.decode('utf-8')
    if not file.is_file() or file.suffix=='.woff2':continue
    data=file.read_bytes();count+=1
    if any(secret in data for secret in secrets):
        raise SystemExit('FAILED: local secret detected in Git-visible file (content withheld)')
print(f'PASS: {count} Git-visible files checked against local secret values; values not displayed')