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

#### Wave 4 착수 전 반영 --- 프론트엔드 계약 공백 10건 (같은 후속 보완)

Wave 4(프론트엔드) 착수 전에 드러난 **명세 공백 10건**을 반영했다. 새 버전 번호를
만들지 않는다. **새 테이블·새 컬럼·새 config 키는 없다.** 모든 신설 계약을 기존
컬럼과 기존 endpoint에서 파생시켰고, `spec/future/`·루트 `spec/05`·`spec/06`은
건드리지 않았다.

-   **[30] `GET /api/history/*`에 응답 계약이 없었다** (`05_API_SPEC.md`의
    `History`가 canonical): `00_SCOPE.md`가 `기본 history`를 In Scope로 열거하는데
    endpoint 2개에 한 줄 설명만 있었고 응답 스키마·수용 기준·화면 정의·상한이 전부
    없었다. 수용 기준이 없다는 이유로 In Scope 항목을 빼지 않고 **최소 계약을
    확정하는 쪽**을 택했다. `GET /sessions`는 `study_sessions`의 여섯 컬럼 그대로 +
    `completed_sentence_count`(그 session의 `study_presentations` 중
    `completed_at IS NOT NULL` 행 수)다. `GET /items`는 **`user_item_learning_state`
    행을 목록 대상으로 잡고** `learning_items.lemma` / `type`,
    `user_mastery.comprehension_mastery`, `invalidated_at IS NULL`인
    `item_exposures` 행 수, `review_states.next_review_at`을 붙인다. 목록 대상을
    그 테이블로 정한 이유는 그 행이 **target으로 제시되었거나 explicit evidence를
    받았을 때만** 생겨서 "눌러만 보고 지나간 item"이 자동으로 빠지고, 따라서 새
    `learned` 플래그 컬럼이 필요 없기 때문이다. 버린 대안: `summary_json`을 읽는
    방식(MVP에 채우는 경로가 없다), `is_active_learning_target = true`만 담는
    방식(exploration item은 노출되어도 target이 아니라 빠진다). 상한은 **두
    endpoint 공통 고정 50**이고 pagination·기간 필터·정렬 옵션을 두지 않았다 ---
    `기본 history`에 cursor를 붙이면 정렬 키·경계·빈 페이지 계약이 따라 붙는다. 50을
    `14_CONFIGURATION.md`에 두지 않은 이유는 그것이 실사용으로 조정할 학습
    파라미터가 아니라 **응답 계약 상수**이기 때문이다(probe 문구, flag note 길이
    상한과 같은 취급). 함께: 인증 필수(익명 허용 목록은 그대로 2개), 대상 사용자를
    지정하는 파라미터를 받지 않음, 읽기 전용(`last_activity_at`을 건드리지 않음).
    `completed_at IS NULL`인 presentation을 세지 않는 이유는 idle timeout으로 닫힌
    session에 영원히 미완료로 남는 행이 있고 그것을 세면 **보지 않고 떠난 문장이
    학습 기록이 되기** 때문이다.
    **구현 보고로 같은 계약에 두 가지를 보완했다(새 번호를 만들지 않는다).**
    (i) 잘림 사실을 응답이 알릴 수 없었다 --- 명세가 "잘렸다는 사실은 화면이 문구로
    알린다"고 요구했는데 스키마에 플래그도 총 개수도 없어 client의 단서가
    `len(rows) == 50`뿐이었고, 그것은 **"정확히 50건인 사용자"와 구분되지 않아**
    경계에서 거짓을 말한다. 두 응답에 `truncated: bool`을 추가하고 판정 방법까지
    명세에 적었다: **상한 + 1건을 조회해 51번째 행의 존재로 판정하고 응답에는 50건만
    담는다.** `COUNT(*)`를 쓰지 않은 이유는 전체 개수를 화면이 쓰지 않는데 행이 많은
    사용자가 조회마다 전수 카운트를 치르기 때문이고, `total`을 노출하지 않은 이유는
    그것이 pagination을 만들라는 압력이 되기 때문이다(pagination 금지는 그대로다).
    `truncated`는 잘렸는지만 말하고 몇 건이 잘렸는지는 말하지 않는다 --- 그것을
    말하려면 `COUNT(*)`가 필요하다.
    (ii) **진행 중 session의 `active_seconds`가 멈춘 값이라는 사실을 기록했다.**
    history는 `touch()`를 부르지 않으므로 그 값은 마지막 학습 요청 시점의 것이고,
    화면이 `진행 중`으로 표시하므로 오해 소지는 작다. 고치지 않았다 --- 대신
    "**여기에 상태 변경을 추가하지 않는다**"를 못박았다. `GET /api/study/session`에
    같은 문장을 둔 것([31])과 **한 규칙**임을 적었다: 조회는 학습 시간을 만들지
    않는다. 이 문장이 없으면 다음 사람이 "학습 시간이 멈춰 보인다"를 버그로 보고
    history 조회에 `touch()`를 넣는데, 그것이 실제 버그다.
-   **[31] 진행바의 분모와 갱신 수단이 없었다** (`05_API_SPEC.md`의
    `진행 상태의 갱신과 세션 종료 판정`이 canonical): 분모
    `(target_minutes + extended_minutes) * 60`, 분자 `active_seconds`, 갱신은
    `/complete` 직후 `GET /api/study/session` 재조회(문장 단위)로 확정했다.
    **자동 폴링을 금지**하고 그 이유를 적었다 --- 상호작용 endpoint를 주기 호출하면
    모든 상태 변경 경로가 `touch()`를 지나므로 `active_time_idle_gap_seconds` 이하
    간격이 계속 생겨 **자리를 비운 시간이 학습 시간으로 누적된다.** 화면은 오히려
    매끄럽게 보이므로 이 오염은 눈에 띄지 않는다. 진행 표시가 **`GET /session`이
    `touch()`하지 않는다는 사실에 의존**하므로 그 사실과 "여기에 상태 변경을
    추가하지 않는다"를 명세에 못박았다. 세 값이 `/next`·`/complete` 응답에 없는
    것은 결함이 아니라 계약 분리이며(session payload vs presentation payload) 두
    계약에서 같은 값을 내면 최신성이 응답 도착 순서에 달린다.
    **F2 구현 보고로 `/finish` 직후 화면을 확정했다(같은 계약, 새 번호를 만들지
    않는다)**: `03_UI_UX_SPEC.md`의 `완료 화면`. 완료 문구 한 줄과 `active_seconds`로
    만든 학습 시간 한 줄로 끝나고 **새 세션 시작 버튼을 두지 않는다.** 그 버튼이 눌릴
    때마다 session 행이 하나 더 생겨 history의 세션 기록이 부풀고, "한 번 더 하시죠"라는
    압박으로 읽힌다 --- 후자는 `Session End`가 이미 금지한 overdue/streak punishment와
    같은 종류이므로 이 선택은 새 규칙이 아니라 그 금지의 **결과**다. 그래서 **막히는
    경로는 없다**는 것도 적었다: 다시 열거나 새로고침하면 `POST /api/study/session`이
    새 session을 만든다(방금 세션은 닫혀 있으므로 resume이 아니라 신규다). 사용자가
    명시적으로 다시 시작하는 것과 화면이 권하는 것을 구분하는 것이 요점이다. 숫자는
    `active_seconds` 하나이며 [32]의 "서버가 준 숫자만 화면에 쓴다"를 참조하게 했고,
    통계·streak·세션 요약은 넣지 않는다.
-   **[32] "세션 종료 도달"의 판정 주체가 없었다** (같은 절): 서버에 플래그를
    추가하지 않고 **client가 `active_seconds >= (target_minutes +
    extended_minutes) * 60`으로 파생**한다. 값 전부가 서버 것이므로 정책값
    하드코딩이 아니다. 반면 `default_session_minutes` / `extra_session_minutes`를
    frontend가 읽는 것은 하드코딩이므로 명시적으로 금지했다. 함께 못박은 것:
    **도달은 세션의 종료가 아니다.** session을 닫는 것은 `/finish` 하나이고, 도달
    뒤에도 `/next`와 상호작용이 허용되며 서버는 도달을 이유로 아무것도 거부하지
    않는다.
-   **[33] `explanation_revealed`의 시점이 없었다** (`05_API_SPEC.md`의
    `explanation_revealed를 언제 보내는가`가 canonical): "설명 패널/시트가 실제로
    렌더된 직후"로 확정하고, 두 event를 유지하는 이유를 적었다 --- click 응답이
    실패하거나(500/409/네트워크 단절) 사용자가 응답 전에 떠나면 `item_clicked`만
    남으므로 **"탭했으나 설명이 표시되지 않은 구간"이 관측된다.** 합치면 그 구간이
    사라지고 "tap 즉시 표시"가 지켜지는지 확인할 수단이 없어진다. 함께: 패널을
    접었다 다시 펴도 **presentation당 1회만** 보낸다(client key는 UUIDv4라 재전송
    때마다 새 event가 쌓여 raw history가 UI 조작 횟수를 세게 된다).
-   **[34] 학습 target span의 시각적 구분이 모호했다** (`03_UI_UX_SPEC.md`의
    `tappable span 표시`): "학습 대상 span을 subtle하게"가 대상만 표시하라는 뜻으로
    읽혔으나 `tappable_items` payload에는 target/incidental 구분 필드가 없다. 필드를
    추가하지 않고 **모든 tappable span을 같은 방식으로 subtle하게** 표시하도록 문구를
    명확히 했다. 근거 둘: 대상만 강조하면 그 문장에서 무엇이 평가 대상인지가 드러나
    같은 문서의 "지나치게 시험 문제처럼 보이지 않게"가 그 자리에서 무너지고,
    강조된 span만 눌려 **incidental click 경로가 사실상 사라진다** --- 그 경로가
    MVP에서 신규 학습 target이 생기는 주된 통로다(`02_LEARNING_POLICY.md`).
    target 여부는 `user_sentence_candidate_targets`가 가진 서버 측 사실이며 화면이
    알 필요가 없다.
-   **[35] 로그인 화면이 어느 UI 명세에도 없었다** (`03_UI_UX_SPEC.md`의 `Login`):
    `01_USER_FLOW.md`가 `Authentication check`를 요구하는데 화면 정의가 없었다.
    `login_id` / `password` 두 필드와 버튼 하나로 확정했다. 실패 문구는 **하나**다
    --- 401이 사유를 구분하지 않으므로 UI가 구분해 적으면 서버가 감춘 것을 알려준다.
    회원가입·재설정 진입점을 두지 않은 이유는 public signup이 없고 그 endpoint가
    MVP에 없어서다(`04_DB_SPEC.md`).
-   **[36] `timed_out_session_id` 표시 문구가 미정이었다**
    (`03_UI_UX_SPEC.md`의 `이전 세션 종료 안내`): non-null이면 한 번 사라지는
    안내를 띄운다("이전 세션은 오랫동안 활동이 없어 종료했습니다. 새 세션을
    시작합니다."). 경고·오류로 보이게 하지 않는다(사용자가 잘못한 것이 없고
    overdue/streak punishment 금지와 같은 취지). 지난 세션 복귀 동작을 제공하지
    않는 이유는 그 session이 이미 닫혀 남은 문장이 영원히 미완료이기 때문이다.
    내부 id 자체는 화면에 노출하지 않는다.
-   **[37] `content.translation_default_visible` / `reading_default_visible`을
    frontend가 읽을 경로가 없다** (`14_CONFIGURATION.md`): config를 지우지도 API를
    바꾸지도 않고 **사실만 기록했다.** 두 값이 기술하는 것은 API 구조가 이미
    강제한다 --- payload에 `korean_translation` 필드도 reading 필드도 없으므로 값이
    뒤집혀도 화면은 달라지지 않는다. 값을 넘기는 endpoint를 만들면 숨김 규칙의
    source of truth가 둘이 되고 그중 하나가 뒤집히는 사고가 가능해지므로, 두 키는
    정책 기록으로만 남기고 소비처를 만들지 않는다.

-   **[38] `+5분 더` 버튼의 숫자가 어떤 payload에도 없다**
    (`03_UI_UX_SPEC.md`의 `Session End`): `extend()`가 더하는 값은
    `learning.extra_session_minutes`인데 그 값은 `/extend`를 호출하기 **전** 어떤
    응답에도 실리지 않는다. 따라서 버튼에 `5분`을 쓰면 정책값 하드코딩이고, config를
    6분으로 바꾸면 화면은 계속 `5분`이라 말하고 서버는 6분을 더하는데 **아무 테스트도
    빨개지지 않는다.** API를 바꾸는 대신 **문구에서 숫자를 뺐다**: `오늘 학습 완료 /
    더 학습하기`. `StudySessionPayload`에 연장 폭을 노출하지 않은 근거는, 누르기
    **전에** 정확한 분 수를 보여야 한다고 요구하는 조항이 어디에도 없고 세션 길이
    자체를 `오늘 약 12분`으로 근사 제시하는 문서 전체의 어조와도 어긋나지 않는다는
    것이다. 함께 규칙을 한 줄로 세웠다 --- **"서버가 준 숫자만 화면에 쓴다."**
    `오늘 약 12분`이 허용되는 이유는 그것이 `target_minutes`로 내려오기 때문이고,
    연장 폭이 금지되는 이유는 내려오지 않기 때문이다. 두 문구의 처리가 갈리는 것은
    그 한 규칙의 결과다. `01_USER_FLOW.md`와 `spec/03_DOMAIN_MODEL.md`의 `+5분`은
    config 기본값을 가리키는 서술이므로 고치지 않았고, 화면 문구를 인용하던
    `05_API_SPEC.md`의 한 줄과 endpoint 요약의 `+5분 연장`만 맞췄다(요약은
    `extra_session_minutes 만큼 연장`으로 고치고, 그 값이 호출 전에는 응답에 없다는
    사실을 한 단락 추가했다).
-   **[39] 세션 쿠키 속성이 배포 토폴로지를 제약한다는 사실이 기록되지 않았다**
    (`spec/04_SECURITY_AND_DATA.md`의 `배포 도메인 가정` 아래
    `쿠키 속성이 배포 토폴로지에 요구하는 조건`): **기록만 했다. ADR-004를 고치지
    않았고 쿠키 속성도 바꾸지 않았다.** `__Host-nc_session`은 `Secure` +
    `HttpOnly` + `SameSite=Strict` + host-only이며 이 속성들은 설정값이 아니므로
    배포가 여기에 맞춰야 한다. 귀결 넷: `SameSite=Strict`는 site가 다른 요청에
    cookie를 싣지 않고 `credentials: 'include'`로 우회되지 않는다(`include`는
    same-site 요청에 cookie를 싣게 하는 것이지 `SameSite` 판정을 바꾸지 않는다);
    `__Host-` prefix가 `Domain`을 금지하므로 cookie는 API 호스트 전용이다;
    따라서 frontend origin과 API origin이 **same-site이고 둘 다 https여야** 하며
    `app.example.com` + `api.example.com`은 동작하지만 무료 호스팅 공용
    도메인(`*.workers.dev` 등) + 별도 도메인 조합은 **구조적으로 동작하지
    않는다**; 그 위에 frontend origin이 `CORS_ALLOW_ORIGINS`에 없으면 상태변경
    요청이 막힌다. 실제 도메인 값은 명세가 정하지 않고 `infra/`에 고정하지 않는다
    --- 도메인·DNS·정적 호스팅은 배포 절차의 몫이다. Wave 5 배포 문서가 참조할
    자리를 위해 기존 `배포 도메인 가정` 바로 아래에 두었다.

교차 참조·서술을 맞춘 문서: `03_UI_UX_SPEC.md`(`Login` / `진행 표시` /
`세션 시작 안내`(resume 포함) / `tappable span 표시` / `History` 신설(`truncated`로만
잘림 문구를 띄운다는 한 줄 포함) / `완료 화면` 신설, `Session End` 문구
변경 + 판정 절 참조, `Explanation`에 event 시점 참조 한 줄),
`13_ACCEPTANCE_CRITERIA.md`(history 수용 기준 2건 --- 자기 데이터만 + 잘림 구분),
`12_TEST_PLAN.md`(history integration 3건 --- 자기 데이터만 / `truncated` 경계
양쪽 / 조회가 `active_seconds`를 움직이지 않음), `14_CONFIGURATION.md`([37] 한 단락),
`spec/04_SECURITY_AND_DATA.md`([39] 한 절. `spec/00~06`은 이 한 곳만 건드렸고
`spec/05`·`spec/06`과 `spec/future/`는 손대지 않았다).

새 ADR은 없다. history 응답 계약이 ADR 후보였으나 **되돌리기 비싼 결정이
아니다** --- 새 테이블·컬럼·config 키가 없고 저장 상태를 만들지 않는 읽기 전용
계약이라, 목록 대상·상한·필드 구성을 바꾸는 것은 `05_API_SPEC.md`의 `History` 절
하나를 고치는 일이다(마이그레이션도 데이터 변환도 없다). 버린 대안과 근거는 그 절과
위 [30]이 이미 담고 있다. [31]\~[34]도 같은 성질이며 [35]\~[38]은 문구 정정,
[39]는 기존 결정(ADR-004)의 귀결 기록이다.

같은 item에 대한 두 번째 self-report의 처리는 이 묶음에서 보고만 하고 명세를 고치지
않았다. 결정이 내려져 **아래 `#### 노출당 evidence 1건`에서 확정했다.**

#### 노출당 evidence 1건 --- self-report 이중 적용 차단 (같은 후속 보완)

위 묶음에서 미해결로 남겼던 건을 확정했다. **새 테이블·새 컬럼·새 config 키는 없다.**
다만 이것은 문구 정정이 아니라 **Wave 2 서버 동작의 변경을 요구하는 규칙 확정**이므로
`docs/decisions/ADR-018-evidence-per-exposure.md`를 남겼다.

-   **[40] `(presentation, learning_item)`당 explicit evidence 상한이 없었다**
    (`07_SRS_SPEC.md`의 `노출당 evidence 1건`이 canonical, HTTP 계약은
    `05_API_SPEC.md`의 `노출당 evidence 상한`): 구현은 같은 item에 대한 두 번째
    self-report를 `client_event_id`만 다르면 두 번 다 적용해 EMA를 두 번 돌리고
    `reps`를 두 번 올렸다. 명세에 금지 조항이 없었고, 반대로 `05_API_SPEC.md`는
    probe에 대해 "probe 하나에 응답은 최대 1건"을 이미 canonical로 못박고 있었다 ---
    **같은 EMA·같은 FSRS mapping·같은 위험인데 한쪽만 막혀 있던 비대칭**이 이 결정의
    출발점이다. 확정: 상한 1건, 서버가 강제, 2회차는 **409**, event도 부수효과도
    기록하지 않는다. 단위는 **`learning_item`**이다(`sentence_item` 단위로 세면 한
    문장에 같은 `learning_item`을 가리키는 `sentence_item`이 둘일 때 뚫린다). 세는
    집합은 self-report 3종 + probe 응답 3종이며 `mastery_probe_skipped`는 제외한다
    --- **새 목록을 만들지 않고** `07_SRS_SPEC.md`의 `No-signal review`가 이미
    `신호 있음`으로 열거한 그 6개를 참조하게 했다(같은 집합을 두 곳에 적으면 한쪽만
    고쳐지는 순간 무신호 판정과 evidence 상한이 서로 다른 것을 센다). **두 경로를
    합쳐 세는 이유**: probe 후보는 그 presentation의 target item이므로 item X에
    `알고 있었음`을 self-report한 뒤 같은 X의 probe에 `몰랐음`을 답하는 순서가
    실제로 성립하고, `probe_id` 기준 제한은 `probe_id`가 다르지 않아 이 경로를 막지
    못한다. 검사 10처럼 구조적으로 죽은 경로가 아니다.
-   **판정 순서를 명시했다**(`05_API_SPEC.md`의 `판정 순서`): 소유권 404 -> 상태
    게이트 409 -> **재전송 멱등성** -> evidence 상한 409 -> 그 밖의 검증. 멱등성이
    상한보다 **먼저**여야 한다 --- 뒤집으면 성공한 self-report의 네트워크 재시도가
    자기가 만든 evidence에 걸려 409를 받고 client가 성공을 실패로 읽는다.
    `공통 규칙`의 "재전송 시 동일 결과를 반환한다"가 canonical이므로 그쪽이 이긴다.
    같은 이유로 `probe-response`의 **probe 응답 1건 제한은 지우지 않았다** --- skip
    포함 여부와 결과(기존 응답 200)가 달라 새 상한과 겹치되 같지 않고, 재전송
    멱등성을 담당하는 쪽이 그것이다. 두 규칙의 관계를 표로 적었다.
    **구현 보고로 그 표를 사실에 맞춰 세 곳 고쳤다(새 번호를 만들지 않는다).**
    (i) `probe_id` 유효성 400을 상한 **뒤**(5번)에 두었으나 `/probe-response`는
    판정 키를 그 probe event에서 꺼내므로 event가 유효하지 않으면 상한을 판정할 키
    자체가 없다 --- **선택이 아니라 구조이고 순서를 바꿀 방법이 없다.** 400을 상한
    앞으로 옮기고 그 이유를 적었다(기존 테스트가 이미 그 동작을 고정한다).
    (ii) probe 제한의 **판정 키를 `probe_id`로 적었으나 실제 키는
    `(presentation, learning_item)`이다.** 사실대로 고치고, `mastery_probe_shown`의
    자연키가 `(presentation, learning_item)`당 하나이므로 **현재 두 표현이 같은
    결과를 낸다**는 것과 **자연키가 바뀌면 갈라진다**는 것(`probe_id` 기준이면 두
    번째 probe에 답할 수 있고 쌍 기준이면 막힌다)을 명시했다. 문서와 코드가 문자
    그대로는 다르지만 그 차이가 현재 도달 불가능한 사례이며 선례로 `08_LLM_SPEC.md`의
    `target 수 상한의 출처와 검사 10의 지위`를 가리켰다. **판정 키가 같아지므로 두
    규칙이 왜 둘인지를 한 문장으로 못박았다** --- 갈라 두는 근거는 키가 아니라
    **`skip` 포함 여부와 결과**다(probe 제한은 skip 포함·200·멱등성, 상한은 skip
    제외·409·이중 평가 차단). `Mastery Probe` 절의 기존 문장은 그대로 두고 실제 키를
    가리키는 한 줄만 덧붙였다 --- 두 곳이 말없이 어긋나면 안 된다.
    (iii) `client_event_id` 충돌 409가 순서표에 빠져 있었다. 구현된 순서(상한이 key
    충돌보다 앞)를 넣고 **그 순서가 의도된 것임을 확인했다** --- 두 409가 동시에
    성립할 때 상한이 "재시도하지 말라"는 종결 답이므로 먼저 주는 것이 유용하고, 뒤집으면
    client가 새 UUID로 재시도한 뒤 결국 상한 409를 받아 왕복만 한 번 는다. **구현
    변경은 필요하지 않다.**
    함께 `재전송 멱등성` 서술을 사실에 맞췄다: 구현은 순서로가 아니라 **상한 검사가
    요청이 들고 온 `client_event_id`를 제외하는 것**으로 멱등성을 지킨다. "멱등성을
    먼저 판정한다"는 서술로는 부족하다 --- 제외 조건이 없으면 순서를 뒤집어도 상한이
    방금 만든 자기 행을 센다.
-   **409 사유를 구분했다**(`05_API_SPEC.md`의 `409 사유 구분`): 새 코드 체계를
    만들지 않고 **기존 방식(응답 body의 사유 문구가 곧 사유 코드)** 을 따랐다. 네
    가지 409(session 종료 / presentation 완료 / `client_event_id` 재사용 / 이 노출에
    이미 evidence)와 각각의 client 동작을 표로 적었다. **복구 동작이 세 종류**라는
    것으로 정리했다: 앞의 둘은 화면 상태가 어긋난 것이라 session 재획득,
    `client_event_id` 충돌은 **새 UUIDv4로 재시도하면 성공할 수 있고**(영구 상태가
    아니다), evidence 상한은 **어떤 재시도도 성공하지 못하므로** "이미 기록했습니다"로
    끝내야 한다. 넷을 합치면 client가 무한 재시도(상한을 충돌로 오해), 불필요한 세션
    재획득(상한을 게이트로 오해), 또는 복구 포기(충돌을 상한으로 오해)를 한다. 표에
    `판정 순서`의 단계 번호를 함께 실어 두 표가 대조되게 했다.
-   **DB 강제 수단을 명시했다**(`04_DB_SPEC.md`의 `learning_events`). 구현이 뒤이어
    `uq_learning_events_evidence` = `UNIQUE (study_presentation_id,
    learning_item_id) WHERE event_type IN (explicit evidence 6종)`을 추가했고 그것을
    형제 테이블과 같은 `유일성:` + 조건 코드블록 + 이유 3단 구조로 반영했다.
    **partial이어야 하는 이유**: full unique면 한 노출에 event를 2건 이상 남길 수 없어
    `item_clicked` / `explanation_revealed` / `mastery_probe_shown`이 전부 막힌다.
    predicate의 6종은 **목록을 이 문서에 다시 적지 않았다** --- `07_SRS_SPEC.md`가
    canonical이고, 같은 집합을 두 곳에 적으면 index가 세는 것과 명세가 세는 것이
    갈라진다(`07_SRS_SPEC.md`에서 목록 재열거를 거부한 것과 같은 규칙이다).
    `mastery_probe_skipped`가 predicate에 없는 이유도 적었다 --- 한 노출에 skip과
    evidence가 함께 있는 것이 정상이므로 넣으면 그 정상 상태가 제약 위반이 된다
    (구현의 변이 실험이 확인했다: 넣으면 기존 테스트 3건이 빨개진다). 범위에
    `user_id`를 넣지 않은 이유(`study_presentation_id`가 이미 한 사용자에 속한다.
    `item_exposures`와 같은 형태다), **애플리케이션 검사를 대체하지 않는다는 것**(정상
    경로는 기록 **전** 조회로 event를 애초에 남기지 않고, index는 경합의 마지막
    방어선이며 **진 요청도 같은 409**를 받는다 --- 그 판별 때문에 index 이름이 구현에서
    상수다), **위반 행을 정리하는 migration 단계를 두지 않는다는 것**(immutable raw
    history에서 행을 지우는 것은 "사용자가 그렇게 답하지 않았다"는 없는 사실을 만드는
    것이고, 두 행 중 무엇을 남길지 고르는 판단도 migration이 할 일이 아니다. 위반 행이
    있으면 migration은 실패한다)까지 함께 적었다. `12_TEST_PLAN.md`에 동시 self-report
    2건 integration 항목을 추가하면서 **이 불변식이 갓 만난 item에서만 우연히 보호되고
    있었다**는 사실을 기록했다 --- 경합에서 진 요청이
    `uq_user_mastery_user_id_learning_item_id` 위반으로 넘어지고 그 롤백이 중복
    evidence를 함께 지웠기 때문이며, `user_mastery` / `user_item_learning_state` /
    `review_states` 행이 **이미 있는 item**(= 복습 중인 모든 item)에서는 그 우연이
    성립하지 않아 evidence 2건이 커밋된다. **시간이 지나면 대다수가 되는 경로가 뚫려
    있었다.** 그래서 이 index를 "다른 제약이 이미 막고 있다"는 이유로 지우면 안 된다.
    R1의 flush 순서 우연([41])과 같은 성격의 기록이다.
-   **read-or-create의 알려진 한계를 기록했다**(`10_ERROR_HANDLING.md`의
    `DB Failure`). 고치지 않았다. 사용자별 학습 상태 행을 만드는 경로가 SELECT 후
    INSERT이므로 같은 item에 **`skip`과 self-report가 동시에** 도착하면 한쪽이
    `user_item_learning_state` 중복 INSERT로 **500**을 받을 수 있다. evidence끼리의
    경합은 새 index가 직렬화하지만 skip은 evidence가 아니라 상한에 걸리지 않는다.
    **데이터 오염이 아니라 가용성 문제다** --- 제약이 오염을 이미 막으므로 잃는 것은 그
    요청 하나다. 해법 방향(`ON CONFLICT DO NOTHING`, `services/events.py`가 event
    기록에 이미 쓰는 방식)까지 적어 두어 나중에 이 증상이 보고되면 원인을 다시 찾지
    않게 했다.
-   **정정은 지원하지 않는다**(`07_SRS_SPEC.md`의 `정정은 하지 않는다`). 덮어쓰기는
    MVP 범위 밖이다 --- EMA 역함수에 필요한 직전 `old`가 `user_mastery`에 없고
    (현재값만 갖는다) `Card` 복원에 필요한 review 전 상태도 `review_states`에 없다.
    직전값 컬럼이나 `learning_events` replay가 선행 조건이고 둘 다 새 스키마·새
    기능이다. 대신 두 오입력의 **비대칭**을 근거로 남겼다: `몰랐음` 오입력은
    `Again`이라 다음 노출이 곧 와 스스로 교정되고, `알고 있었음` 오입력은 교정되지
    않지만 minimum exposure를 채우기 전까지 `reinforcement`로 계속 돌아오므로 영구
    손실은 아니다.

교차 참조·서술을 맞춘 문서: `02_LEARNING_POLICY.md`(`evidence_count`가 한 노출에
최대 1회 오른다는 두 줄 + canonical 참조), `13_ACCEPTANCE_CRITERIA.md`("같은 노출이
두 번 평가되지 않음"을 독립 항목으로 올려 노출 **전체**에 적용됨을 명시. 기존 상태
게이트 항목에서 그 괄호를 떼어 두 항목의 범위를 갈랐다),
`12_TEST_PLAN.md`(integration 3건 --- self-report 2회차 409 + 같은 `client_event_id`
재전송은 204, self-report 뒤 probe 응답 409 + skip 뒤 self-report는 성공 + 성공한
probe 응답 재전송은 200, 동시 self-report 2건 + 우연 기록),
`04_DB_SPEC.md`(`learning_events`의 `유일성:` 절),
`10_ERROR_HANDLING.md`(read-or-create 한계 한 단락).

새 ADR: `ADR-018-evidence-per-exposure.md`. history 계약([30])과 달리 **되돌리기가
비싸다** --- 서버 동작 변경이고, 나중에 정정을 허용하려면 직전값 컬럼이나 event
replay가 필요해 스키마가 따라 움직인다. 버린 대안 네 개((a) 현행 유지 + 프론트
잠금, (b) 덮어쓰기, (c) 조용히 204, (d) `sentence_item` 단위)와 (b)가 왜 범위
확대인지를 그 문서에 보존했다. 번호는 `docs/decisions/`를 확인해 최대값 017 + 1로
잡았다(파일 목록과 함께 `ADR-018`/`ADR-019`를 미리 참조하는 문서·코드가 없음도
확인했다 --- 번호만 예약된 경우를 잡기 위해서다). **구현 보고 후 그 문서 안에서
근거 세 곳을 사실에 맞췄다**(새 ADR을 만들지 않았다): 멱등성 우선이 순서가 아니라
제외 조건으로 성립한다는 것, probe 제한의 판정 키가 상한과 같고 갈라 두는 근거는
skip과 결과라는 것, `probe_id` 400이 구조적으로 상한보다 앞이라는 것. 409 사유 bullet도
네 사유·세 복구 동작으로 맞췄다. self-report -> probe 경로를 probe 제한이 막지 못하는
이유도 "`probe_id`가 다르지 않아서"가 아니라 **"probe 응답 event만 보므로 앞선
self-report를 보지 못해서"**로 정정했다. DB index가 추가된 뒤 `근거`에 **강제 수단이
둘이고 둘 다 필요하다**는 bullet을 하나 더 넣었다 --- ADR이 "프론트 잠금으로는
부족하다"고 말한 것과 같은 논리를 한 단계 더 적용한 결과이므로 새 결정이 아니고,
그래서 새 ADR을 만들지 않았다.

#### 열린 presentation 불변식의 DB 강제 수단 (같은 후속 보완)

**구현이 먼저 닫고 명세가 따라간 건이다.** 위 [40]과 무관한 별건이며 ADR을 만들지
않았다 --- 명세가 이미 선언한 불변식에 강제 수단을 명시하는 것이고 새 결정이 아니다.

-   **[41] `study_presentations`에 partial unique index 블록이 없었다**
    (`04_DB_SPEC.md`의 `study_presentations`): `04_DB_SPEC.md`와
    `05_API_SPEC.md`가 "한 `study_session_id`에 `completed_at IS NULL`인 row는 최대
    1개"를 선언하는데 그것을 강제하는 인덱스가 명세에도 DB에도 없었다. 형제
    테이블은 자기 partial unique index를 적는다(`user_sentence_candidates`의
    `UNIQUE (user_id, sentence_id, presentation_role, context_stage) WHERE status IN
    ('queued', 'ready')`, `prompt_versions`의 `UNIQUE (task_type) WHERE active`).
    같은 `유일성:` + 코드블록 형태로 `UNIQUE (study_session_id) WHERE completed_at
    IS NULL`(이름 `uq_study_presentations_open`)을 불변식 문단 바로 뒤에 적었다.
    **partial이어야 하는 이유**: full unique로 만들면 `study_session_id`가 한 행에만
    존재할 수 있어 한 세션에 문장을 하나밖에 보여줄 수 없다. **범위가 session
    하나인 이유**: idle timeout으로 만료된 session은 미완료 presentation을 남기는
    것이 정상이므로(`_expire_idle_session`) `user_id`로 넓히면 그 정상 상태가 제약
    위반이 된다. 애플리케이션 검사를 대체하지 않는다는 점도 적었다 --- `/next`는
    여전히 열린 presentation을 조회해서 **그것을 반환**해야 하고 index는 경합 시의
    마지막 방어선이다.
-   `12_TEST_PLAN.md`에 동시 `/next` 2건 integration 항목을 추가하면서, 이 불변식이
    그때까지 **ORM flush 순서의 우연**에 기대고 있었다는 사실을 함께 적었다.
    `touch()`가 session 행을 dirty로 만들면 autoflush가 열린 presentation 조회보다
    먼저 UPDATE를 내보내 행 락으로 직렬화되는데, **두 요청의 `now`가 같으면**
    SQLAlchemy가 "unchanged"로 판정해 UPDATE를 내보내지 않아 창이 열린다. 한 요청이
    시각을 한 번만 읽는 clock 규율(ADR-007) 아래서 동일 `now`는 정상이므로 **clock
    규율이 이 우연을 더 자주 깨는 방향으로 작용한다.** 사후 발견이 어려운 종류라
    적어 두었다 --- 나중에 누가 index나 락을 "불필요해 보인다"고 지우면 그 항목이
    무엇을 지키는지 알 수 있어야 한다.

`05_API_SPEC.md`는 변경하지 않았다. `열린 presentation 불변식` 절이 이미 "`/next`는
열린 presentation이 있으면 새로 만들지 않고 그것을 그대로 반환한다"를 적고 있어 추가할
것이 없다(확인만 했다).

#### Wave 4 게이트 반영 --- candidate 수명과 로그아웃 진입점 (같은 후속 보완)

Wave 4 게이트에서 `learning-verifier`가 코드에서 재구성한 candidate 수명
메커니즘과, 구현돼 있으나 도달 불가능한 endpoint 하나를 반영했다. 새 버전 번호를
만들지 않았다. 6건 중 3건이 실질(A-1/A-2/A-3)이고 3건은 **해석의 기록**이다.

확인된 사실 관계부터 적는다(아래 [42]\~[44]가 모두 여기서 나온다).
`selection.py`의 `_review_plans`는 그 시점의 `state.context_stage`로 candidate를
만들고 이미 만들어 둔 candidate를 다시 보지 않는다. 유일성 index는
`status IN ('queued', 'ready')`만 덮으므로 candidate가 `shown`인 동안
materialization이 돌면 같은 `(user, sentence, review, stage)`의 두 번째 행이
생긴다. 그 경로는 실재한다 --- `POST /api/study/session`이 신규·resume 양쪽에서
명세대로 materialization을 1회 실행하고 브라우저는 문장이 열린 상태에서 그것을
부르므로, **문장 도중 새로고침 한 번이 중복 candidate를 만든다.** `_select_review`에
stage 필터가 없고 같은 item의 두 candidate는 `order_key`가 같으므로
`min((order_key, candidate_id))`가 **더 오래된 쪽**을 고른다.

**이것은 명세 위반이 아니다.** `07_SRS_SPEC.md`의 `전이 규칙`과 ADR-012의 근거
(4)가 "Ready Pool에 남아 있던 낮은 stage candidate"를 명시적으로 전제하고
`max`/`min`이 그래서 존재한다. 최소 노출 정의도 "단순 횟수"이지 "서로 다른
문맥"이 아니다. 그러므로 아래 세 건은 **버그 수정이 아니라 비어 있던 규정을
채우는 것**이며, 그 사실을 각 문서에 적었다.

-   **[42] "동시에 두 개 이상의 review candidate를 만들지 않는다"의 status 범위가
    없었다** (`06_LEARNING_ENGINE.md`의 `review candidate: reason 판정`):
    `ready`만인가, `shown`도 포함인가, 한 실행 안만인가가 정의되지 않았다. 구현이
    보장하는 것은 **한 실행 안에서 item당 reason 하나**뿐이다. 문장을 그 범위로
    정확히 하고(`**한 materialization 실행 안에서**`), `이 제약의 범위 (MVP 확정)`
    소절을 새로 넣어 보장하는 것과 보장하지 않는 것을 갈라 적었다. **`shown`
    candidate가 남아 있는 동안 새 candidate가 생기는 것은 정상**임을 명시했고,
    ADR-010이 `shown / consumed / quarantined / expired`를 index에서 **일부러**
    제외했으므로 이 문장을 근거로 index 범위를 넓히지 않는다는 금지도 함께 적었다.
    적지 않으면 다음 사람이 이 문장을 근거로 index를 넓혀 ADR-010이 지키려던
    재사용 가능성을 깬다.
-   **[43] `expired`에 writer가 없었다** (`04_DB_SPEC.md`의
    `user_sentence_candidates`, `06_LEARNING_ENGINE.md`의 `공통 필드`):
    값만 있고 쓰는 주체·시점이 어느 문서에도 없었고, stage가 오른 뒤 남은 하위
    stage `ready` candidate를 어떻게 할지 규정도 없었다. **만료시키지 않는 쪽을
    채택했다** --- 그 candidate를 보여줘도 ladder는 되돌지 않고(`max`) 노출 카운트도
    정확하며, `Pool Fallback` 2단계가 바로 그런 anchor/near-original reinforcement
    노출을 **의도적으로** 허용하므로 만료 규칙은 그 fallback을 예외로 파야 하는
    **새 정책**이 된다. 대신 `queued`를 다룰 때와 **같은 방식으로** 처리했다:
    값과 index 조건은 남기고, MVP에서 쓰지 않는다는 것과 **언제 유효해지는지**
    (candidate 수명 정책이 생기는 시점)를 적었다. `06` 쪽에는 한 단락으로 같은
    사실을 적고 canonical을 `04`로 가리켰다 --- 적지 않으면 다음 사람이 `06`에서
    규칙을 발명한다.
-   **[44] candidate 단위 tie-break가 없었다** (`06_LEARNING_ENGINE.md`의
    `Review Ordering`): 기존 1\~4는 **item 단위** tie-break만 정했고 같은 item에
    candidate가 여럿일 때를 정하지 않아, 실질적으로 candidate id ASC(= 가장
    오래된 것)가 규칙이었다. 이것이 [42]의 중복과 곱해지면 최소 노출이 실제 ladder
    위치보다 낮은 stage로 기울고, 극단에서 ADR-012가 **결함이라 부른 상태**("최소
    5회가 전부 동일 anchor 문장")에 가까워진다. `candidate 단위 tie-break (MVP
    확정)` 소절로 5\~6번을 추가했다: **`state.context_stage`와 일치하는 candidate를
    먼저**, 그다음이 기존 규칙. **배제가 아니라 선호**이므로 일치하는 것이 없으면
    낮은 stage candidate를 그대로 고르고, 그래서 `Pool Fallback` 2단계가 명시적으로
    허용한 노출을 막지 않는다 --- 그 단계는 "그런 candidate가 있는가"를 보고 이
    규칙은 "둘 다 있을 때 무엇을 먼저 보는가"만 정한다. 사라지는 것은 "가장
    오래된 candidate가 먼저"라는 암묵 순서뿐이고 그것을 요구하는 조항은 없었다.
    stage **거리**로 정렬하지 않는 이유(새 정책이 된다)도 적었다.
    `12_TEST_PLAN.md`의 Unit에 이 규칙의 항목을 하나 넣었다 --- 선호와 배제가
    갈리는 지점(일치하는 candidate가 없을 때)까지 단정한다.

새 ADR: `ADR-019-stale-review-candidates.md`. [42]\~[44]가 한 메커니즘의 세 면이고
**되돌리기가 비싸다** --- 선택 동작 변경이며, 버린 대안 (a)만료·(b)배제는 각각
`expired`에 writer를 만들거나 `Pool Fallback` 2단계에 예외를 파므로 나중에
그쪽으로 돌아가려면 정책 문서 여러 곳이 함께 움직인다. 버린 대안 네 개
((a) 만료, (b) 선택 단계 배제, (c) index를 `shown`까지 확장, (d) 현행 유지)와 왜
(2)번 증상만 고치면 충분한지를 그 문서에 보존했다. 번호는 `docs/decisions/`의
**파일 목록**으로 최대값 018 + 1을 잡았다 --- 이 문서 위쪽 [40] 서술에 `ADR-019`를
미리 언급하는 산문이 있어 grep으로는 오탐이 난다.

**구현 변경이 필요한 것은 [44] 하나다.** [42]와 [43]은 구현이 이미 하고 있는 것을
적었을 뿐이다. 변경 지점은 `backend/app/learning/selection.py`의 `_select_review`
이며, `_load_review_targets`가 `UserItemLearningState.context_stage`를 함께
읽어(현재는 `ReviewState` + `UserMastery`만 읽는다) bucket에 넣는 정렬 키를
`(order_key, candidate_id)`에서 `(order_key, stage_mismatch, candidate_id)`로
넓히는 형태다. 이 보완은 명세만 고쳤고 `backend/`·`frontend/`는 건드리지 않았다.

**구현자가 멈추고 보고해서 [44]의 규칙 5를 두 곳 확정했다**(같은 절 안. 새 항목도
새 ADR도 만들지 않았고 `ADR-019`의 Decision 블록만 같은 내용으로 맞췄다). 원인은
내가 **"candidate 하나가 item 하나에 속한다"는 전제**를 검증하지 않고 규칙을 쓴
것이다. 그 전제는 거짓이다 --- `_create_candidates`가 plan을
`(sentence_id, context_stage)`로 묶어 `max_new_items_per_sentence`까지 target을
붙이므로 review candidate도 target을 2개 가질 수 있고(DB probe: `candidate 3 anchor
[1, 2]`), `services/presentation.py`의 `_advance_context_stages`가 `몰랐음`을
**item별로** 판정하므로 2-target presentation 하나에서 두 target의 `context_stage`가
그 자리에서 갈린다. 우연이 아니라 구조다. 그래서 규칙 5의 판정 대상이 정해지지 않은
동안 세 해석(아무 target이나 일치 / order key를 지배한 target / 모든 target이 일치)이
**하필 이 규칙이 겨냥한 시나리오에서** 서로 다른 답을 냈다.

-   **판정 대상 = dominant target**(= 그 candidate의 usable target 중 order key가
    최소인 target). 근거는 내가 규칙 5를 "1\~4의 동률에서만 적용된다"고 못박은
    문언이다 --- 그 동률을 만든 target이 곧 5번이 말하는 item이다. 버린 해석 둘의
    귀결도 절에 적었다: "아무 target이나 일치"는 낡은 `anchor` candidate가 동승자
    덕분에 항상 일치로 판정되어 **규칙이 존재하는 이유를 없애고**, "모든 target이
    일치"는 ladder가 갈린 multi-target candidate를 사실상 **배제**한다(배제는 이
    규칙이 하지 않기로 한 것이다). 아직 구현되지 않은 규칙의 해석 확정이므로 구현
    변경을 부르지 않는다.
-   **1\~4를 target이 여럿인 candidate에 올리는 방법을 명세에 고정했다.**
    `candidate의 order key = usable target들의 order key 최소값`이고 `usable target`의
    정의(1번 통과 + `fsrs_due`면 실제 due)도 함께 적었다. 이것은 **현행 동작을 적은
    것이다** --- 그때까지 `selection.py`의 코드 주석에만 있었고 명세에는 없었다. 규칙
    5가 그 위에 얹히므로 둘을 함께 고정해야 한다. 근거는 한 줄이다: candidate는
    통째로 제시되므로 가장 급한 target이 그 candidate가 언제 보여야 하는지를 정한다.
    최대값·평균은 급한 target을 덜 급한 동승자 때문에 밀리게 한다. **구현 변경 없음.**
-   함께 발견된 **reason 병합**(같은 `(sentence, stage)`의 두 번째 plan이 candidate를
    만들지 않고 target만 붙으므로 그 target의 reason이 사라진다)은 **이번에 명세를
    고치지 않았다.** 분석만 해서 coordinator에게 올렸다 --- 결론은 노출 자체는 손실되지
    않고(병합된 candidate가 그 target을 실어 `item_exposures`를 만든다)
    `reinforcement_min_share_of_review`는 **지표만** 어긋난다는 것이다. 결정은
    coordinator가 한다.

#### 로그아웃 진입점 (같은 후속 보완)

-   **[45] 로그아웃 화면이 명세에 없었다** (`03_UI_UX_SPEC.md`의 `로그아웃` 신설):
    `POST /api/auth/logout`이 `05_API_SPEC.md`의 계약에 있고 `backend/app/api/auth.py`
    에 구현돼 있는데 `03_UI_UX_SPEC.md`의 화면 목록에 진입점이 없어 프론트엔드가
    호출하지 않는다. 귀결은 기기를 분실·공유했을 때 30일 cookie를 브라우저에서
    폐기할 수단이 없고 폐기 경로가 DB 직접 조작뿐이라는 것이다. **범위 확대가
    아니라 `00_SCOPE.md`의 `개인 로그인`을 닫는 것**이므로 추가했고, 그 판단
    근거를 절 안에 적었다. 최소로 정의했다 --- 사이드바 `학습 기록` 아래 버튼
    하나, 누르면 `POST /api/auth/logout` 후 Login 화면, **확인 대화상자 없음**
    (잃는 것이 없고 되돌리는 비용이 로그인 한 번이다). 함께 적은 경계 셋:
    `logout`이 폐기하는 것은 auth session이므로 **진행 중인 study session을 닫지
    않고** 다시 로그인하면 idle timeout 이내면 resume된다, 실패 시 로그인 화면으로
    보내지 않되 **`401`은 성공과 같게 처리**한다(폐기할 세션이 이미 없다는 뜻),
    Demo에는 두지 않는다(Login을 지나지 않는다). **통계·계정 관리·설정 화면은
    만들지 않았고** `History`의 `설정`이 MVP 화면이 아니라는 조항은 그대로 두었다.
    **구현 보고 후 같은 절 안에서 두 곳을 정정했다**(새 항목을 만들지 않았다).
    (1) 위치를 `사이드바, 학습 기록 아래`로 적었는데 **이 프론트엔드에 사이드바가
    없다** --- 모바일 한 손 조작을 우선한 단일 컬럼이고, mockup 사이드바의 나머지
    항목은 같은 문서가 이미 MVP 화면에서 뺐다. 없는 구조를 가리키는 명세는 그대로
    읽은 사람에게 사이드바를 만들게 하므로 `화면 위쪽, 학습 기록 링크 바로 아래`로
    고쳤다(상대 위치는 구현과 맞으므로 유지). 같은 오독원을 막으려고 문서 머리의
    Reference 문단 뒤에 **MVP 레이아웃이 단일 컬럼이고 mockup 사이드바가 MVP 구조가
    아니라는 한 줄**을 못박았다 --- `History` 절의 `사이드바의 학습 기록에 대응하는
    화면이다`도 같은 표현을 쓰고 있어서, 그 문장을 고치는 대신 이 한 줄이 "mockup
    안에서의 위치를 가리키는 말"이라고 해석을 고정하게 했다. **사이드바를 명세에
    도입하지 않았다.** (2) 절이 위치만 적고 **어느 화면에 나타나는지**를 정하지
    않아 구현이 study 화면만 택했다. 그 선택이 옳다고 판단해 명세가 말하게 했다 ---
    `History`는 `두 목록으로 끝난다`이고 같은 절이 "다음 행동으로 이어지는 버튼도
    두지 않는다"를 이미 정했으므로 로그아웃은 그 조항의 첫 예외가 된다. 치르는
    비용은 탭 한 번(`학습으로 돌아가기`가 그 화면의 유일한 출구다)이고, 폐기 수단이
    존재한다는 목적에는 진입점 하나로 충분하다. **구현 변경 없음.** 함께 확인된
    사실 하나를 기존 bullet에 붙였다 --- 재로그인 후 `이어서 학습합니다.`는
    `POST /api/study/session`의 `resumed`가 담당하므로 로그아웃 경로가 따로 하는
    일이 없고, 여기에 `/finish`나 세션 정리를 붙이지 않는다. 실패 시 재시도로 문구가
    최대 ~0.6초 뒤에 뜬다는 사실은 **적지 않았다** --- 공용 재시도 정책의 결과이지
    이 화면의 규칙이 아니고, 절이 즉시성을 약속한 적이 없으며 숫자를 UI 문서 산문에
    박는 것이 된다.

#### 구현 해석의 기록 (같은 후속 보완, 구현을 바꾸지 않았다)

-   **[46] probe 제외 집합이 명세보다 엄격했다** (`02_LEARNING_POLICY.md`의
    `Probe 대상 우선순위`): `learning/probe.py`의 `SESSION_FEEDBACK_EVENTS`에
    `mastery_probe_shown`이 들어 있는데, 명세의 제외 목록은 "방금 explicit feedback을
    받은 item / cooldown 중인 item" 둘뿐이었다. 또 "방금"을 **세션 범위**로 읽은 것도
    명세가 정하지 않은 해석이다. **구현을 바꾸지 않고 명세가 이 해석을 허용한다는
    것을 적었다.** 목록이 **하한**임을 먼저 밝혔다 --- `Probe Pacing`이
    `mastery_probe_target_per_session_min`을 강제하지 않으므로 후보가 줄어드는 것
    자체가 위반이 되는 조항이 없고, 반대 방향(목록에 있는 것을 묻는 것)만 위반이다.
    두 해석의 근거: 세션은 명세가 정하지 않은 시간 창에서 남는 유일한 자연 단위이고
    더 긴 창은 `probe_skip_cooldown_days`가 이미 담당한다. 응답 없는 probe는
    `last_probe_at`을 남기지 않아 cooldown이 잡지 못하므로, 제외하지 않으면 한 세션에서
    같은 item을 두 번 묻게 된다(응답한 probe는 cooldown이 담당하므로 이 예외가 필요
    없다). 이 근거는 코드 주석에도 이미 있었고 문서 쪽에만 없었다.
-   **[47] Core E2E 12단계의 문자가 단정 가능한 것보다 강했다**
    (`12_TEST_PLAN.md`의 `Core E2E Scenario`): 12단계가 "새로운 문맥(`new_context`)
    으로 재노출"이라 적었는데, **문장으로는 `varied`와 `new_context`를 구분할 수
    없다** --- `06_LEARNING_ENGINE.md`의 `한계`가 두 stage의 문장 선택 규칙이 같다고
    적고 있다. 그래서 단정할 수 있는 둘(presentation의 `context_stage`가 `anchor`보다
    위, state의 `context_stage`가 `varied` 이상)로 단계 문자를 고치고, **무엇을 단정하지
    않는지와 그 이유**를 뒤에 한 단락으로 적었다. 문장 내용으로 stage를 단정하는
    테스트는 두 규칙이 같은 동안 항상 참이거나 항상 거짓이라 회귀를 잡지 못한다는
    점도 적었다. 이 단계가 실제로 검증하는 것은 "anchor 한 문장이 반복되지 않는다"다.

`13_ACCEPTANCE_CRITERIA.md`와 `14_CONFIGURATION.md`는 변경하지 않았다. 위 여섯 건
어디에도 새 tuning 값이 없고(전부 기존 상태·기존 ladder로 판정한다) acceptance가
말하는 범위도 그대로다. `spec/future/`와 루트 `spec/05`·`spec/06`도 변경하지 않았다.

#### Wave 5 착수 전 반영 --- 운영 공백 4건과 알려진 공백 4건 (같은 후속 보완)

Wave 5(운영) 착수 전에 planner가 찾은 공백 4건(G1\~G4)과 ADR-019 한 줄(S2)을 반영하고,
coordinator가 넘긴 4건(H1\~H4)을 **결정 없이 공백으로만** 기록했다. 새 버전 번호를
만들지 않았다. 실제 도메인은 어느 문서에도 적지 않았다(`spec/04`의 "`infra/`에 도메인을
고정하지 않는다"). 새 ADR은 만들지 않았다 --- 운영 토폴로지(ADR-020)는 architect가
따로 쓰고, 아래 네 건은 전부 절차·운영값이라 절 하나를 고치면 되돌아간다.

-   **[48] 백업 주기·보관 개수·rotation·restore 검증이 없었다**
    (`spec/04_SECURITY_AND_DATA.md`의 `Backup`): "정기 + rotation"만 있고 숫자도, 무엇이
    검증인지도 없었다. 기존 한 문단은 그대로 두고 소절 넷을 붙였다. `주기와 보관 개수`에
    **하루 1회, 최근 7개**를 넣고 **어디에 두는지**를 정했다 --- 두 값은 운영값이라
    `14_CONFIGURATION.md`(API·worker가 전 키를 읽는 학습 정책 파일)에 두지 않고, API·worker가
    받는 `.env` 계열에도 두지 않는다(소비처가 백업 명령뿐이다). 보관 개수는 **백업 명령의
    인자 기본값**, 주기는 **호스트 스케줄러 설정**이 따를 값이다. `14_CONFIGURATION.md`
    끝의 "이 파일에 두지 않는다" 목록에 한 단락을 붙여 canonical을 가리켰다. `rotation
    규칙`은 **새 백업 검증 뒤에만 삭제**한다(먼저 지우면 실패가 이어질 때 백업이 0개가
    된다). `restore 검증`은 planner의 실측 정의 여섯 가지를 그대로 옮겼고, 그 정의가 참이
    되려면 필요한 조건 셋을 함께 적었다: 원본은 dump부터 비교까지 쓰기가 없어야 한다
    (`worker_heartbeats`와 `auth_sessions.last_used_at` 때문에 살아 있는 원본과 비교하면
    거짓 실패한다), login 확인은 비교 뒤에 한다, 복원은 별도 DB에 한다. `백업 파일의
    민감도`에 password hash·token hash 포함, 0600, Git 제외를 적었다.
    `13_ACCEPTANCE_CRITERIA.md`의 `backup/restore 최소 1회 검증`에 그 정의를 가리키는
    괄호를 붙였다.
-   **[49] production에서 사용량 한도를 켜는 방법이 없었다**
    (`14_CONFIGURATION.md`의 `production override (MVP 확정)` 신설, `spec/04`의
    `학습 정책 파일 경로 (MVP 확정)` 신설): `NC_CONFIG_PATH`가 코드와 `.env.example`에만
    있었다. repo 기본값은 `null` 유지, production은 `NC_CONFIG_PATH`로 **전체 사본**을
    가리키고 사본은 **한도 두 줄만** 다르며 Git에 넣지 않는다. 전체 사본의 두 실패(키 추가 →
    기동 실패, 승인값 변경 → 조용히 미반영)와 그래서 필요한 diff 절차, 프로세스 시작 시 한 번
    읽는다는 사실(한도 변경은 worker 재시작), UTC 경계가 한국시간 오전 9시라는 사실, 하나만
    설정하면 `cost.guard_disabled`가 기동마다 뜬다는 사실을 운영자 서술로 적었다. YAML
    블록의 주석 "production에서 필요 시"를 "production은 두 키 모두 integer를 설정한다"로
    고쳤다 --- 사용자 결정(한도는 반드시 켠다)이다. **`null = limit disabled`의 의미는 바꾸지
    않았다.** `spec/04`에는 API와 worker가 같은 파일을 읽는다는 것을 적었다
    (`max_new_items_per_sentence`를 두 프로세스가 나눠 쓴다).
-   **[50] 데이터를 보존하는 migration 경로가 없었다**
    (`04_DB_SPEC.md`의 `Migration Rule` 아래 `운영 DB에 migration을 적용하는 경로 (MVP
    확정)` 신설): `make db-reset`은 데이터를 지우고 production에서 거부된다. 대상 출력 →
    head면 no-op → pending이면 백업 강제(실패하면 중단) → `upgrade head`. 롤백은 백업 복원이고
    downgrade 명령과 백업 생략 옵션을 두지 않는다. 채택안에 **두 가지를 덧붙였다.** (1) 백업부터
    upgrade까지 API·worker를 멈춘다 --- 복원이 롤백 수단인 이상 그 사이 쓰기는 롤백이 조용히
    지우므로, 이 조건이 없으면 안전망이 성립하지 않는다. (2) head일 때는 백업도 만들지 않는다
    --- 보관 단위가 개수라 불필요한 백업이 옛 백업을 밀어낸다. migration 파일의 `downgrade()`는
    빈 DB 왕복 테스트용으로 남으며 이 규칙이 그것을 지우라는 뜻이 아님도 적었다.
-   **[51] `restart 후 state 유지`의 범위와 근거 테스트가 없었다**
    (`13_ACCEPTANCE_CRITERIA.md`, `12_TEST_PLAN.md`): API·worker 프로세스 재시작과 Postgres
    재시작 뒤 로그인 세션·열린 study session·exposure·mastery·history 유지로 범위를 적고,
    호스트 재부팅 후 자동 기동은 기준에 넣지 않았다. `12_TEST_PLAN.md`의 Integration에
    backup/restore, rotation, restart 세 항목을 넣었다. rotation 항목은 13이 직접 요구하지
    않지만 [48]의 "백업 0개" 방지 규칙을 지키는 유일한 관측이라 함께 넣었다. restart 항목은
    Postgres 재시작 쪽이 **데이터가 남는가**만 단정하고 API의 연결 자동 회복은 요구하지 않는다고
    못박았다 --- 채택안이 말한 것은 데이터 유지이고, 회복 요구는 새 요구사항이 된다.
-   **[52] ADR-019 `한계`에 reason bucket 한 줄** (S2): tie-break는 reason bucket 안에서만
    돌아서 `(anchor, reinforcement)` 낡은 candidate가 `(near_original, fsrs_due)` 새 candidate보다
    먼저 선택되는 경우가 남는다. 명세 위반이 아니고 [44]로 증폭이 모두 해소되었다는 오독을 막으려
    적었다. 조건에 `context_repair`가 없다는 전제를 붙였다(선택 절차 1번이 먼저 걸리기 때문이다).
    `06_LEARNING_ENGINE.md`의 `candidate 단위 tie-break`에는 `한계` 절이 없어서 반영하지 않았다.

**알려진 공백 (결정하지 않았다):** 규칙을 만들지 않고 사실만 각 조항 가까이에 적었다.

-   **[53] seed 규모와 추가 적재** (`04_DB_SPEC.md`의 `Seed Data` 뒤
    `알려진 공백 --- seed가 감당해야 하는 규모와 추가 적재`): worker가 `learning_items`를 만들지
    않으므로 2\~4주 평가의 item 전량이 seed에서 와야 한다는 결론, 그리고 추가 적재 의미론이
    없다는 사실(loader 전체 거부, DB에 item 안정 키 없음). 규모 숫자는 적지 않았다.
-   **[54] 출력 토큰 상한** (`08_LLM_SPEC.md`의 `요청 context` 끝): 조항 없음, 구현도 없음,
    너무 낮으면 잘림으로 retry가 는다는 양면만 적었다.
-   **[55] 예외로 끝난 provider 호출의 계상** (`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`
    마지막 bullet): timeout·5xx·429와 빈 본문 예외가 `provider_calls`에도 token에도 잡히지
    않는다는 사실, SDK 내부 재시도가 1회로 적힌다는 사실, `null`과 0 양쪽의 귀결. 함께 SDK 기본
    timeout 600초·재시도 2회가 기본 `claim_lease_seconds`(300초)와 맺는 관계를
    `14_CONFIGURATION.md`의 lease 단락 뒤에 **운영 판단 대상**으로 적었다.
-   **[56] 사용량 한도의 허용 범위** (`14_CONFIGURATION.md`의 fail-closed 단락 뒤): 범위 미정,
    판정이 `>=`라 0이나 음수면 생성이 영구히 멈춘다는 사실, 끄는 방법은 `null`이라는 사실.
    `production override`의 운영자 서술에서 이 단락을 가리켰다.

`spec/future/`, 루트 `spec/05`·`spec/06`, `backend/`·`frontend/`·`infra/`·`scripts/`·`config/`·
`seed/`는 변경하지 않았다.
