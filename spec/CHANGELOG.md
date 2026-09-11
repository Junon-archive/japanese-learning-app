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
