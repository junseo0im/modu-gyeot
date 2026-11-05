# 기여 및 작업 규칙

## 변경 범위

- 기능·버그 수정·문서 정리를 가능한 한 분리합니다.
- 현재의 `apps/web`, `apps/api`, `services/ocr` 경계를 유지합니다.
- 사용자 데이터·외부 호출·보관 정책 변경은 코드뿐 아니라 문서·테스트에도 반영합니다.
- 기존 의존성·코드 스타일을 우선합니다. 포매터/린터 도입과 전체 재포맷은 별도 변경으로 진행합니다.

## 브랜치 및 커밋

`main`을 기준으로 `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `chore/<topic>` 브랜치를 사용합니다. 이는 협업 규칙이며 원격 브랜치 보호가 설정됐다는 뜻은 아닙니다.

Conventional Commits 형태를 사용합니다.

```text
<type>(<scope>): <변경 요약>
```

- type: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `build`, `ci`
- scope: `web`, `api`, `ocr`, `repo`, `docs` 등 변경 영역
- 요약은 한국어 또는 영어로 구체적으로 작성하고, 비밀값·개인정보를 포함하지 않습니다.
- 호환성을 깨는 변경은 `!` 및 본문의 `BREAKING CHANGE:`로 명시합니다.

예: `fix(web): 비교 기록의 수정 문구 복원`, `docs(repo): 프로젝트 소개와 실행 가이드 정리`.

## 파일·코드 규칙

- UTF-8, LF, 파일 끝 개행. 공백 들여쓰기를 사용합니다.
- Python은 4칸·snake_case, React 컴포넌트는 PascalCase, TypeScript 함수·변수는 camelCase를 기본으로 합니다.
- 웹 코드는 기존 2칸 들여쓰기와 작은따옴표 스타일을 따릅니다. 기존 압축된 JSX를 무관한 기능 변경에서 전면 정리하지 않습니다.
- 문서는 한국어 설명과 원래 API/기술 명칭을 사용합니다. 내부 대화 기록 대신 현재 동작·재현 절차를 적습니다.
- DB 마이그레이션은 `NNN_description.sql`로 추가합니다. 적용된 파일은 해시 검증되므로 수정하지 않습니다.
- `uv.lock`, `package-lock.json`을 함께 관리하고 설치는 `uv sync --locked`, `npm ci`를 사용합니다.
- `next-env.d.ts`, 빌드 결과, 로컬 설정은 생성물로 취급합니다.

## PR 전 확인

1. [개발 가이드](docs/DEVELOPMENT.md)의 관련 테스트·빌드 실행.
2. `python scripts/check_repository.py`와 `python scripts/check_secrets.py` 실행.
3. 추가할 파일과 diff를 직접 검토. 자동 검사는 모든 비밀이나 권리 문제를 찾아내지 못합니다.
4. PR에 변경 목적, 테스트 결과, 외부 호출·비용 여부, 남은 한계를 작성.

실제 AI 호출은 기본 테스트에 포함하지 않습니다. 합성 경계 테스트를 먼저 사용하고, 실제 호출은 권한·자료 이용 범위·비용을 확인한 뒤 명시적으로 실행합니다.

기여하는 자체 코드·문서는 프로젝트의 [MIT License](LICENSE)로 제공할 권한이 있어야 합니다. 외부 코드는 라이선스 호환성과 재배포 조건을 확인하고 원래 고지를 보존합니다. API 데이터·광고 원본의 이용 권한을 코드 라이선스로 대체하지 않습니다.