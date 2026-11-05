# 개발 가이드

## 준비

- Windows PowerShell, Git, Docker Desktop (Linux containers)
- Node.js 24 LTS / npm (Next.js 요구 범위: Node.js 20.9 이상)
- Python 3.12 이상 / uv (로컬 검증은 Python 3.13 사용)
- 공식 검색: 식품안전나라 Open API 사용 권한
- 실제 AI 비교: 팀 Gateway 사용 권한 및 키

키 없이도 합성 경계 통합 테스트를 실행할 수 있지만 PostgreSQL은 필요합니다. 공식 검색과 실제 AI 시험은 별도 자격 증명이 필요합니다. Windows 외 운영체제의 통합 시작 스크립트는 제공하지 않습니다.

아래 명령은 별도 설명이 없으면 저장소 루트에서 실행합니다.

## 환경 변수

최초 한 번만 `.env.example`을 `.env`로 복사합니다. `.env`는 Git 제외 대상이며 화면 캡처·로그에도 노출하지 않습니다.

| 변수 | 설정 |
| --- | --- |
| `POSTGRES_PASSWORD` | 직접 생성한 강한 DB 암호 |
| `DATABASE_URL` | `postgresql://gyeot:<URL 인코딩된 암호>@127.0.0.1:55432/gyeot` 형식 |
| `FOOD_API_KEY` | 식품안전나라 API 키 |
| `AI_GATEWAY_API_KEY` | 팀 Gateway 키 |
| `AI_GATEWAY_MODEL` | 접근 가능한 모델 별칭. 현재 기본값 `claude-sonnet` |
| `WEB_ORIGIN` | `http://localhost:3000` |
| `COOKIE_SECURE` | 로컬 HTTP는 `false`; 공개 HTTPS 배포 시 별도 검증 필요 |

`DATABASE_URL`은 예시 문자열 그대로 사용하지 말고 실제 값으로 설정합니다. 쉘 환경 변수가 `.env`보다 우선합니다. 키를 `NEXT_PUBLIC_*`에 넣지 마세요. 기존 DB 볼륨 생성 후 `.env`의 암호만 바꾸면 DB 내부 암호는 자동 변경되지 않습니다.

## 설치 및 시작

```powershell
Push-Location apps/api
uv sync --locked
Pop-Location
Push-Location apps/web
npm ci
npm run build
Pop-Location
& ./scripts/start.ps1
```

시작 스크립트는 DB·OCR 컨테이너, SQL 마이그레이션, API·워커·웹을 준비합니다. 웹 빌드는 미리 해야 합니다. 이미 포트를 사용 중이거나 이전 PID가 실행 중이면 중복 시작을 거부합니다. PID 재사용 가능성이 있으므로 프로세스를 종료하기 전 실제 실행 경로·명령을 확인하세요.

| 서비스 | 로컬 주소 |
| --- | --- |
| 웹 | `http://localhost:3000` |
| API | `http://127.0.0.1:8766` |
| PostgreSQL | `127.0.0.1:55432` |
| OCR | `http://127.0.0.1:8767` |

브라우저는 `localhost`로 접속합니다. 다른 호스트 이름은 Origin 검사와 맞지 않습니다. 로그·프로세스 정보는 `private/runtime/`에 생성됩니다.

### 개별 실행

```powershell
docker compose up -d --build --wait db ocr
# apps/api 폴더에서, 각각 별도 터미널
uv run python -m gyeot.migrate
uv run uvicorn gyeot.app:app --host 127.0.0.1 --port 8766 --no-access-log
uv run python -m gyeot.worker
# apps/web 폴더에서
npm run dev
```

운영 빌드 확인은 `npm run build` 후 `npm start`를 사용합니다. DB·OCR만 Docker로 실행하며 웹/API/워커는 호스트 프로세스입니다.

## 테스트

```powershell
docker compose up -d --wait db
Push-Location apps/api
uv run pytest -q
Pop-Location
Push-Location apps/web
npm run build
npm run typecheck
Pop-Location
python scripts/check_repository.py
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/check_secrets.py
```

빌드를 먼저 하면 Next.js가 생성하는 타입 파일도 준비됩니다. API 테스트는 임의 PostgreSQL 스키마를 만들고 종료 시 해당 스키마만 정리합니다. 앱 테이블을 비우지 않으며 DB 연결 실패를 성공으로 건너뛰지 않습니다.

브라우저 스크립트는 기존 Playwright 설치를 사용합니다. 현재 앱의 의존성에 포함되어 있지 않으므로 설치된 `playwright` 모듈의 절대 경로를 `PLAYWRIGHT_MODULE`로 지정하거나 Node 모듈 탐색 경로에서 찾을 수 있어야 합니다. 필요하면 설치된 Chromium 실행 파일을 `PLAYWRIGHT_BROWSER`로 지정합니다. 두 변수는 로컬 설정이며 개인 PC 경로를 커밋하지 않습니다. 검증별 호출 비용과 조건은 [VALIDATION.md](VALIDATION.md)를 확인하세요.

## 종료와 데이터 보존

- 터미널에서 직접 실행한 프로세스는 해당 터미널에서 종료합니다.
- 시작 스크립트로 실행한 경우 `private/runtime/processes.json`과 실제 프로세스 명령을 대조한 뒤 본인의 API·워커·웹만 종료합니다.
- 컨테이너는 `docker compose stop`으로 중지합니다.
- **`docker compose down -v`는 DB 데이터를 삭제하므로 일반 종료에 사용하지 않습니다.**

Git 제외는 OneDrive 같은 동기화 도구의 제외 설정이 아닙니다. `.env`, 로컬 DB 백업, 연구자료의 동기화는 별도로 관리하세요.