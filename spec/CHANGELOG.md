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
