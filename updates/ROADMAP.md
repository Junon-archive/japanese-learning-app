# ROADMAP

요청 목록과 상태. 상태 정의와 번호 규칙은 [README.md](README.md)를 따른다. 이 문서는 명세가 아니다.

## 요청 목록

| 번호 | 제목 | 우선순위 | 상태 | 관련 명세 | 커밋 |
|---|---|---|---|---|---|
| U-001 | [선택 홈, 로그인 진입, 말투와 화면 전환](done/U-001-ui-ux-overhaul/request.md) | 높음 | 완료 | `01_USER_FLOW`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | 명세 b1ea50d, 42548b7, 7178f41, 0b405c9 · 머지 5a95fc2, 7c3cab0, ec581a7 · 직접 f196c9a |
| U-002 | [README 재작성과 문서 계층](done/U-002-readme.md) | 높음 | 완료 | `README.md`, `AGENTS.md`, ADR-020 | 명세 b1ea50d · 문서 655f5b6 |
| U-003 | [후리가나 on/off](done/U-003-furigana.md) | 높음 | 완료 | `03_UI_UX_SPEC`, `04_DB_SPEC`, `05_API_SPEC`, `08_LLM_SPEC`, `14_CONFIGURATION` | 명세 b1ea50d, 7178f41, 78a3b38, 0b405c9 · 머지 8b89619, 82e9794, a55ce3a, ec581a7 |
| U-004 | [히라가나·가타카나 학습](done/U-004-kana-learning.md) | 높음 | 완료 | `00_SCOPE`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | 명세 b1ea50d, 7178f41, 78a3b38, 0b405c9 · 머지 db32fc7, 6b131ab |
| U-005 | [demo 확장과 방문자 진도 저장](done/U-005-demo-expansion.md) | 높음 | 완료 | `01_USER_FLOW`, `03_UI_UX_SPEC`, `spec/04_SECURITY_AND_DATA` | 명세 b1ea50d, 7178f41, 78a3b38, 0b405c9 · 머지 1305fc2 · 직접 526a48d |
| U-006 | [영어 학습 추가](U-006-english-learning.md) | 높음 | 배포 대기 | `spec/mvp-03-english/*`, `spec/00~06`, `spec/mvp-01-core/*` 거의 전부, ADR-023·024·025 | 명세 498884c, 8f4d0eb · 직접 f0ef10e, f27c1f4, 794228a, 7e6e04d, 0d0638b, 58daff5, 860268b, 90aba3f, 6f836ff, cc6b217, 98dca0d, 9a5bb50, 4f7b0d6 · 머지 86540a1, f2dc014, f6edb70, 766de3d, 10698b3, a90b660 · 문서 e236a0a |
| - | 비밀번호 규칙과 로그인 방식 | - | 검토 후 유지 | `03_UI_UX_SPEC`의 `Login`, `05_API_SPEC`의 `Authentication` | - |
| - | README 스크린샷 | - | 보류 | `README.md`(U-002) | - |

`관련 명세`의 번호 파일은 `spec/mvp-01-core/` 아래다.

`커밋`은 짧은 해시다. `명세`는 그 요청의 관련 명세에 닿는 명세 커밋, `머지`는 레인 머지 커밋,
`직접`은 레인 없이 main에 넣은 수정 커밋, `문서`는 명세가 아닌 문서 커밋이다.

## 결정 기록

-   **비밀번호 규칙과 로그인 방식:** 검토했고 바꾸지 않는다. 로그인 폼, 쿠키, 401 단일 문구,
    password 규칙(16 code point)은 그대로다. 회원가입·비밀번호 재설정·소셜 로그인은 계속 없다.
-   **계정 수(2026-10-01):** 계정을 하나로 제한하지 않는다. **소유자와 소수의 지인용**이다.
    계정은 CLI로만 만들고(회원가입 없음) 학습 기록은 계정별로 완전히 갈린다. 다만 **LLM 사용량
    한도는 전역이라 공유한다** --- 한도에 걸리면 모든 계정이 함께 멈춘다. 계정과 학습 대상
    언어는 **별개 축**이며 계정을 언어별로 나누지 않는다
    (`spec/mvp-01-core/04_DB_SPEC.md`의 `계정 수와 공유 범위`).
-   **README 스크린샷:** U-002에서 넣지 않는다. 나중에 넣을 자리로 이 행을 남긴다.
-   **앱 이름(U-006):** 영어가 더해져도 `Nihongo Context`를 바꾸지 않는다. 사용자 결정
    (2026-10-01). PWA manifest, 상단바, README, Workers 이름, 저장소 이름 전부 그대로다.
-   **외부 어휘 자료(U-006):** 원본을 저장소에 커밋하지 않는다. `data/wordlists/`는
    gitignore이고 커밋하는 것은 선별 결과·선별 스크립트·출처 표기다(ADR-024 결정 1).

## MVP-03 진행 순서 (U-006)

| Wave | 방식 | 내용 |
|---|---|---|
| 0 | 직렬, main | **(완료)** 외부 자료 확보, 결정 수집, ADR-023·024·025, `spec/mvp-03-english/` 신설, 기존 명세 제자리 수정, 요청서 U-006 |
| 1 | 직렬, main | **(완료)** DB migration(리네임·`language`·`seed_id`·제약)과 모델 |
| 2 | 직렬, main | **(완료)** 리네임 전파 --- 모델·API·LLM 스키마·seed 파일·프론트·테스트 |
| 3 | 병렬 레인 | **(완료)** `engine-lang` · `seed-infra` · `prompt-lang` |
| 4 | 직렬, main | **(완료)** 영어 seed 생성·선별·검수(**사용자 확인 필요**)와 `seed/en/*.yaml` 커밋 |
| 5 | 병렬 레인 | **(완료)** `home-route` · `demo-en` · `speech` |
| 6 | 직렬, main | **(진행 중)** 배포 절차 문서, README, 상태 갱신 |

-   Wave 3 머지 순서: `seed-infra` → `prompt-lang` → `engine-lang`
-   Wave 5 머지 순서: `home-route` → `demo-en` → `speech`
-   **Wave 1\~2는 쪼개지 않는다.** 리네임이 끝나기 전에 레인을 열면 모든 레인이 같은 파일에서
    충돌한다.
-   배포는 Wave 6 뒤에 사용자가 한다. 운영 적용 순서가 있다: schema migration →
    `backfill_seed_id` → prompt 등록 → 영어 seed 증분 적재 → config override 사본 재작성 →
    API·worker 재시작 → frontend 배포.

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
