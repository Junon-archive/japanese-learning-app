# ROADMAP

요청 목록과 상태. 상태 정의와 번호 규칙은 [README.md](README.md)를 따른다. 이 문서는 명세가 아니다.

## 요청 목록

| 번호 | 제목 | 우선순위 | 상태 | 관련 명세 | 커밋 |
|---|---|---|---|---|---|
| U-001 | [선택 홈, 로그인 진입, 말투와 화면 전환](U-001-ui-ux-overhaul/request.md) | 높음 | 결정됨 | `01_USER_FLOW`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | - |
| U-002 | [README 재작성과 문서 계층](U-002-readme.md) | 높음 | 결정됨 | `README.md`, `AGENTS.md`, ADR-020 | - |
| U-003 | [후리가나 on/off](U-003-furigana.md) | 높음 | 결정됨 | `03_UI_UX_SPEC`, `04_DB_SPEC`, `05_API_SPEC`, `08_LLM_SPEC`, `14_CONFIGURATION` | - |
| U-004 | [히라가나·가타카나 학습](U-004-kana-learning.md) | 높음 | 결정됨 | `00_SCOPE`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | - |
| U-005 | [demo 확장과 방문자 진도 저장](U-005-demo-expansion.md) | 높음 | 결정됨 | `01_USER_FLOW`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | - |
| - | 비밀번호 규칙과 로그인 방식 | - | 검토 후 유지 | `03_UI_UX_SPEC`의 `Login`, `05_API_SPEC`의 `Authentication` | - |
| - | README 스크린샷 | - | 보류 | `README.md`(U-002) | - |

`관련 명세`의 번호 파일은 `spec/mvp-01-core/` 아래다.

## 결정 기록

-   **비밀번호 규칙과 로그인 방식:** 검토했고 바꾸지 않는다. 로그인 폼, 쿠키, 401 단일 문구,
    password 규칙(16 code point)은 그대로다. 회원가입·비밀번호 재설정·소셜 로그인은 계속 없다.
-   **README 스크린샷:** U-002에서 넣지 않는다. 나중에 넣을 자리로 이 행을 남긴다.

## MVP-02 진행 순서

| Wave | 방식 | 내용 |
|---|---|---|
| 0 | 직렬, main | `updates/` 요청 관리 체계와 요청서 U-001~U-005 |
| 1 | 직렬, main | 참고 사이트 전환 관찰과 목업, ADR-021(후리가나)·ADR-022(선택 홈·격리), `spec/mvp-02-onboarding/` 신설과 기존 명세 수정 |
| 2 | 병렬 레인 | `shell`(U-001) · `furigana-be`(U-003) · `kana-core`(U-004) |
| 3 | 병렬 레인 | `furigana-fe`(U-003) · `demo`(U-005) · `kana-ui`(U-004) |
| 4 | 직렬, main | README 재작성(U-002), 배포 절차 문서, 요청 목록의 상태를 `배포 대기`로 갱신 |

-   Wave 2 머지 순서: `furigana-be` → `kana-core` → `shell`
-   Wave 3 머지 순서: `furigana-fe` → `demo` → `kana-ui`
-   배포는 Wave 4 뒤에 사용자가 한다. 사용자가 배포를 확인하면 `완료`로 바꾸고 요청서를 `done/`으로 옮긴다.

## 미룬 항목

MVP-01에서 다음 사이클로 미룬 항목은 [backlog.md](backlog.md).
