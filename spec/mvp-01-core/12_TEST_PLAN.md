# Test Plan

## Unit

no-click rule, policy ratios/config, mastery signals, exposure count,
FSRS wrapper, validation, duplicate, auth.

추가 필수 unit test:

-   mastery EMA 갱신 (NULL 초기값 포함)
-   explicit signal → FSRS rating mapping
-   no-signal review가 FSRS memory state를 변경하지 않고
    `deferred_until`만 설정
-   category mix deficit 계산 (15문장처럼 나누어떨어지지 않는 경우 포함)
-   review ordering tie-break의 결정성
-   exposure 중복 집계 금지 (같은 presentation + 같은 item = 1회)
-   span code point offset 검증과 overlap 거부
-   job idempotency key 중복 삽입 방지
-   password 하한 미만이면 계정 생성이 실패하고, 하한 이상이면
    성공한다 (`spec/04_SECURITY_AND_DATA.md`의
    `Password 요구사항 (MVP 확정)`)
-   무신호 판정: `item_clicked`만 있는 review presentation과
    `mastery_probe_skipped`만 있는 review presentation이 **둘 다
    무신호로 처리되어** `deferred_until`이 설정된다
    (`07_SRS_SPEC.md`의 `No-signal review`)
-   무신호 판정이 (presentation, item) 쌍 단위다: target 2개 중 하나만
    self-report를 받으면 나머지 하나만 defer된다
-   probe pacing: `probe_min_gap_presentations` 미만 간격이면 probe를
    싣지 않고, `mastery_probe_target_per_session_max`에 도달하면 더 싣지
    않는다. 후보가 없어 `..._min`에 못 미치는 것은 실패가 아니다
-   server 발급 `client_event_id`가 결정론적이다: 같은 자연키로
    `uuid5`를 두 번 계산하면 같은 값이 나온다
    (`05_API_SPEC.md`의 `event idempotency key`)

## Integration

FastAPI↔Postgres, session↔selection, event↔mastery/SRS, job↔worker↔pool,
Alembic from empty DB.

추가 필수 integration test:

-   Ready invariant: explanation이 없는 item을 포함한 문장은 candidate가
    `ready`가 되지 않는다.
-   API request handler 경로에서 provider client가 호출되지 않는다.
-   flag → quarantine → 이후 selection 제외.
-   login 실패 응답이 사유와 무관하게 동일하다 (없는 `login_id` /
    틀린 password / 비활성 계정 → 같은 401, 본문 구분 없음).
-   seed 상태의 신규 사용자가 첫 세션을 시작할 수 있다. 구체적으로
    `POST /api/study/session`이 `Candidate Materialization`을 실행해
    seed 콘텐츠에서 `status = ready` candidate를 만들고, 이어진 `/next`가
    presentation을 반환한다. **candidate row를 손으로 INSERT하지 않는다**
    (`06_LEARNING_ENGINE.md`의 `테스트에서의 candidate 구성`).
-   materialization 재실행이 같은 candidate를 중복 생성하지 않는다
    (`04_DB_SPEC.md`의 partial unique index).
-   `/next` 재시도가 presentation을 중복 생성하지 않는다
    (`05_API_SPEC.md`의 `열린 presentation 불변식`).
-   `/complete` 재호출이 `sentence_completed`와 `item_exposures`를 중복
    생성하지 않는다.
-   `probe-response`가 다른 presentation의 `probe_id`를 받으면 400이고,
    같은 `probe_id`에 두 번 응답하면 첫 응답 결과가 유지된다.
-   Demo isolation: demo API endpoint가 존재하지 않고, demo frontend
    fixture가 backend로 네트워크 요청을 하지 않는다.

## Core E2E Scenario

1.  신규 사용자/테스트 사용자 생성 (seed 기반 cold start). 세션 시작이
    Ready Pool을 만든다(`06_LEARNING_ENGINE.md`의
    `Candidate Materialization`). Wave 3 worker 없이 성립한다.
2.  `任せる`가 포함된 문장 노출
3.  item 클릭
4.  precomputed 설명 표시 (live LLM 호출 0)
5.  `몰랐음` 선택
6.  event 저장
7.  mastery(observation 0.0, EMA) / review state(Again) 생성
8.  `item_exposures` 1건 생성
9.  due 시점으로 테스트 clock 이동
10. review 문장 노출
11. exposure 누적
12. 초기 원문(anchor) 후 새로운 문맥(new_context)으로 재노출
13. 최소 5회 노출 이후에도 FSRS due라면 계속 복습 가능

## Regression Scenarios

다음은 반드시 회귀 테스트로 유지한다.

### Scenario A --- due 20개 / 12분 세션

-   일부만 표시된다.
-   미표시 due는 **failure/lapse로 처리되지 않는다.**
-   due 상태와 `next_review_at`이 그대로 유지된다.

### Scenario B --- passive exposure 5회, explicit signal 0

-   mastery가 Known으로 상승하지 않는다.
-   같은 세션에서 무한 due 반복이 없다(`deferred_until`).
-   `passive_exposures_before_probe` 이후 probe 우선순위가 상승한다.

### Scenario C --- 첫 exposure에서 `알고 있었음`

-   FSRS rating은 Good.
-   mastery에 explicit evidence(observation 0.8)가 반영된다.
-   exposure \< 5이므로 `reinforcement` 노출이 계속 가능하다.
-   FSRS interval을 억지로 cap하지 않는다.

### Scenario D --- new context에서 실패

-   `몰랐음`이면 Again evidence를 기록한다.
-   다음 context는 `context_repair`로 한 단계 쉬워질 수 있다.
-   해당 문장이 flag되면 파생된 failure evidence를 무효화할 수 있다.

### Scenario E --- New Ready Pool 비어 있음

-   다른 available category 또는 reinforcement로 진행한다.
-   **synchronous LLM 호출이 없다.**
-   replenishment job이 enqueue된다.

### Scenario F --- target 외 unknown incidental expression 클릭

-   click만으로 SRS에 등록되지 않는다.
-   `몰랐음`/`애매함` explicit 입력 시 learning state가 활성화된다.
-   `알고 있었음`이면 신규 item으로 강제 등록되지 않는다.

### Scenario G --- probe 계속 skip

-   mastery 변화가 없다.
-   같은 item을 즉시 다시 묻지 않는다.
-   `probe_skip_cooldown_days`가 적용된다.

### Scenario H --- 사용자가 `unnatural` flag

-   candidate/sentence가 quarantined된다.
-   향후 selection에서 제외된다.
-   해당 content에서 파생된 negative mastery evidence를 무효화할 수
    있다(`item_exposures.invalidated_at`).

## Demo E2E

-   anonymous visitor가 로그인 없이 demo를 시작할 수 있다.
-   설명 / 번역 / probe / contextual review를 체험할 수 있다.
-   private user data가 노출되지 않는다.
-   LLM paid call이 발생하지 않는다.
-   demo 화면이 backend로 네트워크 요청을 하지 않는다(static fixture).

## Golden Regression

장기적으로 약 100개 sample로
naturalness/correctness/difficulty/explanation/register를 회귀 검토.
별도 LLM judge는 필수 아님.

이 golden eval harness는 **MVP 구현 의무가 아니다**
(`spec/06_LLM_ENGINEERING_PRINCIPLES.md`의 MVP 구현 의무 범위).
