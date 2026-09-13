# U-002 README 재작성과 문서 계층

| 항목 | 값 |
|---|---|
| 번호 | U-002 |
| 제목 | README 재작성과 문서 계층 |
| 상태 | 결정됨 |
| 우선순위 | 높음 |
| 요청일 | 2026-09-13 |
| 관련 명세 | `README.md`, `AGENTS.md`, `docs/decisions/ADR-020-production-topology.md` |
| 커밋 | - |

---

## 1. 배경 --- 사용자 결정 (2026-09-13)

-   이 사이트의 방문자는 사용자의 포트폴리오에서 대표 빌드를 구경하러 오는 사람이다.
-   루트 README는 지금 명세 저장소 설명이다. 방문자와 개발자가 바로 이해하게 다시 쓴다.
-   MVP-02 명세가 새로 생기므로 문서 계층 설명도 바뀐다.

## 2. 원하는 것 --- 사용자 결정 (2026-09-13)

### README 성격

루트 README를 방문자 우선으로 다시 쓴다. 명세 저장소 설명은 개발자 절로 옮긴다.

### README 구성

-   한 줄 소개
-   바로 써보기
-   어떻게 공부하게 되나(흐름)
-   어떻게 돌아가나
    -   mermaid 구성도: 휴대폰 → Cloudflare(frontend) → API → PostgreSQL, worker → LLM provider
-   기술 스택
-   비용과 개인정보(방문자 데이터는 서버에 가지 않음)
-   개발자용: 로컬 실행, 테스트, 문서 지도, `updates/` 안내
-   로드맵 링크

### 공개 주소

-   공개 주소는 사이트 주소 1개, README에만 둔다(Wave 4).

### 문서 계층

-   `spec/mvp-02-onboarding/`를 새로 만든다. `00_SCOPE.md`(MVP-02 범위 delta)와 MVP-02용
    `12_TEST_PLAN.md`, `13_ACCEPTANCE_CRITERIA.md`를 둔다.
-   기존 `spec/mvp-01-core/*`와 `spec/00~04`는 제자리에서 수정하고 `spec/CHANGELOG.md`에 기록한다.
-   새 source of truth는 `mvp-01-core + mvp-02-onboarding delta`다. 이 사실을 `AGENTS.md`와
    루트 `README.md`의 문서 계층 설명에 반영한다.
-   `AGENTS.md`의 "MVP 구현 대상이 아님" 목록에서 형태소 분석기만 MVP-02로 해제한다(`U-003`).
    나머지 항목(audio/TTS 등)은 그대로 둔다.

## 3. 원하지 않는 것 --- 사용자 결정 (2026-09-13)

-   스크린샷은 넣지 않는다. 나중에 넣을 자리만 `ROADMAP.md`에 남긴다.
-   README에 싣지 않는 것
    -   API 호스트명
    -   외부 연결 경로의 이름과 그것을 돌리는 서비스 이름
    -   포트
    -   서버 경로
    -   IP
    -   계정 ID

## 4. 참고 --- 사용자 결정 (2026-09-13)

-   저장소는 공개 상태다.
-   요청 관리 체계는 `updates/README.md`.

## 5. 완료 확인 방법 --- 사용자 결정 (2026-09-13)

-   방문자와 개발자가 README를 읽고 바로 이해한다.
-   README가 위 구성을 모두 갖는다.
-   공개 주소는 README의 사이트 주소 1개뿐이다.
-   모든 커밋 파일에서 위의 금지 정보를 다시 점검한다(security-reviewer).
-   `AGENTS.md`와 README의 문서 계층 설명이 `mvp-01-core + mvp-02-onboarding delta`를 말한다.

정식 합격 기준은 Wave 1의 `spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md`다.

---

## 6. 영향 명세·충돌 --- Claude 작성

### 충돌

-   `docs/decisions/ADR-020-production-topology.md`의 결정 6(커밋되는 파일에는 실제 도메인을 쓰지
    않는다)과 충돌한다. → Wave 1에서 README의 사이트 주소 1개만 예외로 개정한다.
    (Wave 1 반영 예정)
-   ADR-020 결정 6이 개정되기 전이라 이 요청서에는 실제 주소를 적지 않는다.
-   `AGENTS.md`: "MVP 구현 source of truth는 `spec/mvp-01-core/*`다." 새 계층과 다르다.
    (Wave 1 반영 예정)
-   루트 `README.md`의 `문서 계층`, `우선순위`: source of truth가 `spec/mvp-01-core/*` 하나다.
    머리의 `Current Milestone: MVP-01 Core Learning`도 바뀐다. (문서 계층은 Wave 1, 전체 재작성은
    Wave 4 반영 예정)

### 영향

-   `spec/mvp-02-onboarding/` 신설: `00_SCOPE.md`, `12_TEST_PLAN.md`, `13_ACCEPTANCE_CRITERIA.md`.
    (Wave 1 반영 예정)
-   `.claude/agents/`의 여러 정의(`planner`, `scope-guard`, `spec-sync` 등)가 `spec/mvp-01-core/*`를
    유일한 source of truth로 적고 있다. Wave 1에서 `.claude/agents/`의 source of truth 표기를
    `mvp-01-core + mvp-02-onboarding delta`로 고친다. (Wave 1 반영 예정)
-   `spec/04_SECURITY_AND_DATA.md`: "`infra/`에 도메인을 고정하지 않는다." README는 `infra/`가
    아니므로 충돌은 아니다. `infra/DEPLOY.md`에는 계속 도메인을 쓰지 않는다.

## 7. 결정 필요 질문 --- Claude 작성

없음(확정).

## 8. 작업 계획 --- Claude 작성

| Wave | 레인 | 작업 |
|---|---|---|
| 1 | main | ADR-020 결정 6 예외 개정, `spec/mvp-02-onboarding/` 신설, `AGENTS.md` 문서 계층 갱신 |
| 4 | main | README 재작성, 커밋 파일 전체 공개 정보 점검(security-reviewer), `ROADMAP.md` 스크린샷 자리 유지 |
