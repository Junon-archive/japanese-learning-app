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
-   `context_stage` 전이(`07_SRS_SPEC.md`의 `전이 규칙`): 무신호/`애매함`/
    `알고 있었음` exposure는 한 칸 올리고 explicit `몰랐음`은 한 칸 내린다.
    `anchor`에서의 `몰랐음`은 `anchor`에 머물고 `new_context`에서의 성공은
    `new_context`에 머문다. 낮은 stage의 presentation이 이미 진행한 stage를
    끌어내리지 않는다(`max`/`min`)
-   explicit review 기록이 `deferred_until`을 `NULL`로 지운다
    (`07_SRS_SPEC.md`의 `deferral 해제`)
-   client 발급 `client_event_id`는 **UUIDv4만** 통과한다. v5(=server 발급
    형식)·v1·v7을 body에 넣으면 422이고 event가 기록되지 않는다
    (`05_API_SPEC.md`의 `키 공간 분리`)
-   structured output parsing: 요청이 보내지 않은 `item_ref`가 응답에 오면
    그 문장이 `unknown_item_ref`로 탈락한다 (`08_LLM_SPEC.md`)
-   validation 9번의 범위: **target이 아닌** tappable item의 explanation이
    비어 있으면 그 문장이 `missing_explanation`으로 탈락한다
    (`08_LLM_SPEC.md`의 `Ready invariant와 같은 범위`)
-   `normalized_hash`: 전각/반각·공백만 다른 두 문장이 같은 해시를 내고,
    seed loader와 generation 경로가 **같은 함수**로 같은 값을 만든다
-   duplicate corpus에 `quarantined`가 포함된다(`08_LLM_SPEC.md`의
    `duplicate 비교 corpus`): 격리된 문장과 같은 문장을 생성하면
    `duplicate_hash`로 탈락한다. **탈락이 corpus 비교(11번)에서 났다는 것까지
    단정한다** --- `jobs/persistence`의 저장 직전 hash 대조가 같은 사유 코드를
    내고 그것은 `sentences.status`를 보지 않으므로, 사유 코드만 보면 corpus에서
    `quarantined`를 빼도 이 항목이 통과한다. 두 경로를 갈라 보려면 backstop 쪽
    탈락이 `detail`로 식별되어야 한다. 그 식별 수단이 없으면 이 규칙은
    **similarity(12번)로만** 관측된다 --- near-copy에는 persistence 대응물이
    없으므로 corpus만이 그것을 거부할 수 있다. `near_original`로 생성된 문장은
    similarity(12번)로 탈락하지 않는다
-   `failed`와 `dead_letter` 분기: active `prompt_versions` 행이 없으면 첫
    시도에서 `dead_letter`이고 `retry_count`가 늘지 않는다. provider
    timeout은 `retry`이며 소진하면 `failed`다
    (`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`)
-   daily ceiling 초과 시 job을 claim하지 않는다: job이 `queued`로 남고
    `retry_count`가 늘지 않으며 provider가 호출되지 않는다
-   `daily_token_limit`이 설정된 상태에서 오늘 token이 `null`인 job이 있으면
    한도 미달이어도 claim하지 않는다(fail-closed). `daily_request_limit`만
    설정된 경우에는 영향이 없다
    (`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`)

## Integration

FastAPI↔Postgres, session↔selection, event↔mastery/SRS, job↔worker↔pool,
Alembic from empty DB.

추가 필수 integration test:

-   Ready invariant: explanation이 없는 item을 포함한 문장은 candidate가
    `ready`가 되지 않는다.
-   API request handler 경로에서 provider client가 호출되지 않는다. 실제
    구현체 모듈과 provider SDK가 `sys.modules`에 적재되지도 않는다
    (ADR-015의 `정적과 런타임의 분담`). **"적재되지 않는다"를 in-process의
    절대 집합 검사로 확장하지 않는다** --- provider 구현체는 그것을 직접
    검사하는 테스트 모듈이 최상위에서 import하므로 full run에서는 수집
    시점에 이미 `sys.modules`에 있고, 절대 집합에 그 이름을 넣으면 모든 호출
    지점이 영구히 실패한다. in-process 쪽은 **블록 전후의 delta**("이 요청이
    `app.llm*`을 새로 적재했는가")로 관측하고, 문자 그대로의 요구는 **별도
    프로세스** 테스트가 검사한다(같은 절).
-   request 경로가 **worker loop와 job runner를 실행하지 않는다.** enqueue만
    일어나고 job 실행 진입점은 한 번도 불리지 않는다. 정적 guard(G12)가 검사할
    수 있는 것은 import까지이므로 "실제로 안 불렸다"는 이 테스트가 증명한다
    (ADR-015의 `정적과 런타임의 분담`).
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
-   server 발급 키를 client가 선점할 수 없다:
    `uuid5(NC_EVENT_NAMESPACE, "session_finished:{sid}")`를 `/extend` body로
    보내면 422이고, 이어진 `/finish`가 정상 200이며 idle timeout 뒤의
    `POST /api/study/session`도 정상 동작한다
    (`05_API_SPEC.md`의 `키 공간 분리`).
-   상태 게이트(`05_API_SPEC.md`의 `세션·presentation 상태 게이트`):
    `/finish` 뒤 그 session의 presentation에 대한 click /
    explanation-revealed / translation reveal / self-report / probe-response가
    **전부 409**이고, `UserMastery` 행이 생기지 않으며 `last_activity_at`이
    움직이지 않는다. 같은 presentation의 `/complete`는 200(기존 결과)이다.
-   `/flag`는 게이트의 예외다: 완료된 presentation에 flag하면 성공하고 그
    presentation의 `item_exposures`가 `invalidated_at`으로 무효화되며
    `meaningful_exposure_count`가 다시 계산된다. 닫힌 session에 flag해도
    그 session의 `last_activity_at`은 움직이지 않는다.
-   열린 session에서도 `/complete` 뒤의 self-report는 409다 --- 같은 노출이
    두 번 평가되지 않는다.
-   Demo isolation: demo API endpoint가 존재하지 않고, demo frontend
    fixture가 backend로 네트워크 요청을 하지 않는다.
-   contextual repetition이 실제로 진행한다: 같은 item을 연속 세션에서
    실패 없이 반복 제시하면 제시 문장이 `anchor` 한 문장에 고정되지 않고
    `context_stage`가 ladder를 따라 올라간다.
-   `context_repair`가 도달 가능하다: 높은 stage에서 explicit `몰랐음` →
    다음 materialization이 `context_repair` reason의 candidate를 만들고,
    그 노출이 일어난 뒤에는 더 만들지 않는다.
-   target이 아닌 item에 `몰랐음`을 주면 `new` pool이 생긴다: 그
    presentation은 그 item의 `item_exposures`를 만들지 않고,
    `anchor_sentence_id`가 그 문장으로 기록되며, 이어진 materialization이
    `presentation_role = new` candidate를 **같은 문장**으로 만든다.
-   stale `running` 회수: `started_at`을 `claim_lease_seconds` 이전으로
    되돌린 `running` job이 다음 worker loop에서 `retry`가 되고
    `retry_count`가 1 증가하며 다시 claim된다. 소진하면 `failed`다
    (`09_BACKGROUND_JOBS.md`의 `stale running 회수`).
-   claim이 중복 실행을 만들지 않는다: 같은 job을 두 번 claim하려 하면
    두 번째는 아무 job도 얻지 못한다(`FOR UPDATE SKIP LOCKED`).
-   heartbeat: worker loop 1회가 `worker_heartbeats`를 upsert하고
    `/api/health`가 `worker.status = ok`를 반환한다.
    `last_heartbeat_at`을 임계값 이전으로 되돌리면 `stale` +
    `status = degraded`이고, 행이 없으면 `unknown`이며 `degraded`가 아니다.
-   enqueue 트리거: explanation이 없는 문장만 가진 item으로
    materialization을 돌리면 `EXPLAIN_ITEM`이 누락된 `sentence_item`당 1건
    생기고, 같은 날 재실행이 중복 생성하지 않는다(idempotency key).
-   현재 `context_stage` 조건에 맞는 문장이 없으면
    `GENERATE_REVIEW_CONTEXT`가 `(item, stage)`당 1건 enqueue된다. 그 item에
    문장이 아예 없으면 대신 Pool Fallback 3단계의
    `GENERATE_SENTENCE_BATCH`가 enqueue된다.
-   `backend/tests/`의 test double provider를 worker loop에 주입해
    `GENERATE_SENTENCE_BATCH` job을 끝까지 실행하면 `sentences` / `sentence_items` / `sentence_item_spans` /
    `sentence_item_explanations`가 만들어지고, 이어진 materialization이 그
    문장으로 `status = ready` candidate를 만든다. 네트워크 호출은 0건이다.
-   같은 job을 두 번 실행해도(at-least-once) 문장이 두 벌 저장되지 않는다.
-   worker 진입점은 `LLM_PROVIDER`가 없거나 허용값이 아니면 부팅에
    실패한다. `LLM_PROVIDER = openai`인데 `LLM_API_KEY`가 없어도 실패한다.
    두 경우 모두 provider client를 만들지 않는다
    (`spec/04_SECURITY_AND_DATA.md`의 `LLM provider 자격증명 (MVP 확정)`).
-   job 완료 후 `result_ref.usage`가 채워지고, 그 합이 daily ceiling 판정에
    쓰인다. 판정 경계는 UTC 일이다.

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
-   그 presentation은 이 item의 `item_exposures`를 만들지 않고
    `context_stage`도 움직이지 않는다 (`07_SRS_SPEC.md`의
    `target item의 canonical 정의`).
-   `anchor_sentence_id`가 그 문장으로 기록되고, 이 item이 `new` pool에
    들어가 첫 `new` presentation이 **같은 문장**을 제시한다.

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
