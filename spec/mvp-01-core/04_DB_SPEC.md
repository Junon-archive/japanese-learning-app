# Database Specification

논리 schema이며 SQLAlchemy/Alembic으로 구현한다. 아래 필드 목록은
최소 요구사항이고, 구현 시 index/constraint를 추가할 수 있다.

## 공통 규칙

-   모든 timestamp는 **UTC**(`timestamptz`)로 저장한다. 사용자 local day
    경계는 `users.timezone`(기본 `Asia/Seoul`)으로 계산한다.
-   사용자 종속 테이블은 예외 없이 `user_id`를 가진다.
-   immutable log(`learning_events`, `item_exposures`)는 UPDATE로 의미를
    바꾸지 않는다. 무효화는 전용 컬럼(`invalidated_at`)으로 표현한다.
-   Public Demo는 DB를 사용하지 않는다. demo 전용 row/테이블/`mode`
    컬럼을 만들지 않는다(`spec/04_SECURITY_AND_DATA.md` 참조).

## users

-   id
-   login_id (로그인 식별자. 아래 규칙이 canonical)
-   password_hash (Argon2id 등 안전한 password hash)
-   timezone (default `Asia/Seoul`)
-   starting_level (default `beginner`)
-   created_at
-   is_active

Public signup은 없다. 계정은 seed/admin CLI 또는 초기 setup 절차로
생성한다.

password 요구사항(최소 길이 등)의 canonical 정의는
`spec/04_SECURITY_AND_DATA.md`의 `Password 요구사항 (MVP 확정)`이며 계정
생성 경로에서 검증한다. **`users`와 `auth_sessions` 어느 쪽에도 로그인 실패
카운터·잠금 시각 컬럼을 두지 않는다**(같은 문서의
`온라인 무차별 대입 방어 (MVP 확정)`).

### login_id

로그인 식별자는 **컬럼 하나**이며 이름은 `login_id`다. 별도 `email`
컬럼을 두지 않는다. API 요청/응답의 필드명도 같다(`05_API_SPEC.md`).

``` text
컬럼        login_id
제약        NOT NULL, UNIQUE
정규화      앞뒤 공백 제거 후 ASCII lowercase
허용 형식   ^[a-z0-9._+@-]{3,64}$   (정규화 결과 기준, CHECK)
```

-   **대소문자를 구분하지 않는다.** 구분하지 않기로 한 이상 **저장
    시점에 정규화한 값만 저장**하고 조회도 정규화한 값으로 한다. 원본
    대소문자를 저장하고 조회할 때만 `lower()`로 비교하는 방식은 쓰지
    않는다. 그러면 UNIQUE가 정규화 전 값에 걸려 대소문자만 다른 중복
    계정이 만들어진다. `citext` extension도 쓰지 않는다(설치 의존성을
    늘리지 않는다).
-   허용 문자를 ASCII로 제한하는 이유는 lowercase 변환 결과를 하나로
    고정하기 위해서다. Unicode casefold는 locale에 따라 결과가 달라진다.
    정규화 결과가 이 형식을 벗어나면 계정 생성이 실패한다.
-   **이메일 형식을 강제하지 않는다.** public signup이 없고 실사용자가
    한 명이며, 앱이 이 값으로 메일을 보내는 기능도 없다. 형식 검증은
    오탈자를 잡아주지 못하면서 식별자 선택만 제한한다. 이메일을 쓰고
    싶으면 `user@example.com`도 위 형식에 그대로 들어간다.

## auth_sessions

학습 세션(`study_sessions`)과 이름이 충돌하지 않도록 인증 세션은 별도
테이블로 둔다.

-   id
-   user_id
-   token_hash (opaque random token의 hash만 저장, 원본 토큰 저장 금지)
-   created_at
-   expires_at
-   last_used_at
-   revoked_at nullable

## learning_items

-   id
-   type: `word | grammar | expression`
-   lemma / canonical_form
-   reading
-   default_meaning (canonical/default 의미. 문맥 의미와 혼동 금지)
-   difficulty_label nullable (MVP는 coarse label 하나만)
-   topic_tags nullable (simple tag 목록)
-   origin: `seed | generated`
-   metadata_json
-   created_at

Future-ready: item senses, register, active-use/recognize-only, richer
difficulty, morphology provenance, audio metadata, production mastery는
모두 Future다(`spec/future/` 참조). MVP에서는 nullable 확장 여지만 남기고
구현하지 않는다.

## sentences

Sentence는 **global content entity**다. "이 사용자에게 지금 어떤
목적으로 보여주는가"는 sentence가 아니라 `user_sentence_candidates`가
가진다.

-   id
-   japanese
-   korean_translation
-   source_type (MVP: `generated | seed`)
-   source_id nullable
-   difficulty_json (MVP는 coarse label 중심)
-   provenance_json (model / provider / prompt_version / generated_at /
    parent_sentence_id)
-   generation_job_id nullable
-   parent_sentence_id nullable (review context 재생성 lineage)
-   normalized_hash (duplicate 검출용 정규화 해시)
-   status: `draft | validated | quarantined | retired`
-   created_at

`sentences`에는 `user_id`도, 사용자별 role도 두지 않는다.

## sentence_items

Sentence와 LearningItem의 **언어적 annotation**이다.

-   id
-   sentence_id
-   learning_item_id
-   surface_form
-   is_tappable
-   created_at

**`role` 컬럼은 두지 않는다.** new/review/exploration은 사용자별·시점별
속성이므로 global content에 저장하면 같은 문장을 다른 시점에 다른
목적으로 재사용할 수 없다. 해당 정보는
`user_sentence_candidates.presentation_role`과
`study_presentations.presentation_role`에 저장한다. v0.2까지 존재하던
`role = incidental` 설계는 이 이유로 제거한다.

## sentence_item_spans

일본어 표현은 불연속·활용형이 흔하므로 span은 child entity로 분리한다.

-   id
-   sentence_item_id
-   start_codepoint
-   end_codepoint
-   span_order

Offset 기준은 **Unicode code point index**로 고정한다. 바이트나
UTF-16 code unit이 아니다. 불연속 표현(`気が全然乗らない`,
`任せといて`)은 여러 span row로 표현한다.

Frontend가 JavaScript UTF-16 index를 직접 계산하게 만들지 않는다. API는
sentence를 render 가능한 segment list로 반환한다
(`05_API_SPEC.md` 참조).

## sentence_item_explanations

**tap 시 표시할 문맥 설명의 저장소다.** 이 테이블이 없으면 핵심 UI가
표시할 데이터가 존재하지 않는다.

-   id
-   sentence_item_id
-   reading
-   core_meaning (핵심 의미 1\~2개)
-   meaning_in_context (이 문장에서의 의미)
-   nuance (짧은 usage nuance)
-   example_sentence
-   example_translation nullable
-   provider nullable
-   model nullable
-   prompt_version nullable
-   generated_at
-   status: `draft | validated | quarantined`

`learning_items.default_meaning`은 canonical 의미,
`sentence_item_explanations.meaning_in_context`는 해당 sentence에서의
의미다. 둘을 같은 필드로 섞지 않는다.

## user_mastery

-   user_id
-   learning_item_id
-   comprehension_mastery: **nullable float \[0.0, 1.0\]**
-   listening_mastery: **nullable float \[0.0, 1.0\]** (MVP에서는 항상
    NULL. 갱신하지 않는다)
-   evidence_count: mastery update에 실제 사용된 **explicit evidence
    개수**. meaningful exposure count와 다른 값이다.
-   mastery_algorithm_version: 이 값이 어떤 알고리즘 버전으로
    계산되었는지 기록하여 재계산/replay 시 비교 가능하게 한다.
-   last_updated_at

Unique: `(user_id, learning_item_id)`.

`NULL`은 "능력이 0"이 아니라 **"아직 충분한 evidence가 없음"**을
의미한다. boolean Known/Unknown으로 구현하지 않는다.

## review_states

FSRS scheduling 상태를 저장한다. mastery score와 **별도 테이블**이다.

컬럼은 실제 사용하는 라이브러리(`fsrs` 6.x)의 `Card`에 1:1로 대응시킨다
(`docs/decisions/ADR-003-fsrs-library-binding.md`).

-   user_id
-   learning_item_id
-   stability nullable (`Card.stability`)
-   difficulty nullable (`Card.difficulty`)
-   state (`Card.state`. fsrs 6 열거값 `1 = Learning | 2 = Review |
    3 = Relearning`)
-   step nullable int (`Card.step`. learning/relearning step index이며
    이것 없이는 Card를 복원할 수 없다. `state = Review`이면 NULL)
-   last_review_at nullable (`Card.last_review`에 1:1 대응)
-   next_review_at NOT NULL (`Card.due`에 1:1 대응)
-   reps
-   lapses
-   fsrs_params_version (파라미터 변경 시 재현용)
-   deferred_until nullable (무신호 passive review 후 단기 재노출 방지.
    FSRS memory state와 무관)
-   meaningful_exposure_count (denormalized cache. **canonical source는
    `item_exposures`다**)

스케줄은 **절대시각(`next_review_at`)으로만 저장한다.** fsrs 6의 스케줄은
`Card.due`이고 interval(일수)은 `due - last_review`의 파생값이므로
`scheduled_days` 같은 컬럼을 중복 저장하지 않는다.

`reps`와 `lapses`는 FSRS가 돌려주는 값이 아니라 **애플리케이션이 직접
유지하는 카운터**다. review를 기록할 때 `reps`를 1 증가시키고 rating이
`Again`이면 `lapses`를 1 증가시킨다. 무신호 review는 rating을 만들지
않으므로 둘 다 증가시키지 않는다(`07_SRS_SPEC.md`).

`Card.card_id`는 저장하지 않는다. identity는 아래 unique 제약이며 Card는
매 review마다 이 컬럼들에서 재구성한다. 외부 식별자를 하나 더 두면
canonical identity가 둘이 된다.

Unique: `(user_id, learning_item_id)`.

## user_item_learning_state

Context progression과 probe 상태를 사용자별로 추적한다.

-   user_id
-   learning_item_id
-   anchor_sentence_id nullable (최초 학습 문맥)
-   context_stage: `anchor | near_original | varied | new_context`
-   passive_no_signal_count
-   last_probe_at nullable
-   probe_skip_count
-   is_active_learning_target (incidental click에서 승격되었는지 포함)
-   updated_at

Unique: `(user_id, learning_item_id)`.

## item_exposures

meaningful exposure의 **canonical source**다. 단순 integer counter를
source of truth로 사용하지 않는다.

-   id
-   user_id
-   learning_item_id
-   study_presentation_id
-   sentence_id
-   modality (MVP: `reading` 만 사용. listening은 Future)
-   context_stage
-   created_at
-   invalidated_at nullable (content flag/quarantine 시 재계산에서 제외)

Unique: `(study_presentation_id, learning_item_id)` — 한 presentation의
같은 item은 **최대 1 exposure**다. click/explanation reveal/self-report를
각각 별도 exposure로 중복 집계하지 않는다.

## user_sentence_candidates

특정 사용자에게 보여줄 후보다. Ready Pool은 이 테이블의
`status = ready` 집합이다.

-   id
-   user_id
-   sentence_id
-   presentation_role: `review | new | exploration`
-   review_reason nullable: `fsrs_due | reinforcement | context_repair`
-   context_stage
-   status: `queued | ready | shown | consumed | quarantined | expired`
-   created_at
-   updated_at

## user_sentence_candidate_targets

문장당 target item 1\~2개를 연결한다.

-   id
-   candidate_id
-   learning_item_id
-   is_new_item

## study_presentations

사용자에게 실제로 어떤 문장을 어떤 이유로 보여줬는지의 기록이다.

-   id
-   study_session_id
-   user_id
-   candidate_id
-   sentence_id
-   presentation_role
-   review_reason nullable
-   context_stage
-   shown_at
-   completed_at nullable

이 구조로 same sentence 재사용, role 변화, original/near/new context,
exposure replay, content flag invalidation을 추적한다.

## study_sessions

-   id
-   user_id
-   started_at
-   last_activity_at
-   ended_at nullable
-   active_seconds (interaction interval 기반 active time. 긴 idle
    gap 제외)
-   target_minutes (default 12)
-   extended_minutes
-   policy_snapshot_json (해당 세션에 적용된 config/policy 값)
-   summary_json

30분(`study_session_idle_timeout_minutes`) 이상 inactive 후 재진입하면
새 study session을 시작한다.

## learning_events

Immutable raw history. Mastery 알고리즘이 바뀌더라도 과거 event를
replay할 수 있도록 원본을 보존한다.

-   id
-   user_id
-   study_session_id
-   study_presentation_id nullable
-   sentence_id nullable
-   learning_item_id nullable
-   event_type
-   payload_json
-   client_event_id (idempotency용 client 생성 UUID)
-   created_at

Unique: `(user_id, client_event_id)`.

MVP event_type 목록:

``` text
session_started
sentence_viewed
sentence_completed
item_clicked
explanation_revealed
translation_revealed
self_report_known
self_report_uncertain
self_report_unknown
mastery_probe_shown
mastery_probe_known
mastery_probe_uncertain
mastery_probe_unknown
mastery_probe_skipped
content_flagged
session_extended
session_finished
```

audio 관련 event는 MVP에 없다(`00_SCOPE.md` 참조).

## generation_jobs

-   id
-   job_type (허용값은 아래 목록이 canonical)
-   status: `queued | running | validated | completed | retry | failed | dead_letter`
-   payload_json
-   result_ref nullable (생성된 sentence/explanation id 집합)
-   idempotency_key **UNIQUE**
-   retry_count
-   max_attempts
-   next_attempt_at
-   last_error nullable
-   created_at
-   started_at nullable
-   finished_at nullable

Worker 실행은 at-least-once를 전제로 하고 **DB persistence는
idempotent**해야 한다(`09_BACKGROUND_JOBS.md` 참조).

### job_type 허용값

MVP의 `job_type` 허용값은 다음 **3개뿐**이며 이 목록이 canonical이다.
migration이 거는 제약(CHECK든 enum type이든)에 이 집합이 그대로 들어간다.
제약의 구현 수단은 다른 열거 컬럼과 같은 방식을 따르면 된다.

``` text
GENERATE_SENTENCE_BATCH
GENERATE_REVIEW_CONTEXT
EXPLAIN_ITEM
```

`08_LLM_SPEC.md`의 MVP task 이름과 1:1로 같다. job이 실제로 하는 일이
provider task이므로 축을 하나로 유지한다.

-   **pool replenishment는 job_type이 아니다.** Ready Pool이 부족할 때
    `GENERATE_SENTENCE_BATCH`(필요하면 `GENERATE_REVIEW_CONTEXT`)를
    enqueue하는 **트리거**이며, 그렇게 만들어진 job의 `job_type`은 위 값
    중 하나다. 별도 값을 두면 같은 생성 작업이 두 이름으로 존재하게 되고
    "어느 쪽으로 enqueue해야 하는가"라는 질문이 계속 생긴다. 트리거
    조건은 `06_LEARNING_ENGINE.md`와 `09_BACKGROUND_JOBS.md`에 있다.
-   **missing explanation repair job의 job_type은 `EXPLAIN_ITEM`이다.**
-   **maintenance/cleanup은 MVP job_type에 넣지 않는다.** MVP에 이 job을
    만드는 호출자가 없다. 호출자가 없는 task를 목록에서 빼는 기준은
    `ANALYZE_SENTENCE`를 Future로 보낸 기준과 같다(`08_LLM_SPEC.md`).
    필요해지면 이 목록을 먼저 고치고 migration으로 값을 추가한다.

## content_flags

-   id
-   user_id
-   sentence_id nullable
-   learning_item_id nullable
-   study_presentation_id nullable
-   reason: `unnatural | wrong | too_easy | too_hard | other`
-   note nullable
-   created_at
-   resolved_at nullable

flag의 실제 동작(quarantine, evidence 무효화)은
`10_ERROR_HANDLING.md`에 정의한다.

## prompt_versions

-   id
-   task_type
-   version
-   model/provider metadata
-   created_at
-   **active** (현재 사용 중인 버전 표시)

## Seed Data

초급 사용자의 첫 세션을 가능하게 하기 위해 **작은 version-controlled
starter seed set**을 둔다.

-   everyday high-frequency word / grammar / expression
-   `learning_items.origin = seed`
-   빈도 정보는 새 컬럼 없이 `learning_items.metadata_json`의
    `frequency_rank`로 싣고, seed loader가 같은 `metadata_json`에
    `seed_order`(적재 순서)를 채운다. 두 값의 canonical 정의와 loader
    규약은 `06_LEARNING_ENGINE.md`의 `Exploration Item 선정`에 있다
-   seed 문장을 함께 두어 첫 세션의 new/exploration pool을 확보한다
-   정확한 개수는 제품 명세에 고정하지 않는다

seed는 Git으로 관리하고 migration 또는 별도 seed 절차로 적재한다.

## Demo Data

Public Demo는 static frontend fixture이며 **DB를 사용하지 않는다.**
demo user row, demo state, `mode` 컬럼을 두지 않는다. 따라서 demo가
private mastery를 오염시킬 경로 자체가 존재하지 않는다.

## Migration Rule

DB schema 변경은 Alembic migration 없이 직접 production DB에 적용하지
않는다. 빈 DB에서 migration만으로 전체 schema를 재현할 수 있어야 한다.
