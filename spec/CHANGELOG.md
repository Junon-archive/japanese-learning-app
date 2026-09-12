# Specification Changelog

## v0.2 --- 2026-09-11

v0.1 MVP 명세에 지금까지 논의한 장기 설계를 추가했다.

추가/보강: comprehensible-input 비율, multidimensional difficulty,
sentence 이해와 item mastery 분리, morphology/lemma, sense 확장,
register/recognize-only, 설명 언어 progression, topic coverage,
Busy/Deadline habit, real-source mix, minimal LLM context, prompt
caching, model routing, \~100 golden eval, duplicate evolution, 비용
지표, Admin/export, YouTube LearningValue/comprehension/rewatch,
configuration.

## v0.2 Corrective Patch --- 2026-09-11

v0.2 compression으로 소실된 implementation detail을 복원하고, 명세 리뷰에서
드러난 P0/P1 구멍을 현재 제품 결정에 맞춰 in-place로 보완했다. 새 버전
번호를 만들지 않았다.

주요 내용:

-   **소실 detail 복원**: meaningful exposure positive definition,
    LearningEvent type 목록, `learning_events`의 FK/context column,
    `review_states`의 user/item identity, `sentences`의
    status/difficulty/provenance 필드, `prompt_versions.active`,
    empty pool fallback 절차, retry 세부 규칙, E2E 단계별 시나리오.
-   **Audio/Listening**: MVP-01에서 audio 전면 제외. `listening_mastery`는
    nullable float, 초기값 NULL, MVP에서 갱신하지 않음.
-   **Mastery**: nullable float `[0.0, 1.0]` + explicit evidence
    (0.0/0.4/0.8) + configurable EMA. auxiliary signal은 mastery를 직접
    바꾸지 않음. `evidence_count` 정의 분리.
-   **FSRS / no-signal**: explicit signal → Again/Hard/Good mapping,
    `Easy` 미사용. 무신호 review는 rating을 추론하지 않고
    `deferred_until`로만 처리하여 무한 due loop를 제거.
-   **Exposure / Context model**: `item_exposures`를 canonical source로
    도입(presentation당 1회), `user_item_learning_state`로 context
    progression 추적. 최소 5회 보장은 FSRS interval을 왜곡하지 않고
    `reinforcement` 노출로 달성.
-   **Ready Pool**: `user_sentence_candidates` /
    `user_sentence_candidate_targets` / `study_presentations` 도입.
    사용자별 role을 global sentence에 저장하던 `sentence_items.role`
    (`incidental` 포함) 제거.
-   **Contextual explanation**: `sentence_item_explanations` 신설 +
    Ready invariant 정의(tap 시 live LLM fallback 금지).
-   **Span**: `sentence_item_spans` 신설, Unicode code point index 고정,
    불연속 표현 지원, API가 render segment list 반환.
-   **Demo / Auth**: Demo는 완전한 static frontend fixture(API/DB/provider
    경로 없음). auth는 seed 계정 + Argon2id + `auth_sessions` +
    동일 registrable domain + CORS/CSRF 규칙 확정.
-   **Cold start / selection**: starter seed set 요구, deficit 기반
    category mix, review ordering, backlog 정의, pool fallback 확정.
-   **LLM lifecycle**: 모든 provider 호출은 worker 전용,
    deterministic validation 12개 항목, sense correctness 한계 명시,
    job idempotency/retry 확정. `ANALYZE_SENTENCE`는 Future로 이동.
-   **API contract**: 실제 request/response schema 수준으로 보강.
    번역은 reveal 이후에만 반환.
-   **MVP/Future boundary**: 실험 수치를
    `future/EXPERIMENTAL_PARAMETERS.md`로 이동(삭제 아님), acceptance에서
    실험 숫자 제거, observability MVP 필수 범위 축소.

### 후속 보완 --- 2026-09-11 (구현 지시서 §6)

Wave 2 착수 전 미해결이던 명세 공백 2건을 권장안대로 확정했다. 새 버전
번호를 만들지 않고 corrective patch에 이어 붙인다.

-   **review reason 우선순위** (`06_LEARNING_ENGINE.md`,
    `Review Reason 선택`): review 슬롯이 선택된 뒤 reason을
    `context_repair > fsrs_due > reinforcement` 순으로 고른다. reason의
    사용 가능 여부는 Ready Pool의 `status = ready` candidate 유무로
    판단한다. `reinforcement`가 굶지 않도록 세션 내 review presentation
    수를 분모로 하는 `reinforcement_deficit`을 정의하고, 이 최소 지분은
    `fsrs_due`보다만 앞서고 `context_repair`는 넘지 않는다.
-   **exploration item 선정** (`06_LEARNING_ENGINE.md`,
    `Exploration Item 선정`): 후보 조건(mastery NULL /
    `is_active_learning_target = false` / 최근 미노출)과 정렬
    (difficulty distance → frequency_rank → `learning_item_id`)을 확정했다.
    "최근 노출" 판정 소스는 `item_exposures`(`invalidated_at IS NULL`)로
    고정하고 denormalized cache를 쓰지 않는다. 난이도 비교용 label
    ladder(`beginner < intermediate < advanced`)를 canonical로 정의했다.
    frequency 컬럼을 신설하지 않고 `metadata_json.frequency_rank` →
    seed 적재 순서로 고빈도를 정의했으며, generated item에는 빈도 정보가
    없다는 한계를 명시했다. cold start는 별도 분기 없이 같은 정렬로
    "seed 고빈도부터"가 되도록 했다.
-   **config**: `learning.reinforcement_min_share_of_review: 0.2`,
    `learning.exploration_recent_days: 14`를 `14_CONFIGURATION.md`에
    추가했다. 전자는 category 비율 합 검증 대상이 아니다.
-   **FSRS 라이브러리 바인딩** (`04_DB_SPEC.md` `review_states`,
    `07_SRS_SPEC.md`, ADR-003): 실제 배포명은 `py-fsrs`가 아니라 `fsrs`
    6.x이고 `Card`에 `reps`/`lapses`/`scheduled_days`가 없다는 사실에
    맞춰 스키마를 갱신했다. `scheduled_days` 제거(스케줄은 절대시각
    `next_review_at` = `Card.due`만 저장), `step` 추가(`state = Review`면
    NULL), `state` 열거값 명시(`1 = Learning | 2 = Review |
    3 = Relearning`), `last_review_at` ↔ `Card.last_review` 대응 명시,
    `Card.card_id` 미저장. `reps`/`lapses`는 유지하되 **애플리케이션이
    직접 유지하는 카운터**임을 명시했다(`lapses`는 `Again` 기록 시 증가,
    무신호 review는 둘 다 증가시키지 않음). 07에 Rating 열거값
    (`Again=1 / Hard=2 / Good=3 / Easy=4`, MVP는 1\~3만 사용)과 fuzzing
    비활성화를 추가했다. fuzzing off는 interval cap이 아니라 jitter
    제거이므로 최소 5회 노출 규칙과 충돌하지 않는다.
    `srs.fsrs_enable_fuzzing: false`를 `14_CONFIGURATION.md`에 추가했다.
-   **`/api/health` 응답 규약** (`05_API_SPEC.md`): 의존성 상태와 무관하게
    **항상 HTTP 200**을 반환하고 판정은 body `status`(`ok | degraded`)로
    한다. `checked_at` / `version` / `components.api|database|worker`를
    정의하고, `database`는 `ok | down | unknown`(+`latency_ms`),
    `worker`는 `unknown | ok | stale`(+`last_heartbeat_at`)로 고정했다.
    `unknown`은 degraded가 아니다. DB 오류 원문·DSN·credential은 응답에
    넣지 않는다. **worker heartbeat 저장 위치는 미결이며 Wave 3에서
    확정한다**(`09_BACKGROUND_JOBS.md`에 미결 절 추가, 선반영 금지).
-   **backlog 비율 검증** (`14_CONFIGURATION.md`, `06_LEARNING_ENGINE.md`):
    `backlog_review_ratio` / `backlog_new_ratio` /
    `backlog_exploration_ratio`도 합 1.0 검증 대상으로 명문화했다. backlog
    모드는 세 ratio를 세트로 통째로 교체하며 같은 deficit 계산에 그대로
    들어간다.
-   **배포 표면** (`spec/04_SECURITY_AND_DATA.md` Security,
    `05_API_SPEC.md` 공통 규칙): 인증 없이 열리는 endpoint는
    `GET /api/health` 하나뿐이며, FastAPI 자동 문서 경로
    (`/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect`)는 기본
    비활성이다. 환경 구분은 `APP_ENV`(`local | development | production`,
    기본 `local`) 환경변수로 하고 자동 문서는 `development`에서만 연다
    (fail-closed). `APP_ENV`는 배포 표면 제어 전용이며 학습 기능·정책을
    환경에 따라 분기시키지 않는다. 배포 설정이므로
    `14_CONFIGURATION.md`에 두지 않는다.
-   **seed frequency 참조**: `04_DB_SPEC.md`의 Seed Data 절에
    `metadata_json.frequency_rank` cross-reference를 1줄 추가했다.
    canonical 정의는 `06_LEARNING_ENGINE.md`에 둔다.

Wave 1(스키마 + 인증) 착수 중 드러난 명세 공백 6건을 같은 방식으로
확정했다. 새 버전 번호를 만들지 않는다.

-   **익명 접근 endpoint 서술의 자기모순 해소** (`05_API_SPEC.md`,
    `익명 접근 허용 목록`): "인증 없이 접근 가능한 endpoint는
    `GET /api/health` 하나뿐"이라는 문장이 같은 문서의
    `POST /api/auth/login`과 직접 모순이었다. 익명 호출 가능 endpoint는
    `GET /api/health`와 `POST /api/auth/login` **둘**이며, login은 인증의
    예외가 아니라 인증을 **생성하는** 진입점임을 명시했다. 그 밖의 모든
    endpoint(`logout`, `me` 포함)는 미인증 시 401이다. "학습 데이터를
    읽거나 쓰는 endpoint 중 익명 접근 가능한 것은 없다"를 별도 문장으로
    분리해 판정 기준을 해석 여지 없이 만들었다. 목록에 없는 경로가 익명
    접근을 허용하면 명세 위반(fail-closed). 자동 문서 경로는 이 목록과
    별개이며 `APP_ENV`로 제어한다.
-   **session cookie 규격 확정** (`spec/04_SECURITY_AND_DATA.md`,
    `Session Cookie (MVP 확정)`, ADR-004): `__Host-nc_session` /
    `HttpOnly; Secure; SameSite=Strict; Path=/` / `Domain` 미지정
    (host-only) / `Max-Age = AUTH_SESSION_TTL_DAYS`(env, 기본 30일).
    만료 판정의 canonical source는 `auth_sessions.expires_at`이고 cookie
    `Max-Age`는 브라우저 힌트다. absolute expiry만 쓰고 sliding session은
    두지 않는다. **수명 값은 `14_CONFIGURATION.md`의 학습 정책 YAML이
    아니라 `.env` 계열 환경변수다**(`APP_ENV`와 같은 취급). 이름·
    `SameSite`·`Secure`·`Domain`은 설정값이 아니며 환경별 스위치를 두지
    않는다. `Secure`는 항상 켠다(브라우저가 `http://localhost`를 secure
    context로 취급하므로 로컬 개발용 off 스위치가 불필요하고, `APP_ENV`를
    보안 하향에 쓰면 배포 표면 제어 전용 규칙과 충돌한다).
    `14_CONFIGURATION.md`에는 "여기 두지 않는다"는 참조 1건만 추가했다.
-   **exploration frequency fallback의 저장 위치 확정**
    (`06_LEARNING_ENGINE.md`, `seed_order (seed loader 규약)`): 2순위
    "seed 적재 순서"는 `learning_items.metadata_json.seed_order`(정수)다.
    seed loader가 `seed 파일명 오름차순 → 파일 내 행 순서`로 1부터 채운다.
    정렬은 `(0, frequency_rank) / (1, seed_order) / (2, 0)` tuple ASC로
    비교해 두 값을 같은 숫자 공간에서 섞지 않는다. **`learning_items.id`를
    쓰지 않는다** --- 쓰면 2단계가 3단계 tie-break와 같은 기준이 되어 3단
    규칙이 2단으로 붕괴하고, generated item이 사이에 id를 받으므로 id
    순서는 seed 파일 순서도 아니다. `seed_order`를 `frequency_rank`로
    승격시키지 않는다. 새 컬럼은 만들지 않았다.
-   **로그인 식별자 확정** (`04_DB_SPEC.md`, `users` / `login_id`):
    컬럼은 **하나**이고 이름은 `login_id`다(`email / login identifier`
    병기 제거, 별도 `email` 컬럼 없음). `NOT NULL` + `UNIQUE`,
    정규화는 앞뒤 공백 제거 후 ASCII lowercase, CHECK는
    `^[a-z0-9._+@-]{3,64}$`. **대소문자를 구분하지 않으며 정규화한 값만
    저장**한다(조회 시점 `lower()` 비교나 `citext`를 쓰지 않는다 --- UNIQUE가
    정규화 전 값에 걸리면 중복 계정이 생긴다). **이메일 형식은 강제하지
    않는다**: public signup이 없고 사용자가 1명이며 메일 발송 기능도 없어
    실익이 없다. 이메일을 쓰고 싶으면 위 형식에 그대로 들어간다.
-   **`generation_jobs.job_type` 허용값 확정** (`04_DB_SPEC.md`,
    `job_type 허용값`): `GENERATE_SENTENCE_BATCH` /
    `GENERATE_REVIEW_CONTEXT` / `EXPLAIN_ITEM` **3개뿐**이며 그대로
    migration CHECK에 들어간다. `08_LLM_SPEC.md`의 MVP task와 1:1이다.
    **pool replenishment는 job_type이 아니라** `GENERATE_SENTENCE_BATCH`를
    enqueue하는 트리거다. maintenance/cleanup은 MVP에 호출자가 없으므로
    넣지 않는다(`ANALYZE_SENTENCE`를 Future로 보낸 기준과 동일).
    `09_BACKGROUND_JOBS.md`의 5종 나열 문장을 canonical 참조로 교체했다.
-   **API id 표현 확정** (`05_API_SPEC.md` `ID 표현`, ADR-005): DB 정수
    PK는 **JSON number(정수)** 로 낸다. 예외는 client 생성
    `client_event_id`(UUID 문자열)뿐이다. `05_API_SPEC.md`의 JSON 예시
    (`presentation_id`, `sentence_id`, `sentence_item_id`,
    `learning_item_id`, `probe_id`)를 문자열 placeholder에서 정수로 모두
    교체했다. 한계(JS `Number.MAX_SAFE_INTEGER`)는 ADR-005에 기록했다.
    `probe_id`의 발급·저장 방식은 Wave 2에서 확정하되 같은 표현 규칙을
    따른다.

Wave 1 보안 검토에서 드러난 명세 공백 1건을 확정했다. 새 버전 번호를 만들지
않는다.

-   **온라인 무차별 대입 방어 확정** (`spec/04_SECURITY_AND_DATA.md`의
    `Password 요구사항 (MVP 확정)` / `온라인 무차별 대입 방어 (MVP 확정)`,
    ADR-006): `POST /api/auth/login`에 시도 횟수 제한·계정 잠금·실패 지연이
    전혀 없었고, 명세에도 그 요구가 없었다(구현이 명세를 어긴 것이 아니라
    명세가 비어 있었다). 방어를 **password 엔트로피 하한**으로 확정한다.
    최소 **16 code point**이며 **계정 생성 경로에서만** 검증하고
    `POST /api/auth/login`은 검증하지 않는다(하한 미만 password는 DB에
    존재할 수 없고, login에서 길이를 먼저 보면 실패 응답 시간이 갈린다).
    복잡도 혼용 규칙·금지어 목록·유출 password 조회·최대 길이는 두지 않는다.
    최소 길이는 학습 정책 YAML에도 `.env`에도 두지 않고 **코드에
    고정**한다(보안 하한을 낮추는 스위치를 만들지 않는다 --- `Secure`
    플래그와 같은 판단, ADR-004). **애플리케이션 레벨 rate limit·계정
    잠금·실패 지연은 MVP에 두지 않는다**: 계정이 하나뿐이라 잠금은 곧 주인에
    대한 DoS이고, DB 실패 카운터는 인증 전 write 경로를 열며, in-process
    카운터는 worker 수에 따라 한도가 달라지고, Redis는 MVP에서 쓰지
    않는다(ADR-001). 부족한 것은 시도 속도(Argon2id 약 39ms → 약 25회/초)가
    아니라 탐색 공간이기 때문이다. 배포 계층(Cloudflare) rate limit은
    권장하되 **운영자 책임**이며 이 명세는 켜져 있다고 가정하지 않는다 ---
    설정하지 않으면 남는 방어가 password 하한과 Argon2id 비용뿐이라는 사실을
    명세에 명시했다. `require_trusted_origin`은 브라우저 CSRF만 막으므로 이
    방어에 포함되지 않는다는 문장을 추가했다. 로그인 실패 로그·알림은
    Future다(실패마다 로그를 남기면 공격 중 로그가 디스크 압박이 된다).
    교차 참조만 추가한 문서: `04_DB_SPEC.md`(실패 카운터 컬럼 금지),
    `05_API_SPEC.md`(실패 시 동일 401, **429 없음**),
    `14_CONFIGURATION.md`(여기 두지 않는다), `11_OBSERVABILITY.md`(실패 로그
    Future), `13_ACCEPTANCE_CRITERIA.md`(수치 없는 기준 1줄),
    `12_TEST_PLAN.md`(unit 1건 + integration 1건).
-   **수용된 위험 기록** (`spec/04_SECURITY_AND_DATA.md`의
    `수용된 위험 --- login endpoint의 메모리 비용`): 익명
    `POST /api/auth/login`이 요청당 Argon2id 메모리(기본 `m=65536` =
    64MiB)를 잡아 동시 요청만으로 자원 고갈을 유발할 수 있다. 사용자
    1명이고 피해가 가용성에 한정되므로 MVP는 방어하지 않고 받아들인다.
    **Argon2 파라미터를 낮추는 방식으로 대응하지 않는다**(password hash
    강도는 1차 방어의 축이다). 완화가 필요해지면 배포 계층이 먼저다. 기록일
    뿐 새 요구사항·테이블·설정 키를 만들지 않았다.

Wave 2(Learning Engine + SRS) 계획에서 드러난 **차단성 명세 공백 5건**을
확정했다. 새 버전 번호를 만들지 않는다. MVP 범위는 넓히지 않았고 새
테이블도 만들지 않았다.

-   **[P-1] Ready Pool을 누가 만드는가** (`06_LEARNING_ENGINE.md`의
    `Candidate Materialization`이 canonical, ADR-010): seed 적재는 global
    content만 만들고 `user_sentence_candidates`를 만들지 않는데, Ready
    Pool의 실체가 그 테이블이라 **pool을 채우는 주체가 명세에 없었다.**
    `user_sentence_candidates` row는 **Wave 2의 Learning Engine이 request
    경로에서 직접 만든다.** 실행 시점은 `POST /api/study/session`(세션
    생성/resume 직후)과 `/session/{id}/next`(선택된 category에 ready
    candidate가 없을 때 Pool Fallback 3단계 직전)이고, 대상은 **요청을
    보낸 인증 사용자 한 명**이다. seed loader도 계정 생성 CLI도 Wave 3
    worker도 만들지 않는다(각각의 기각 이유는 ADR-010). **review
    candidate(`fsrs_due` / `context_repair` / `reinforcement`)도 Wave 2가
    만든다.** 그래서 Core E2E 9~12단계와 Regression Scenario A~D를 worker
    없이 Wave 2에서 재현할 수 있다. 판정 근거: materialization은 provider
    호출이 아니라 결정론적 DB 연산이므로 `08_LLM_SPEC.md`의 LLM 호출
    경계를 어기지 않고, 같은 문서가 request handler에 허용한 범위 안이다.
    worker의 일은 **없는 콘텐츠를 생성**해 `sentences`를 채우는 것이고,
    그렇게 만들어진 문장은 다음 materialization에서 candidate가 된다
    (`09_BACKGROUND_JOBS.md`에 "worker는 candidate row를 만들지 않는다"
    명시). role은 `user_item_learning_state.is_active_learning_target`으로
    `new`/`exploration`이 배타적으로 갈리며, cold start에서는 exploration만
    생긴다(Cold Start 절의 "available category만 사용한다"와 일치).
    `context_repair`는 **새 컬럼 없이** 가장 최근 `몰랐음` event의
    presentation stage + 현재 `context_stage` + `item_exposures`로 판정한다.
    한 item에 대해 review candidate는 **한 reason으로 하나만** 만든다
    (평가 순서는 `Review Reason 선택`의 우선순위와 동일). 둘 이상 만들면
    같은 item·같은 stage에서 대개 같은 문장을 골라 유일성 제약과 충돌한다.
    `status`의 경계를 고정했다: `queued` = 콘텐츠가 아직 없어 worker가
    생성 중(Wave 3), `ready` = 지금 그대로 제시 가능. 테스트는 candidate를
    손으로 INSERT하지 않고 materialization을 호출해 만든다(선택 함수의
    unit test만 예외). **한계:** MVP에는 문장 단위 "anchor로부터의 거리"
    지표가 없어 `varied`와 `new_context`의 문장 선택 규칙이 같다.
-   **[P-2] 서버가 발생시키는 event의 `client_event_id`**
    (`05_API_SPEC.md`의 `event idempotency key`가 canonical,
    `04_DB_SPEC.md`의 `client_event_id 발급 주체`, ADR-008):
    `04_DB_SPEC.md`는 컬럼을 "client 생성 UUID"로, `05_API_SPEC.md`는
    "상태 변경 event POST는 client가 생성한 `client_event_id`를 포함한다"로
    정의했지만 `session_started` / `sentence_viewed` /
    `sentence_completed` / `mastery_probe_shown` / `session_finished`는
    **client가 POST하는 endpoint가 없어** 두 문장이 서로 모순이었다. 컬럼
    의미를 **"event의 idempotency key(UUID), 발급 주체는 event_type마다
    고정"**으로 고치고 16개 event 전부의 발급 주체 표를
    `05_API_SPEC.md`에 두었다(두 문서에 표를 중복하지 않는다). server
    발급은 `uuid5(NC_EVENT_NAMESPACE, 자연키)`이며 자연키에 시각·순번을
    넣지 않는다. **`/session`·`/next`·`/finish`의 body에
    `client_event_id`를 받지 않는다** --- 셋 다 서버 row에 대응하는 자연키가
    있고, body를 늘리면 client가 endpoint마다 UUID를 만들어 재시도 간
    보존해야 한다. `session_extended`만 client 발급이다(한 세션에서 여러
    번 정당하게 일어나고 재시도와 두 번째 연장을 구분할 자연키가 없다).
    `/next` 재시도의 presentation 중복 생성은 client key가 아니라 새
    **`열린 presentation 불변식`**으로 막는다: 한 세션에 `completed_at IS
    NULL`인 presentation은 최대 1개이고 `/next`는 그것을 그대로 반환한다.
    따라서 `/next`가 직전 문장을 암묵적으로 완료시키지 않고, client가
    `/complete`를 명시적으로 호출한다. `/finish`는 열린 presentation을
    완료 처리한다. 컬럼 이름은 `client_event_id`로 유지한다(이름 변경의
    이득이 migration 비용보다 작다).
-   **[G-1] 세션 내 probe pacing** (`06_LEARNING_ENGINE.md`의
    `Probe Pacing`이 canonical): `14_CONFIGURATION.md`가 세션당 개수만
    정하고 "언제 꽂는가"가 없어, 상한만 구현하면 초반에 probe가 연속으로
    나와 `03_UI_UX_SPEC.md`("probe는 세션의 중심 UI가 되어서는 안 된다")와
    충돌했다. `/next`가 probe를 싣는 조건을 결정론적 3항으로 확정했다:
    max 미만 + `probe_min_gap_presentations` 간격(세션 첫 probe도 gap만큼
    뒤로 민다) + 대상 우선순위·cooldown을 만족하는 후보 존재.
    **`mastery_probe_target_per_session_min`은 강제하지 않는다.** 관측
    목표이며, 채우려고 cooldown이나 대상 우선순위를 깨면 가치 없는
    evidence를 만들고 `Skip` 규칙과 충돌하며, 간격을 깨면 UI 제약을
    어긴다. probe가 너무 드물면 min을 올리는 것이 아니라
    `probe_min_gap_presentations`를 줄인다. 연속 skip 시 세션 probe budget
    축소는 **MVP에서 구현하지 않는다**(item 단위 `probe_skip_cooldown_days`가
    이미 담당한다). 새 config 키: `learning.probe_min_gap_presentations: 3`.
-   **[G-4] `probe_id`의 발급·저장 위치** (`05_API_SPEC.md`의
    `Mastery Probe`가 canonical, `04_DB_SPEC.md`의
    `probe 상태를 어디에 두는가`, ADR-009): `probe_id`는 해당 probe를 낸
    **`mastery_probe_shown` learning_event의 정수 id**다. **전용
    `mastery_probes` 테이블을 만들지 않는다** --- probe가 필요로 하는
    *상태*는 이미 `user_item_learning_state.last_probe_at`과
    `probe_skip_count`에 전용 컬럼으로 있고, event log에서 읽는 것은
    "이 probe_id가 유효한가, 어떤 item인가"라는 조회이지 상태 저장이
    아니다. 새 테이블은 모든 컬럼이 파생값이고 그 unique 제약도 P-2의
    UUIDv5 자연키와 같은 내용을 두 번 표현한다. `probe_id =
    study_presentation_id` 안은 body의 `probe_id`를 중복 정보로 만들면서
    event 조회를 그대로 남기므로 기각했다. `probe-response`는 `probe_id`로
    event를 조회해 `event_type` / `user_id` / `study_presentation_id`를
    검증하고(어긋나면 400), 응답 event의 `learning_item_id`는 **client가
    보낸 값이 아니라 조회한 probe event의 값**을 쓴다. 같은 `probe_id`에
    응답은 최대 1건이다. P-2의 server 발급 덕분에 같은 presentation을 다시
    받아도 `probe_id`가 같은 값으로 유지된다.
-   **[E-1] 무신호 판정 기준** (`07_SRS_SPEC.md`의 `No-signal review`가
    canonical): v0.2의 "item을 누르지 않고 / self-report도 하지 않고 /
    probe도 없고"라는 서술을 문자 그대로 읽으면 **click 한 번이나 probe
    제시만으로 무신호가 아니게 되어** `deferred_until`이 설정되지 않고 그
    due item이 무한히 재선택된다. 이는 `13_ACCEPTANCE_CRITERIA.md`의
    "무신호 review가 무한 due loop를 만들지 않음"과 Scenario B를 어긴다.
    기준을 **"FSRS rating을 만드는 explicit evidence가 있는가"**로
    고쳤다. 신호는 `self_report_{known,uncertain,unknown}`과
    `mastery_probe_{known,uncertain,unknown}` **6개뿐**이며,
    `item_clicked` / `explanation_revealed` / `translation_revealed` /
    `mastery_probe_shown` / `mastery_probe_skipped` / `sentence_viewed` /
    `sentence_completed`는 **있어도 무신호**다. 근거: 무신호 처리의 목적은
    (1) 증거 없는 review가 FSRS를 오염시키지 않게 하면서 (2) 무한 due
    loop를 막는 것인데, click과 skip은 `02_LEARNING_POLICY.md`에서 이미
    mastery evidence도 FSRS grade도 아니므로 목적 1에 기여하지 않는다.
    목적 2를 포기할 이유가 없다. 판정 단위를 **(presentation, target
    item) 쌍**으로 명시했고(target 2개 중 하나만 self-report를 받는 경우),
    처리는 `presentation_role = review`일 때만
    `review_states.deferred_until` 설정 +
    `user_item_learning_state.passive_no_signal_count` 증가로 고정했다.
    `02_LEARNING_POLICY.md`의 중복 서술은 canonical 참조로 교체했다.

새 config 키 2개(`learning.probe_min_gap_presentations: 3`,
`learning.candidate_materialization_batch_size: 20`)를
`14_CONFIGURATION.md`에 추가했다. 둘 다 학습 정책 tuning 값이며 본문과
acceptance에는 숫자를 박지 않았다. **새 테이블은 0개**이고,
`user_sentence_candidates`에 materialization idempotency를 위한 partial
unique index 하나만 추가했다.

교차 참조만 추가하거나 중복 서술을 canonical 참조로 바꾼 문서:
`02_LEARNING_POLICY.md`, `09_BACKGROUND_JOBS.md`, `12_TEST_PLAN.md`(unit
4건 + integration 5건 + Core E2E 1단계 보강), `13_ACCEPTANCE_CRITERIA.md`
(수치 없는 기준 4줄).

#### Wave 2 구현 보고 반영 (같은 후속 보완)

Wave 2 구현 중 보고된 명세 모순 2건과 공백 4건을 확정했다. 새 버전 번호를
만들지 않는다. **새 테이블·새 컬럼·새 config 키는 없다.**

-   **[C-1] Candidate Materialization의 실행 위치**
    (`06_LEARNING_ENGINE.md`의 `Pool Fallback`이 canonical):
    06은 "0단계", `05_API_SPEC.md`는 "3단계(job enqueue) 직전"이라고 적혀
    서로 다르게 읽혔다. **0단계로 확정**하고, 0단계 실행 뒤 같은 deficit
    순서로 category를 다시 훑는 1단계를 명시했다. 다른 category로 먼저
    내려가면 아직 만들 수 있던 문장을 두고 Category Mix가 틀어진다.
    0단계는 **요청당 1회**이며 1단계가 비어도 되돌아가지 않는다. 05와
    `실행 시점과 대상` 표, ADR-010의 서술을 이 canonical 참조로 맞췄다.
-   **[C-2] reinforcement 판정의 exposure 소스**
    (`07_SRS_SPEC.md`의 `Meaningful Exposure 정의`가 canonical):
    06이 denormalized cache인 `review_states.meaningful_exposure_count`를
    읽는다고 적어 07의 "canonical source는 `item_exposures`"와 충돌했다.
    06의 reinforcement 조건을 **`invalidated_at IS NULL`인
    `item_exposures` 건수**로 고쳤다. 07에는 cache를 읽어도 되는 조건을
    명시했다 --- **결과가 candidate 선택이나 mastery/FSRS 상태에 영향을 주지
    않는 표시·집계뿐**이다. content flag가 `invalidated_at`을 설정하는
    시점과 cache 재계산 시점이 어긋날 수 있기 때문이다.
-   **[G-5] probe 대상 우선순위가 도달 불가능했다**
    (`02_LEARNING_POLICY.md`, ADR-011): `user_mastery` 행은 explicit
    evidence 기록 시에만 만들어지고 그 시점에 `evidence_count = 1`,
    `comprehension_mastery`가 non-NULL이 되므로, v0.2의 2번("passive
    exposure가 반복됐지만 explicit evidence가 없는 item")은 항상 1번의
    부분집합이었다. 목록을 **2단**으로 확정하고 2번을 **1번 내부의 정렬
    기준**(`passive_no_signal_count >= passive_exposures_before_probe`인
    item 먼저)으로 내렸다. 행 생성 시점을 첫 exposure로 앞당기는 안은
    스키마 의미를 바꾸고도 **같은 순서**를 낳으므로 기각했다. `uncertain`은
    새 임계값 없이 기존 세 observation 값 중 `애매함` 최근접으로 정의했다.
-   **[G-6] "서로 충돌하는 evidence"의 정의 부재**
    (`02_LEARNING_POLICY.md`, ADR-011): **MVP에서 순위로 두지 않는다.**
    EMA 갱신 아래에서 known/unknown이 섞인 item의 mastery는 가운데로
    모이므로 uncertain 순위가 이미 잡는다. 정의를 지금 만들면
    `learning_events` 역추적 규칙이 그대로 새 정책이 된다.
-   **[G-7] `max_new_items_per_sentence` 초과 처리**
    (`06_LEARNING_ENGINE.md`의 `role별 규칙`): "초과하면 그 문장은
    건너뛴다"를 **"상한까지만 붙이고 초과 item은 그 문장에 싣지 않는다.
    문장 자체를 버리지 않는다"**로 고쳤다. 문장을 버리면 이미 만든
    candidate를 되돌려야 하고 item 하나 때문에 멀쩡한 문장이 사라진다.
    실리지 못한 item은 다른 문장이나 다음 실행에서 자기 candidate를 얻는다.
    `08_LLM_SPEC.md`의 validation 10번은 **생성 시점**, 이 규칙은
    **materialization 시점**임을 명시했다.
-   **[G-8] anchor 문장을 더는 쓸 수 없을 때**
    (`06_LEARNING_ENGINE.md`의 `anchor 문장을 더는 쓸 수 없을 때`):
    원인에 따라 갈랐다. **`quarantined`면 `anchor_sentence_id`를 NULL로
    되돌리고 재지정**하고, 그 밖의 사유로 Ready invariant를 만족하지
    않으면 재지정 없이 그 stage를 건너뛴다. 둘을 같게 다루면 quarantine된
    anchor를 가진 item이 `anchor`/`near_original`에서 영영 candidate를 얻지
    못해 학습 대상에서 조용히 빠진다. quarantine 시점에 그 문장의
    `item_exposures`는 이미 `invalidated_at`으로 무효화되므로
    (`10_ERROR_HANDLING.md`) 보존할 "최초 학습 문맥" 기록 자체가 없다.

구현 결정 중 명세에 남긴 것 2건:

-   **deficit 비교 전 반올림**(`06_LEARNING_ENGINE.md`의 `Category Mix
    계산`): `0.7*12-8`과 `0.2*12-2`가 IEEE 754에서 1e-16 다르므로,
    반올림하지 않으면 명세가 정한 tie-break(`review → new → exploration`)가
    사실상 실행되지 않고 부동소수점 오차가 순서를 정한다. 자릿수는 구현
    상수이며 학습 정책 값이 아니므로 config에 두지 않는다. (기본 비율과
    15문장 세션에서는 review 11 / new 3 / exploration 1로 수렴한다. 동률이
    전부 review로 가는 것이 명세의 귀결이며 acceptance에는 숫자를 박지
    않는다.)
-   **probe 선택은 idempotent하지 않다**(`06_LEARNING_ENGINE.md`의
    `Probe Pacing`): probe를 실으면 그 event가 세션에 남아 다음 호출의
    pacing과 제외 집합이 달라진다. `열린 presentation 불변식`으로 같은
    presentation을 다시 반환하는 경로에서는 다시 고르지 않고 `uuid5`
    자연키로 기존 event를 조회해 같은 `probe_id`를 반환한다.

새 ADR: `docs/decisions/ADR-011-probe-target-priority.md`.

#### Wave 2 검증 보고 반영 (같은 후속 보완)

Wave 2 verifier가 보고한 도달 불가능 조항 3건과 공백 2건을 확정했다. 새 버전
번호를 만들지 않는다. **새 테이블·새 컬럼·새 config 키는 없다.**

-   **[A] `context_stage` 전이 규칙 부재**
    (`07_SRS_SPEC.md`의 `Context Progression` → `전이 규칙`이 canonical,
    ADR-012): `context_stage`에 값을 쓰는 지점이 행 생성 시 `anchor` 대입
    하나뿐이라, 최소 5회 노출이 전부 같은 anchor 문장으로 채워지고
    `near_original`/`varied`/`new_context` 분기가 한 번도 실행되지 않았다.
    전이는 **presentation을 닫을 때 meaningful exposure와 같은 트랜잭션**에서
    일어나고, 대상은 그 presentation에서 exposure가 기록된 item이다.
    explicit `몰랐음`이면 `min(S_cur, down(S_shown))`, 아니면
    `max(S_cur, up(S_shown))`이다. v0.2 표의 `또는`은 **실패 여부**였다 ---
    실패 없는 경로를 따라가면 표의 exact sequence와 `任せる` 예시가 그대로
    재현된다. 무신호와 `애매함`은 올리고 explicit `몰랐음`만 내린다.
    `max`/`min`은 Ready Pool에 남은 낮은 stage candidate와 `Pool Fallback`
    2단계의 anchor reinforcement가 이미 올라간 ladder를 끌어내리지 않게 한다.
-   **[A-config] "config로 조정 가능하다"를 철회**
    (`07_SRS_SPEC.md`, `14_CONFIGURATION.md`): 조정 대상이 될 값은 "한
    stage에 몇 번 머무는가"인데, 하강이 있는 이상 `item_exposures`의 stage별
    건수로는 복원되지 않아(되돌아온 stage의 옛 노출이 즉시 재승급시킨다)
    **새 컬럼**이 필요하다. MVP 제약을 넘으므로 키를 만들지 않고 그 문장을
    철회했다. ladder 변경은 config 변경이 아니라 명세 변경이다.
-   **[B] `context_repair`가 도달 불가능**
    (`07_SRS_SPEC.md`의 `New-context Failure`, `06_LEARNING_ENGINE.md`의
    `review candidate: reason 판정`): "한 단계 쉬운 context"가 **stage
    하강**임을 확정했다. 같은 stage 안에서 다른 문장을 고르는 것이 아니다.
    stage 하강은 [A]의 전이 규칙이 수행하므로 조건 b가 실제로 참이 될 수
    있다. 하강 자체는 결정론적이고, `할 수 있다`가 걸리는 것은 다음
    presentation이 실제로 `context_repair`가 되는지다. 조건 1-a의 S_fail
    소스를 **그 (presentation, item)의 `invalidated_at IS NULL` item_exposures
    row**로 한정했다 --- target이 아닌 item의 self-report와 flag로 무효화된
    노출이 repair를 유발하지 않게 한다.
-   **[C] `new` role pool이 항상 빔 (명세 내부 충돌)**
    (`06_LEARNING_ENGINE.md`의 `role별 규칙`, ADR-013): `new`를 "아직
    `review_states` 행이 없는 item"으로 정의하던 서술을 **철회**했다.
    `07_SRS_SPEC.md`의 `몰랐음 -> Again`이 승격과 동시에 `review_states`를
    만들므로 그 집합은 공집합이었다. FSRS mapping이 더 핵심적이고 Core E2E
    7단계가 그것을 검증하므로 `new`의 정의를 고쳤다. 새 기준은 **"아직
    target으로 제시된 적이 있는가"**이고 판정 소스는 다른 모든 노출 판정과
    같은 `item_exposures`다. `review`는 exposure 1건 이상으로 좁혀 두 pool을
    배타적으로 유지했다.
-   **[D] 승격된 incidental item이 exposure를 못 받음**
    (`07_SRS_SPEC.md`의 `target item의 canonical 정의`, ADR-013):
    `target item`은 그 presentation의 `user_sentence_candidate_targets`
    row라고 확정했다(materialization 시점 고정). 문장의 모든 tappable로
    넓히면 "스쳐 지나간 것을 모두 세지 않는다"가 무너지고 [C]의 `new` 기준도
    함께 무너진다. 대신 승격 시점에 `anchor_sentence_id`를 **그 문장**으로
    기록해(`anchor_sentence_id 지정`), 그 item의 첫 `new` presentation이 같은
    문장을 anchor로 다시 제시하게 했다. 최초 문맥은 5회 중 1회로 정상
    계상되고 시점만 한 presentation 뒤로 밀린다.
-   **[E] explicit review 후 `deferred_until` 미해제**
    (`07_SRS_SPEC.md`의 `deferral 해제`): explicit evidence가 FSRS review로
    기록되는 순간 `deferred_until = NULL`로 지운다. deferral의 근거는 "증거가
    없다" 하나뿐이고, 남겨 두면 `Again` 직후 몇 분 뒤의 due를 12시간 가려
    스케줄 준수가 아니라 스케줄 무시가 된다. 무한 due loop는 deferral의
    지속이 아니라 무신호 presentation마다 다시 거는 동작이 막는다.

교차 참조·서술을 맞춘 문서: `02_LEARNING_POLICY.md`(`Incidental Item Click`이
승격 시 일어나는 일 4줄과 canonical 참조, `Exposure`에 전이 규칙 참조),
`06_LEARNING_ENGINE.md`(`stage → sentence` 표의 anchor 지정 참조, 문장이 없을
때 stage가 움직이지 않는다는 명시, Cold Start 서술),
`14_CONFIGURATION.md`(ladder에 키를 두지 않는 이유),
`12_TEST_PLAN.md`(unit 2건 + integration 3건), `13_ACCEPTANCE_CRITERIA.md`
(수치 없는 기준 2줄).

새 ADR: `docs/decisions/ADR-012-context-stage-progression.md`,
`docs/decisions/ADR-013-exposure-target-and-new-role.md`.

#### security review 반영 --- event key 선점과 상태 게이트 (같은 후속 보완)

security reviewer가 **실제 요청으로 익스플로잇한 결함 1건**과 명세 공백 1건을
확정했다. 새 버전 번호를 만들지 않는다. **새 테이블·새 컬럼·새 config 키는
없다.**

-   **[F] client가 server 발급 event key를 선점해 세션을 영구 브릭**
    (`05_API_SPEC.md`의 `키 공간 분리 (server = v5, client = v4)`가 canonical,
    ADR-008의 `후속 결정`): server 발급 키는 공개된 자연키의 `uuid5`인데
    client 발급 키와 **같은 `(user_id, client_event_id)` unique 공간**에
    들어갔다. `/extend` body에 `uuid5(NS, "session_finished:{sid}")`를 보내면
    `/finish`가 영구 409이고, idle timeout 만료가 같은 키를 쓰므로
    `POST /api/study/session`까지 영구 500이 되어 DB 직접 수정 없이는 복구되지
    않았다. ADR-008은 발급 주체만 정하고 두 공간이 겹친다는 사실을 다루지
    않았다 --- 수용된 위험이 아니라 누락이다. **client 발급 키를 UUIDv4로
    제한**해 공간을 version으로 가른다. `uuid5`는 항상 version 5이므로 선점이
    구조적으로 불가능하고, `crypto.randomUUID()`가 v4를 내므로 client 비용이
    없다. v4가 아니면 body 검증 실패(422)다. server 발급 경로가 그럼에도 다른
    `event_type`의 행을 만나면 client 잘못이 아니므로 409가 아니라 500 +
    로그다. 버린 대안(server 전용 namespace 추가 = obscurity, 발급 주체 컬럼
    추가 = 새 컬럼 비용, event 기록 생략 = audit 공백)은 ADR-008에 있다.
-   **[G] 종료된 세션의 presentation 상호작용 7종이 그대로 허용됨**
    (`05_API_SPEC.md`의 `세션·presentation 상태 게이트`가 canonical, ADR-014):
    `/next`와 `/extend`만 409였고 나머지는 동작해, 끝난 세션의 self-report가
    **새 mastery 행을 만들고** `last_activity_at`을 계속 밀었다. 더 중요한
    것은 `/complete` 시점에 exposure 확정과 무신호 처리가 끝난 presentation에
    뒤늦게 explicit evidence가 붙어 **같은 노출이 두 번 다르게 평가**된 점이다.
    상호작용 5종(click, explanation-revealed, translation reveal,
    self-report, probe-response)은 **session이 닫혔거나 presentation이
    완료됐으면 409**로 통일한다. 예외는 둘이다. `/complete`는 이미 완료된
    presentation이면 200이고(성공한 `/complete`의 재시도가 `/finish`와 겹쳐
    실패로 보이면 안 된다) 열린 presentation인데 session이 닫혔으면 409다.
    **`/flag`는 상태와 무관하게 허용한다** --- `10_ERROR_HANDLING.md`가
    요구하는 "이미 생성된 `item_exposures` 무효화"는 완료 이후의 flag만
    참으로 만들 수 있어서, 막으면 그 조항이 도달 불가능해진다. 대신 닫힌
    session의 flag는 `last_activity_at`을 갱신하지 않는다. 판정 순서는
    소유권(404) → 상태(409) → 그 밖의 검증(400)이다. idle timeout으로 닫힌
    session에 남은 미완료 presentation은 영원히 미완료로 남는다(의도된 결과.
    부재를 완료로 추론하지 않는다). idle timeout은
    `POST /api/study/session` 시점에만 적용되고 모든 상호작용이
    `last_activity_at`을 갱신하므로, 사용자가 화면을 보는 도중 409를 받는
    경로는 없다.

교차 참조를 맞춘 문서: `04_DB_SPEC.md`(`client_event_id 발급 주체`에 키 공간
분리 한 문단, 컬럼·unique는 불변), `12_TEST_PLAN.md`(unit 1건 + integration
3건), `13_ACCEPTANCE_CRITERIA.md`(수치 없는 기준 2줄).

새 ADR: `docs/decisions/ADR-014-closed-session-interaction-gate.md`.

#### Wave 3 계획 반영 --- LLM/worker 차단 공백 13건 (같은 후속 보완)

Wave 3(LLM/worker) 계획에서 보고된 **차단성 명세 공백 13건**과 비차단 5건을
확정했다. 새 버전 번호를 만들지 않는다. MVP 범위를 넓히지 않았고,
`spec/06_LLM_ENGINEERING_PRINCIPLES.md`의 `MVP 구현 의무 범위`가 제외한
항목(prompt caching 최적화, 정교한 model routing, 고급 비용 지표, 100개
golden eval, embedding similarity, 형태소 분석기)은 끌어들이지 않았다.

**새 테이블 1개 / 새 config 키 6개 / 새 컬럼 0개**다.

-   **[1] worker heartbeat 저장 위치** (`04_DB_SPEC.md`의
    `worker_heartbeats`, `09_BACKGROUND_JOBS.md`의 `Worker Heartbeat`,
    `05_API_SPEC.md`, ADR-015): 두 번 미뤄진 미결을 닫았다. 전용 테이블
    `worker_heartbeats(worker_name PK, last_heartbeat_at)`를 만들고, worker가
    **job이 없어도** loop마다 upsert하며 job 트랜잭션과 분리해 commit한다.
    `/api/health`는 최대값 하나를 읽어 `unknown | ok | stale`을 낸다. 버린
    대안인 "`generation_jobs`의 최근 활동으로 추론"은 개인용 앱에서 **job이
    0건인 날이 정상**이라 "일이 없다"와 "worker가 죽었다"를 구분하지
    못한다 --- heartbeat가 가장 필요한 날에 판정이 항상 틀린다.
-   **[2] Ready invariant의 범위** (`08_LLM_SPEC.md`의
    `Ready invariant와 같은 범위`, `06_LEARNING_ENGINE.md`): 대상은 target
    item만이 아니라 그 문장의 **모든 `is_tappable` item**이다. seed loader와
    Wave 2 materialization이 이미 이 해석이므로 generation validation만 약한
    해석을 쓰면 "생성은 통과했는데 candidate는 될 수 없는" 문장이 조용히
    쌓인다. 함께 못박은 것: target item은 반드시 tappable이고, 설명을 붙일 수
    없는 표현은 tappable로 만들지 않는다.
-   **[3] `preferred_new_items_per_sentence`의 소비처**
    (`14_CONFIGURATION.md`): 생성 프롬프트에 싣는 **선호값**이며 유일한
    소비처는 `GENERATE_SENTENCE_BATCH`의 요청 context다. 강제 상한은
    `max_new_items_per_sentence` 하나이고, 선호값을 어겼다는 이유로 생성된
    문장을 버리지 않는다.
-   **[4] `normalized_hash` 정규화 규칙** (`08_LLM_SPEC.md`):
    `NFKC` → 모든 Unicode whitespace 제거 → `sha256` hex를 canonical로
    확정했다. **현행 seed loader 구현을 그대로 승계**한다 --- 바꾸면 기존
    seed 행의 해시가 비교 불가능해져 duplicate 검사가 seed를 못 본다. seed
    loader와 worker는 같은 함수 하나를 쓴다.
-   **[5] structured output 스키마** (`08_LLM_SPEC.md`의
    `Structured Output 스키마`): 응답 JSON을 필드 단위로 확정했다. 모델이 우리
    쪽 id를 만들지 않고, item 지시는 요청 로컬 라벨 `item_ref`(`it{n}`)로만
    한다. 요청에 없는 ref가 오면 그 문장을 버린다(`unknown_item_ref`).
    `register` 필드는 스키마에 두지 않는다(`00_SCOPE.md`).
    `GENERATE_REVIEW_CONTEXT`도 같은 스키마를 쓰고 `EXPLAIN_ITEM`은
    `explanation` 객체 하나만 받는다.
-   **[6] `failed`와 `dead_letter`의 경계** (`09_BACKGROUND_JOBS.md`):
    attempt 소진 = `failed`, 재시도해도 결과가 같은 영구 오류 = `dead_letter`
    (payload 필수 key 불충족 / 참조 행 없음 / 미지원 job_type / active
    prompt_version 없음). provider 인증 실패는 키 교체 중일 수 있어
    `dead_letter`가 아니라 retry다.
-   **[7] stale `running` job 회수** (`09_BACKGROUND_JOBS.md`의
    `Claim과 lease`): 명세에 아예 없어 crash한 job이 영구히 `running`에
    갇혔다. `jobs.claim_lease_seconds`를 신설하고
    `running AND started_at < now - lease` → `retry`로 회수하되
    **`retry_count`를 증가시킨다.** 증가시키지 않으면 실행할 때마다 crash하는
    job이 무한 재실행된다. claim은 `FOR UPDATE SKIP LOCKED` 단일 UPDATE다.
-   **[8] token/request usage 저장 위치와 일 경계**
    (`04_DB_SPEC.md`의 `result_ref 구조`, `09_BACKGROUND_JOBS.md`의
    `usage 기록과 일 경계`, `11_OBSERVABILITY.md`): **새 테이블 없이**
    `generation_jobs.result_ref.usage`에 per-job 누적 기록한다. 실패한 호출도
    비용이므로 지우지 않는다. daily ceiling 판정 경계는 **UTC 일**이다 ---
    사용자에게 보이는 학습 경계가 아니라 전역 운영 장치이고 job은 사용자
    단위로 돌지 않는다. ceiling에 걸리면 **claim하지 않는다**(claim 후
    실패시키면 한도 때문에 attempt가 소모된다).
-   **[9] duplicate 비교 corpus** (`08_LLM_SPEC.md`의
    `duplicate 비교 corpus`): `sentences` 전체 중 `status != retired`이며
    **`quarantined`를 반드시 포함**한다. 빼면 flag로 격리한 문장을 다시
    생성해 새 id로 ready가 되고 `13_ACCEPTANCE_CRITERIA.md`의 "flag된
    content가 다시 Ready로 선택되지 않음"이 깨진다. similarity는 표준
    라이브러리 문자 유사도이며 embedding은 MVP 의무가 아니다.
-   **[10] `GENERATE_SENTENCE_BATCH`의 대상 선정과 batch 크기**
    (`08_LLM_SPEC.md`의 `GENERATE_SENTENCE_BATCH 대상 선정`): payload는
    `{user_id, presentation_role}`뿐이고 **item 목록을 넣지 않는다** ---
    idempotency key가 하루 창이고 `ON CONFLICT DO NOTHING`이라 그날 첫 job의
    payload가 고정되어 실행 시점에는 이미 낡는다. worker가 실행 시점에 role별
    대상 조건을 다시 계산하고, 거기에 "Ready invariant를 만족하는 문장이 0건"
    조건을 더해 **materialization이 문장을 못 찾은 item만** 대상으로 삼는다.
    상한은 새 키 `llm.sentences_per_batch`이며 item 하나당 문장 하나다.
-   **[11] `EXPLAIN_ITEM` / `GENERATE_REVIEW_CONTEXT`의 트리거와 key**
    (`09_BACKGROUND_JOBS.md`의 `Enqueue 트리거와 idempotency key`가
    canonical, `06_LEARNING_ENGINE.md`가 참조): enqueue는 전부 request 경로의
    materialization에서 일어나고 worker는 job을 만들지 않는다. 세 job_type의
    트리거·key 형식·payload 구조를 표 하나에 모았다. 기존 replenishment key
    형식(`replenish:...:{YYYY-MM-DD}`)도 같은 표에 canonical로 올려 구현과
    명세가 갈라지지 않게 했다. 두 job의 경계는 "문장이 없다"
    (`GENERATE_SENTENCE_BATCH`)와 "이 stage에 맞는 문장이 없다"
    (`GENERATE_REVIEW_CONTEXT`)다.
-   **[12] `origin = generated` learning_item을 누가 만드는가**
    (`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`, `04_DB_SPEC.md`,
    `06_LEARNING_ENGINE.md`): **MVP는 만들지 않는다.** worker는 요청에 실어
    보낸 item만 annotate한다. `06_LEARNING_ENGINE.md`의 "generated item에는
    frequency 정보가 없다"는 한계 서술은 삭제하지 않고, 그 한계가 MVP에서는
    실제로 발생하지 않는다는 한 문단을 덧붙여 모순을 없앴다.
-   **[13] `prompt_versions` 등록 절차** (`04_DB_SPEC.md`): version 형식은
    원칙 6의 이름을 그대로 쓴 `sentence_gen_v{n}` / `review_context_v{n}` /
    `explain_item_v{n}`이고, prompt 본문이 바뀌면 `{n}`을 올린다. `active`는
    **partial unique index `UNIQUE (task_type) WHERE active`**로 강제한다
    ("가장 최근 행"으로 추론하면 rollback이 불가능해진다). 등록은 idempotent
    upsert 스크립트이며 본문은 Git 파일, DB는 registry만 둔다.
-   **[14] provider/model 선택 소스와 env 변수명**
    (`spec/04_SECURITY_AND_DATA.md`의 `LLM provider 자격증명 (MVP 확정)`,
    `08_LLM_SPEC.md`, `02_ARCHITECTURE.md`, ADR-016): 구현 선택은
    `LLM_PROVIDER = openai | stub`(기본 `stub`), secret은 `LLM_API_KEY`이며
    **worker 프로세스에만 주입**한다. 모델명은 `prompt_versions` 행에서 온다.
    **mock provider(`stub`)를 명세에 정식 포함**하되 안전장치를 함께 박았다:
    `APP_ENV = production`이면 worker 부팅 실패, `openai`인데 키가 없어도 부팅
    실패, stub 응답도 같은 validation을 통과해야 저장, provenance에
    `provider/model = "stub"` 기록.
-   **[16] `sentences.difficulty_json`** (`08_LLM_SPEC.md`): 모델이 준 label만
    `{"label": ...}`로 저장하고 정확성을 검증하지 않는다. 허용값은 스키마
    enum이 강제하며, 이 값은 문장 선택에 쓰이지 않는다.
-   **[17] validation 탈락 콘텐츠** (`08_LLM_SPEC.md`의
    `탈락한 콘텐츠의 처리`): **저장하지 않는다.** `draft`로 남기면 아무도 읽지
    않는 행이 쌓이는데 정리할 maintenance job도 admin UI도 MVP에 없다. 대신
    13개 사유 코드를 `result_ref.rejected`와 로그에 남긴다. 그 결과 MVP에는
    `sentences.status = draft` 행을 만드는 경로가 없고, 그 사실을
    `04_DB_SPEC.md`에 명시했다.

새 config 키(전부 `14_CONFIGURATION.md`):

``` text
jobs.poll_interval_seconds        5
jobs.claim_lease_seconds        300
jobs.heartbeat_interval_seconds  30
jobs.heartbeat_stale_seconds    120
llm.sentences_per_batch           5
llm.avoid_examples_per_item       3
```

`heartbeat_stale_seconds > heartbeat_interval_seconds`를 config 로드 시
검증한다(같으면 정상 worker가 주기적으로 `stale`로 보고된다).

교차 참조·서술을 맞춘 문서: `spec/02_ARCHITECTURE.md`(provider/model 출처
한 줄), `spec/04_SECURITY_AND_DATA.md`(env 절 신설),
`06_LEARNING_ENGINE.md`(Ready invariant 범위, enqueue 지점 2곳, Pool
Fallback 3단계 payload, generated item 한계),
`11_OBSERVABILITY.md`(수집 항목의 저장 위치 표), `12_TEST_PLAN.md`(unit
6건 + integration 8건), `13_ACCEPTANCE_CRITERIA.md`(수치 없는 기준 7줄),
`.env.example`(새 환경변수 2개).

새 ADR: `docs/decisions/ADR-017-worker-heartbeat-storage.md`,
`docs/decisions/ADR-016-llm-provider-selection.md`.

같은 확정에서 드러난 인접 공백 하나도 함께 닫았다:
`user_sentence_candidates.status = queued`는 **MVP에 만드는 경로가 없다**
(worker가 candidate를 만들지 않고 materialization은 곧바로 `ready`를 쓴다).
값과 partial unique index 조건은 그대로 두고 쓰지 않는다는 사실만 명시했다
(`04_DB_SPEC.md`).

#### Wave 3 구현 보고 반영 --- provider 주입과 stub (같은 후속 보완)

구현자가 보고한 **ADR 간 정면 충돌 1건**과 파생 확정 2건을 닫았다. 새 버전
번호를 만들지 않는다. **새 테이블·새 컬럼·새 config 키는 없다.**

-   **[18] `LLM_PROVIDER = stub`을 구현할 앱 코드가 존재하지 않았다**
    (`spec/04_SECURITY_AND_DATA.md`의 `LLM provider 자격증명 (MVP 확정)`이
    canonical, `08_LLM_SPEC.md`의 `Provider 선택과 model 출처`,
    ADR-016의 `개정` 절): ADR-016은 `LLM_PROVIDER = openai | stub`에 기본값
    `stub`을 두었고, ADR-015는 `StubProvider`를 `app/`에 두는 것을 명시적으로
    거부했다(구현체 1개 상한). 그 결과 `build_provider`가 `openai` 하나만
    만들어 **기본 설정으로 worker를 띄우면 `ProviderConfigError`**였다. 두
    의도는 양립하므로 **주입으로 해소한다.** 프로세스 진입점
    (`scripts/run_worker.py`)이 env를 읽어 `build_provider(name, api_key=...)`로
    만든 provider를 worker loop에 **인자로** 넘기고, 테스트는 같은 자리에
    `backend/tests/`의 test double을 넣는다. 그래서 claim / lease / validation /
    저장 / completed는 실제 코드로 돌고 provider 호출만 대체된다. 확정:
    `LLM_PROVIDER`의 **허용값은 `openai` 하나, 기본값 없음**이며 미설정·미지원
    값·키 없음은 전부 worker 부팅 실패다. `APP_ENV = production`이면 실패한다는
    검사는 **없앤다** --- 선택할 mock이 앱 코드에 없으므로 런타임 검사보다 강한
    구조적 보장이 남는다(Public Demo의 "structurally impossible"과 같은 형태).
    기본값을 `openai`로 두지 않는 이유는 ADR-016 원안이 막으려던 위험(키가
    놓인 개발 머신에서 유료 호출이 먼저 일어남)이 그대로 살아나기 때문이다.
-   **[19] `stub`이 남는 자리** (`08_LLM_SPEC.md`, `04_DB_SPEC.md`의
    `prompt_versions`): env 값에서 사라지고 **provenance 값으로만** 남는다.
    `prompt_versions.provider` / `provenance_json.provider = "stub"`은 test
    double이 만든 콘텐츠라는 뜻이고 테스트 fixture만 그 행을 만든다. stub
    응답도 똑같은 deterministic validation을 통과해야 저장된다는 규칙은
    그대로다.
-   **[20] `build_provider`가 `api_key`를 인자로 받는다** (ADR-015의
    `provider abstraction의 상한`, ADR-016의 `개정` 4): `app/llm/`이
    `app.settings`를 읽으면 G11(a)를 어기고 테스트가 값을 주입할 수 없다.
    환경변수를 **읽는** 유일한 지점은 worker 진입점이고 `build_provider`는
    key를 **client에 넣는** 유일한 지점이다. ADR-015의 "API key를 읽는 유일한
    지점"이라는 표현을 그렇게 정정했다. provider SDK는 구현체 모듈 안에서만
    import하며 SDK 버전은 명세가 아니라 의존성 manifest가 정한다.

ADR-015의 "키 없이 완주라는 요구는 명세 어디에도 없다"는 서술도 정정했다.
`12_TEST_PLAN.md`의 integration 목록과 `13_ACCEPTANCE_CRITERIA.md`가 실제로
그것을 요구한다. 결론(`app/`에 mock을 두지 않는다)은 바뀌지 않는다 --- 그
요구를 만족시키는 것이 env 값이 아니라 주입이라는 것이 이번 확정이다.

교차 참조·서술을 맞춘 문서: `spec/02_ARCHITECTURE.md`(허용값 한 줄),
`04_DB_SPEC.md`(`prompt_versions.provider`의 `stub` 주석),
`12_TEST_PLAN.md`(integration 2건 수정 + request 경로 SDK 미적재 조건),
`13_ACCEPTANCE_CRITERIA.md`(mock 선택 불가 기준 1줄), `.env.example`.

개정한 ADR: `docs/decisions/ADR-016-llm-provider-selection.md`(`개정` 절),
`docs/decisions/ADR-015-llm-worker-module-boundaries.md`(진입점 표기,
`build_provider` 시그니처, 정정 1건). 새 ADR은 없다.

#### Wave 3 구현 보고 반영 --- unknown token과 G12 문구 (같은 후속 보완)

구현이 명세 없이 내린 판단 4건을 명세에 확정했다. 새 버전 번호를 만들지
않는다. **새 테이블·새 컬럼·새 config 키는 없다.** 네 건 모두 구현된 동작을
그대로 명세화한 것이므로 구현 변경은 없다.

-   **[21] provider가 `usage`를 주지 않으면 token은 `null`이고 0이 아니다**
    (`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`가 canonical): 0은
    "호출했는데 토큰을 안 썼다"는 거짓이고 그 거짓이 그대로 daily ceiling
    판정에 들어간다. 누적은 **sticky-null**이다 --- 한 attempt의 token을
    모르면 그 job의 총계는 계속 `null`이며, 아는 부분까지 집계에서 빠진다.
    부분 합을 적으면 그 숫자가 **총계처럼** 보이기 때문에 "모른다" 쪽으로
    기운다. 손실은 `max_job_attempts`로 유계이고, 정확히 하려면 호출 단위
    기록이 필요한데 그것은 이미 같은 절이 MVP에서 만들지 않기로 한 것이다.
-   **[22] `daily_token_limit`은 unknown token에서 fail-closed다**
    (같은 절 + `14_CONFIGURATION.md` 한 단락): 오늘 호출한 job 중 token이
    `null`인 것이 하나라도 있으면 한도에 **도달한 것으로 본다**(신규
    generation 중단). 하한을 한도와 비교하는 것은 한도를 지키는 척하는
    것이고, `null`을 0으로 뭉개면 한도를 켜 둔 운영자가 상한 없는 청구서를
    받는다 --- 이 키가 막으라고 있는 유일한 사건이다. `null = limit
    disabled`와 모순되지 않는다: `null`은 판정을 하지 않는다는 뜻이고
    fail-closed는 한도를 **켜 둔** 경우에만 적용된다. 멈춤은 UTC 자정에
    해소되고 off-switch가 문서화된 기본값이며, 학습 세션은 Ready Pool로 계속
    돈다(불변식 #1). 멈춘 이유가 한도 자체가 아닐 수 있으므로 멈춤 로그에
    token이 `null`인 job 수를 함께 싣는다. **`daily_request_limit`은
    영향받지 않는다** --- 호출 수는 항상 셀 수 있다.
-   **[23] `result_ref` 구조에서 token이 nullable이다**
    (`04_DB_SPEC.md`의 `result_ref 구조`): `usage.input_tokens` /
    `usage.output_tokens`는 **정수 또는 `null`**이라고 서술을 맞췄다. 예시
    JSON은 그대로 두고(구체적 인스턴스다) 타입만 명시했다. 기록·누적 규칙과
    ceiling 판정은 [21][22]가 canonical이다.
-   **[24] ADR-015 G12에서 정적으로 검사 불가능한 절을 뺐다**
    (`docs/decisions/ADR-015-llm-worker-module-boundaries.md`): "enqueue
    모듈이 `generation_jobs` INSERT 외에 아무것도 하지 않는다"는 AST guard로
    검사할 수 없다. 검사할 수 없는 것을 정적 guard 문구에 두면 guard가
    지키는 범위가 실제보다 넓어 보인다. G12를 (a) jobs 모듈 import
    allowlist / (b) enqueue 모듈은 `app.llm`을 import하지 않는다 /
    (c) `BackgroundTasks` 금지로 **번호를 매겨 갈랐고**, 빠진 절반은
    `정적과 런타임의 분담`이 런타임 테스트로 받는다: request 경로가 worker
    loop와 job runner를 실행하지 않는다(`12_TEST_PLAN.md`의 Integration에
    항목 추가). 기존 `no_outbound_network()` +
    `assert_no_provider_import()`는 provider 쪽을 이미 덮는다.

`cached tokens` 판정: **MVP 필수가 아니다**(`11_OBSERVABILITY.md`).
`MVP 필수 범위` 목록이 닫힌 집합이고 거기에 없다. MVP는 기록하지 않으며
`usage` 구조에 키를 추가하지 않는다 --- 그 구조는 `04_DB_SPEC.md`가 MVP
확정으로 못박았으므로, 필요해지면 명세를 먼저 고친다. 문서 맨 위 `LLM:`
줄의 `cached tokens`는 장기 지표 쪽이다. 기존 문구("provider가 값을 줄 때만
담고")가 필수처럼 읽혔던 것을 여기서 닫았다.

교차 참조·서술을 맞춘 문서: `09_BACKGROUND_JOBS.md`(canonical 4개 bullet),
`04_DB_SPEC.md`(nullable 서술), `11_OBSERVABILITY.md`(nullable token +
`cached tokens` 판정), `14_CONFIGURATION.md`(fail-closed 한 단락),
`12_TEST_PLAN.md`(unit 1건 + integration 1건).

개정한 ADR: `ADR-015`(G12 분할 + 런타임 분담 한 단락). 새 ADR은 없다 ---
[21][22]는 되돌리기 비싼 결정이 아니라 canonical 절 하나로 뒤집을 수 있고,
그 절이 근거를 이미 담고 있다.

#### Wave 3 구현 보고 반영 --- cost 누적과 "무엇이 관측하는가" (같은 후속 보완)

구현·검증에서 드러난 **명세 문구가 사실과 다른 지점 4건**을 고쳤다. 새 버전
번호를 만들지 않는다. **새 테이블·새 컬럼·새 config 키는 없다.** 네 건 모두
문구 정정이며 구현 변경을 요구하지 않는다.

-   **[25] `estimated_cost_usd`의 누적 규칙이 없었다**
    (`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`가 canonical): 누적
    규칙이 `provider_calls`와 token에만 걸려 있고 sticky-null 문단의 주어도
    token이어서, cost는 "채운다"는 서술만 있었다. cost도 **token과 같은
    규칙**(attempt 합, 한 attempt를 모르면 sticky-null)임을 못박았다. 마지막
    attempt 값으로 덮어쓰면 retry한 job의 비용이 실제의 1/attempt로 보인다.
    같은 규칙이므로 한 함수로 구현한다 --- 구현은 `jobs/queue._accumulate`를
    int/float 공용으로 두어 규칙을 한 곳에만 둔다. 함께: **cost는 관측
    항목이며 ceiling 판정에 들어가지 않는다.** 한도는 `daily_request_limit`과
    `daily_token_limit` 둘뿐이고 fail-closed([22])는 `daily_token_limit`
    전용이다. cost로 판정하면 단가표를 모른다는 것만으로 생성이 멈추는데,
    단가표는 명세가 담지 않기로 한 것이므로 그 멈춤은 해소할 수단이 없다.
    `04_DB_SPEC.md`는 이미 cost를 nullable로 적고 기록 규칙을 09에 위임하므로
    고치지 않았다.
-   **[26] duplicate corpus의 `quarantined` 포함을 hash로 관측할 수 없다**
    (`12_TEST_PLAN.md` unit 1건; 규칙 자체는 `08_LLM_SPEC.md`의
    `duplicate 비교 corpus`가 canonical): 명세가 "격리된 문장과 같은 문장을
    생성하면 `duplicate_hash`로 탈락한다"를 관측 방법으로 적었으나 그것으로는
    규칙을 검증할 수 없다. `jobs/persistence`의 저장 직전 hash 대조가
    `sentences.status`를 보지 않으므로 corpus에서 `quarantined`를 빼도 같은
    문장은 여전히 `duplicate_hash`로 탈락한다(실증: 사유 코드만 보는 동안에는
    corpus에서 `quarantined`를 빼도 관련 테스트가 전부 통과했다). 관측
    요구를 **"탈락이 corpus 비교(11번)에서 났다는 것까지 단정한다"**로 고쳤고,
    두 경로를 갈라 보려면 backstop 쪽 탈락이 `detail`로 식별되어야 한다는
    조건을 명시했다. 그 식별 수단이 없으면 이 규칙은 **similarity(12번)로만**
    관측된다 --- near-copy에는 persistence 대응물이 없으므로 corpus만이 그것을
    거부할 수 있다. 구현은 backstop 탈락의 `detail`에 표식을 붙여 식별 수단을
    두었다(`jobs/persistence`); `detail` 형식은 명세가 규정하지 않는다
    (`rejected`의 **사유 코드** 집합만 `08_LLM_SPEC.md`가 canonical이다).
-   **[27] ADR-015가 달성 불가능한 것을 주장했다**
    (`ADR-015`의 `정적과 런타임의 분담`): "request를 보내는 **모든** 테스트가
    `no_outbound_network()` 안에서 돈다"는 참이 될 수 없다. 테스트 DSN이 unix
    socket이고 unix socket 연결도 그 헬퍼가 거부하는 `socket.socket.connect`를
    지나가므로, 요청이 새 pooled 커넥션을 여는 다중 커넥션
    fixture(`committed_api` --- job → worker → pool을 실제로 밟는 것들)는
    provider와 무관한 이유로 실패한다. 단일 커넥션 fixture에서 통하는 것은
    커넥션이 이미 열려 재사용되기 때문이다. 문구를 **단일 커넥션 fixture로
    한정**하고, fixture에 의존하지 않는 일반 메커니즘으로 별도 프로세스 검사
    (`test_a_fresh_api_process_loads_neither_the_provider_module_nor_the_sdk`)를
    지목했다.
-   **[28] "`sys.modules`에 적재되지도 않는다"는 in-process로 검사 불가능하다**
    (`12_TEST_PLAN.md` Integration 1건): provider 구현체 모듈을 절대 집합
    검사에 넣을 수 없다 --- 그 모듈을 직접 검사하는 테스트가 최상위에서
    import하므로 full run에서는 수집 시점에 이미 `sys.modules`에 있고, 넣으면
    모든 호출 지점이 영구히 실패한다. in-process 쪽은 **블록 전후 delta**("이
    요청이 `app.llm*`을 새로 적재했는가")로 관측하고 --- 이것이 `app/jobs/`가
    `app.llm`을 합법적으로 import해서 생기는 G4의 맹점도 덮는다 --- 문자 그대로의
    요구는 **별도 프로세스** 테스트가 받는다고 적었다. 이 문장이 없으면 다음
    사람이 절대 집합 헬퍼를 "고치고" provider 테스트의 top-level import를 지운다.

교차 참조·서술을 맞춘 문서: `09_BACKGROUND_JOBS.md`(cost 누적 + ceiling 제외
2개 bullet), `12_TEST_PLAN.md`(unit 1건 + integration 1건 문구 정정).
개정한 ADR: `ADR-015`(런타임 분담 문구 한정). 새 ADR은 없다 --- 네 건 모두
관측 가능성에 대한 사실 정정이거나 기존 canonical 절 안의 규칙 확장이다.

#### Wave 3 구현 보고 반영 --- target 수 상한의 출처 (같은 후속 보완)

구현·검증에서 드러난 **명세 내부 불일치 1건**을 고쳤다. 새 버전 번호를 만들지
않는다. **새 테이블·새 컬럼·새 config 키는 없고 구현 변경도 요구하지 않는다**
--- 코드가 맞고 명세 문구가 틀렸다.

-   **[29] validation 검사 5는 리터럴 숫자로, 검사 10은 config 키로 같은
    상한을 적고 있었다** (`08_LLM_SPEC.md`의
    `target 수 상한의 출처와 검사 10의 지위`가 canonical): 검사 5는 "target
    LearningItem 수 1\~2", 검사 10은 "신규 target item 수가 configured max 이하
    (`learning.max_new_items_per_sentence`)"였고,
    `06_LEARNING_ENGINE.md`는 **전체** target 수를 그 키에 묶는다. 리터럴을
    남기는 쪽은 택하지 않았다 --- 학습 정책값 하드코딩 금지에 어긋나고, 키를
    1로 낮추면 리터럴 "2"가 06의 규칙과 정면충돌한다(06은 전체 target 1개를
    요구하는데 08은 2개를 통과시킨다). 따라서 "1\~2"는 **기본값을 인라인으로
    적은 것**으로 판정하고, 검사 5를 "1 이상
    `learning.max_new_items_per_sentence` 이하(기본값 2)"로 고쳤다. 하한 1은
    config가 아닌 고정값으로 유지했다 --- target이 없는 문장은 어떤 candidate도
    만들지 못한다. 함께: 신규 target 수는 항상 전체 target 수 이하이므로 두
    상한이 한 키에서 오는 동안 **검사 10은 구조적으로 발화하지 않는다**는
    사실을 적었다(구현이 회귀 테스트로 고정해 둔 사실이다). 검사 10을
    지우지는 않았다 --- 두 검사가 세는 대상이 다르고(전체 target vs 신규
    target) 상한이 분리되면 즉시 유효해지는 backstop이며, 구현도 그래서 두
    상한을 별도 인자로 들고 있다(`app/llm/validation.py`의 `SentencePolicy`).
    **상한 분리는 MVP 범위가 아니다**; 분리하는 변경이 들어오면 그때 검사 10의
    handler 경로 테스트를 추가해야 한다는 조건만 적었다. 검사 번호는
    재배열하지 않았다 --- 다른 문서와 테스트가 번호로 참조한다.

교차 참조·서술을 맞춘 문서: `14_CONFIGURATION.md`(강제되는 값을 검사하는 곳이
5번과 10번 둘 다라는 사실 정정. `preferred_new_items_per_sentence`가 선호값이지
강제 상한이 아니라는 나머지 논지는 그대로다),
`06_LEARNING_ENGINE.md`(`role별 규칙`의 bullet 하나. 문장당 target 수 상한의
**생성 시점** 대응물을 10번이 아니라 **5번**으로 정정했다 --- 06의 규칙은 전체
target 수를 말하므로 신규 수를 세는 10번이 아니고, 10번이 발화하지 않는다고
명문화한 뒤에는 발화하지 않는 검사를 자기 대응물로 가리키게 된다. "둘은 같은
config 키를 쓰지만 적용 지점이 다르다"는 요지는 여전히 사실이므로 그대로 뒀다).
새 ADR은 없다 --- 명세 문구가 구현과 다른 절에 어긋난 것을 맞춘 사실 정정이며
새 설계 결정이 아니다.
