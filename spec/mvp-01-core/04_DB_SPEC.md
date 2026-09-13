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

**MVP에 `origin = generated` 행을 만드는 경로는 없다.** worker는 요청에
실어 보낸 item만 annotate하고 새 `learning_items`를 만들지 않는다
(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`). 값은 컬럼 허용값으로
남긴다.

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

`status`의 MVP 사용 범위: seed 적재와 generation 모두 검증을 마친 뒤
`validated`로 INSERT하므로 **`draft` 행을 만드는 경로가 없다**
(`08_LLM_SPEC.md`의 `탈락한 콘텐츠의 처리`). `quarantined`는 content
flag가 만들고(`10_ERROR_HANDLING.md`), `retired`는 MVP에 경로가 없다. 값은
남기되 쓰지 않는 것을 명시한다.

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
    FSRS memory state와 무관. 설정과 **해제**의 canonical 정의는
    `07_SRS_SPEC.md`의 `No-signal review`와 `deferral 해제`)
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
-   anchor_sentence_id nullable (최초 학습 문맥. 지정 규칙은
    `07_SRS_SPEC.md`의 `anchor_sentence_id 지정`)
-   context_stage: `anchor | near_original | varied | new_context`
    (전이 규칙은 `07_SRS_SPEC.md`의 `Context Progression`)
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

row를 **만드는 주체와 시점, role/reason/stage/status에 넣는 값의
canonical 정의는 `06_LEARNING_ENGINE.md`의 `Candidate Materialization`**
이다. 요약하면 Wave 2의 Learning Engine이 `POST /api/study/session`과
`POST /session/{id}/next`의 pool 부족 시점에 **요청한 사용자 한 명분만**
만든다. seed loader도 계정 생성 CLI도 candidate를 만들지 않는다.

`status`의 두 값은 다음 경계를 가진다.

``` text
queued  콘텐츠가 아직 없어 worker가 생성 중인 candidate (Wave 3)
ready   Ready invariant를 만족해 지금 그대로 제시할 수 있다
```

Wave 3을 확정하고 보니 **`queued`를 만드는 경로는 MVP에 없다.** worker는
candidate를 만들지 않고(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`),
materialization은 이미 검증된 콘텐츠만 투영하므로 곧바로 `ready`를 쓴다
(`06_LEARNING_ENGINE.md`). `sentences.status = draft`와 같은 취급이다.
값과 아래 partial unique index의 조건은 그대로 두되 **MVP에서 쓰지 않는
것을 명시한다.** 조건에서 `queued`를 빼면 나중에 이 상태를 도입할 때
index를 다시 만들어야 하고, 두어도 지금 동작에 영향이 없다.

**`expired`도 MVP에서 쓰지 않는다.** 이 값을 쓰는 주체와 시점이 없다. 특히
`user_item_learning_state.context_stage`가 오른 뒤 Ready Pool에 남은 낮은
stage candidate를 만료시키지 않는다.

-   그 candidate를 보여줘도 ladder는 되돌지 않고
    (`07_SRS_SPEC.md`의 `전이 규칙`의 `max`) 노출 카운트도 정확하다. 비용은
    라운드 한 번이 낮은 stage 문장으로 지나가는 것뿐이다.
-   `06_LEARNING_ENGINE.md`의 `Pool Fallback` 2단계는 바로 그런 노출
    (anchor/near-original reinforcement)을 **의도적으로** 허용한다. 만료
    규칙을 두면 그 fallback을 예외로 파야 하고, 그것은 새 정책이다.
-   낮은 stage candidate가 먼저 뽑히는 문제는 배제나 만료가 아니라
    `06_LEARNING_ENGINE.md`의 `candidate 단위 tie-break`가 **선호**로
    해결한다. 근거와 버린 대안은
    `docs/decisions/ADR-019-stale-review-candidates.md`.

`queued`와 같은 이유로 값과 index 조건은 그대로 남긴다. `expired`가
유효해지는 시점은 candidate에 **수명 정책**이 생길 때다(예: 생성 후 N일,
또는 stage 변경 시 무효화). MVP에 그 정책이 없다.

유일성: materialization이 idempotent해야 하므로 **아직 소비되지 않은
candidate에 partial unique index**를 건다.

``` text
UNIQUE (user_id, sentence_id, presentation_role, context_stage)
WHERE status IN ('queued', 'ready')
```

`shown / consumed / quarantined / expired`를 제외하는 이유는 같은 문장을
나중에 다른 시점에 다시 candidate로 만들 수 있어야 하기 때문이다
(contextual review의 전제). 새 컬럼이나 새 테이블은 필요하지 않다.

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

불변식: **한 `study_session_id`에 `completed_at IS NULL`인 row는 최대
1개다.** `POST /session/{id}/next`는 열린 presentation이 있으면 새로
만들지 않고 그것을 반환한다(`05_API_SPEC.md`의
`열린 presentation 불변식`). 이것이 재시도로 인한 중복 presentation을
막는다.

유일성: 위 불변식은 애플리케이션 검사만으로 성립하지 않으므로 **아직
완료되지 않은 presentation에 partial unique index**를 건다. 이름은
`uq_study_presentations_open`이다.

``` text
UNIQUE (study_session_id) WHERE completed_at IS NULL
```

-   **partial이어야 한다.** 조건절을 빼고 full unique로 만들면
    `study_session_id`가 한 행에만 존재할 수 있게 되어 **한 세션에 문장을
    하나밖에 보여줄 수 없다.** 완료된 행은 세션마다 여러 개 쌓이는 것이
    정상이다.
-   **범위는 session 하나다.** `user_id`로 넓히지 않는다. idle timeout으로
    만료된 session은 미완료 presentation을 그대로 남기는 것이 정상이므로
    (`05_API_SPEC.md`의 `세션·presentation 상태 게이트`) 사용자 단위로 묶으면
    그 정상 상태가 제약 위반이 된다. 불변식 문장 자체도 "한
    `study_session_id`에"다.
-   애플리케이션 검사를 대체하지 않는다. `/next`는 여전히 열린
    presentation을 **조회해서 그것을 반환**해야 한다. index는 그 조회가
    동시 요청과 경합했을 때의 마지막 방어선이다.

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
-   client_event_id (event idempotency key. UUID. **client 발급과 server
    발급이 모두 있다** --- 아래)
-   created_at

Unique: `(user_id, client_event_id)`.

유일성: `07_SRS_SPEC.md`의 `노출당 evidence 1건`을 DB가 강제하도록 **explicit
evidence event에 partial unique index**를 건다. 이름은
`uq_learning_events_evidence`이다.

``` text
UNIQUE (study_presentation_id, learning_item_id)
WHERE event_type IN (explicit evidence 6종)
```

-   **partial이어야 한다.** 조건절을 빼고 full unique로 만들면 한 노출에 event를
    2건 이상 남길 수 없어 `item_clicked` / `explanation_revealed` /
    `mastery_probe_shown`이 전부 막힌다. 한 노출에 여러 event가 쌓이는 것은
    정상이고 **evidence만** 하나여야 한다.
-   predicate의 6종은 `07_SRS_SPEC.md`의 `노출당 evidence 1건`이 열거하는 그
    집합이다(self-report 3종 + probe 응답 3종). **목록을 이 문서에 다시 적지
    않는다** --- 같은 집합을 두 곳에 적으면 한쪽만 고쳐지는 순간 index가 세는 것과
    명세가 세는 것이 갈라진다. 구현이 두 목록을 갖는 것은 migration이 애플리케이션
    코드를 import하지 않기 때문이며, 갈라졌는지는 테스트가 DB의 index 정의를 읽어
    단정한다.
-   **`mastery_probe_skipped`는 들어가지 않는다.** skip은 evidence가 아니므로
    (`02_LEARNING_POLICY.md`의 `Skip`) 한 노출에 skip과 evidence가 함께 있는 것이
    정상이고, predicate에 넣으면 그 정상 상태가 제약 위반이 된다.
-   **범위에 `user_id`를 넣지 않는다.** `study_presentation_id`가 이미 한 사용자에
    속하므로 넓혀도 더 막는 것이 없다. `item_exposures`의
    `(study_presentation_id, learning_item_id)`와 같은 형태다.
-   애플리케이션 검사를 대체하지 않는다. 정상 경로는 **기록 전에 조회해서** 2회차를
    409로 거부하는 것이고(그래야 event를 애초에 남기지 않는다), index는 경합했을
    때의 마지막 방어선이다. 경합에서 진 요청도 **같은 409**를 받는다 ---
    `05_API_SPEC.md`의 `409 사유 구분`이 요구하는 사유가 두 경로에서 같아야 하기
    때문이다. 그 판별을 위해 index 이름이 구현에서 상수다.

**위반 행을 정리하는 migration 단계를 두지 않는다.** 위반 행이 있으면 migration은
실패하며 그대로 둔다. 이 테이블은 immutable raw history이고, 행을 지우는 것은
"사용자가 그렇게 답하지 않았다"는 없는 사실을 만드는 것이다. 두 행 중 무엇을 남길지
고르는 판단도 migration이 할 일이 아니다. `item_exposures`와 달리 이 테이블에는
무효화 컬럼이 없다는 점도 같은 방향을 가리킨다.

### client_event_id 발급 주체

이 컬럼은 v0.2까지 "client 생성 UUID"로만 설명했지만, `session_started`,
`sentence_viewed`, `sentence_completed`, `mastery_probe_shown`,
`session_finished`는 **client가 POST하는 endpoint가 없고 서버가 부수적으로
남기는 event**다. 그래서 컬럼 의미를 다음으로 고친다.

``` text
client_event_id = 이 event의 idempotency key (UUID)
발급 주체는 event_type마다 고정이며 섞이지 않는다
```

-   **client 발급**: 같은 사용자 입력이 여러 번 정당하게 발생할 수 있고
    서버에 그것을 구분할 자연키가 없는 event.
-   **server 발급**: 서버가 만든 row(session / presentation) 하나당 최대
    1건만 존재해야 하는 event. 고정 namespace를 쓴 **UUIDv5**로
    결정론적으로 계산하므로 재시도해도 같은 값이 나오고
    `(user_id, client_event_id)` unique가 중복을 막는다.

**event_type별 발급 주체와 자연키의 canonical 표는
`05_API_SPEC.md`의 `event idempotency key`에 둔다.** 두 문서에 표를
중복해 두지 않는다.

두 주체가 **같은 unique 공간**을 쓰므로 키 형식으로 공간을 가른다: server
발급은 `uuid5`(version 5), client 발급은 **UUIDv4만** 받는다. 그래서 client가
서버 자연키를 선점할 수 없다. canonical 서술은 `05_API_SPEC.md`의
`키 공간 분리 (server = v5, client = v4)`이며, **컬럼과 unique 제약은 바뀌지
않는다**(검증은 API 경계에서 한다).

컬럼 이름은 `client_event_id`로 유지한다. 이름을 바꾸면 migration과 이미
작성된 model/테스트가 따라 움직이는데, 얻는 것은 이름 하나의 정확도뿐이다.
의미는 이 절이 canonical이다.

### probe 상태를 어디에 두는가

**`mastery_probes` 같은 전용 테이블을 만들지 않는다.**
`05_API_SPEC.md`의 `probe.probe_id`는 해당 probe를 낸
`mastery_probe_shown` **learning_event의 id**(정수)다
(`docs/decisions/ADR-009-probe-id.md`).

probe가 실제로 필요로 하는 **상태**는 이미 전용 컬럼에 있다.

``` text
마지막 probe 시각    user_item_learning_state.last_probe_at
skip 누적            user_item_learning_state.probe_skip_count
cooldown 판정        위 두 값 + probe_skip_cooldown_days
```

event log에서 읽는 것은 "이 probe_id가 유효한가, 어떤 item에 대한
것인가"라는 **조회**이지 상태 저장이 아니다. 따라서 전용 테이블은 파생
가능한 컬럼만 가진 20번째 테이블이 되고, 그 unique 제약
`(presentation_id, learning_item_id)`도 위 UUIDv5 자연키와 같은 내용을
두 번 표현하게 된다.

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
-   result_ref nullable (JSON. 생성된 sentence/explanation id 집합 +
    provider usage. 구조는 아래 `result_ref 구조`)
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

job_type별 **enqueue 트리거·`idempotency_key` 형식·`payload_json` 구조의
canonical 표는 `09_BACKGROUND_JOBS.md`의
`Enqueue 트리거와 idempotency key`**에 있다. 여기에 중복해 두지 않는다.

### result_ref 구조 (MVP 확정)

``` json
{
  "sentence_ids": [12, 13],
  "sentence_item_explanation_ids": [55],
  "rejected": [{"reason": "duplicate_hash"}],
  "usage": {
    "provider_calls": 1,
    "input_tokens": 1234,
    "output_tokens": 567,
    "estimated_cost_usd": null,
    "last_call_at": "2026-09-12T04:05:06Z"
  }
}
```

`usage.input_tokens` / `usage.output_tokens`는 **정수 또는 `null`**이다.
`null`은 "이 job이 쓴 총량을 모른다"(provider가 `usage`를 주지 않은 호출이
있었다)이고 0과 다르다. `estimated_cost_usd`도 nullable이다.

`usage`가 **token/request 사용량의 저장 위치**다. 별도 usage/metrics
테이블을 만들지 않는다. 기록 규칙과 daily ceiling 판정(UTC 일 경계)은
`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`가 canonical이고,
`rejected`의 사유 코드 집합은 `08_LLM_SPEC.md`가 canonical이다.

## worker_heartbeats

worker 프로세스의 생존 신호다. `GET /api/health`의 `components.worker`가
읽는 유일한 소스다(`05_API_SPEC.md`, `09_BACKGROUND_JOBS.md`의
`Worker Heartbeat`).

-   worker_name (text, PK)
-   last_heartbeat_at (timestamptz NOT NULL)

MVP의 worker는 하나이며 `worker_name = 'default'` 한 행만 존재한다. 그래도
이름을 PK로 두는 이유는 upsert 대상이 필요하고, worker가 둘이 되는 날
migration 없이 행만 늘면 되기 때문이다. 사용자 종속 테이블이 아니므로
`user_id`가 없다.

**왜 새 테이블인가.** `generation_jobs`의 최근 활동으로 추론하는 대안은
`components.worker`가 답해야 하는 질문에 답하지 못한다. 개인용 앱에서는
하루 종일 job이 0건인 것이 정상이고, 그때 "일이 없다"와 "worker가 죽었다"가
같은 관측이 된다. 즉 heartbeat가 가장 필요한 순간에 판정이 항상 틀린다.
근거와 버린 대안 전체는
`docs/decisions/ADR-017-worker-heartbeat-storage.md`.

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
-   task_type (허용값은 `generation_jobs.job_type`과 같은 3개)
-   version (형식은 아래)
-   provider (실행 구현 이름. `openai | stub`. `stub`은 테스트 fixture만
    만드는 값이며 `LLM_PROVIDER`의 허용값이 아니다 --- `08_LLM_SPEC.md`의
    `Provider 선택과 model 출처`)
-   model (모델 문자열. business logic에 하드코딩하지 않는다)
-   created_at
-   **active** (현재 사용 중인 버전 표시)

Unique: `(task_type, version)`.

### version 형식과 active 유일성 (MVP 확정)

``` text
task_type                version 형식
GENERATE_SENTENCE_BATCH  sentence_gen_v{n}
GENERATE_REVIEW_CONTEXT  review_context_v{n}
EXPLAIN_ITEM             explain_item_v{n}
```

이름은 `spec/06_LLM_ENGINEERING_PRINCIPLES.md` 6번의 것을 그대로 쓰고
`{n}`은 1부터 증가하는 정수다. **prompt 본문이 바뀌면 반드시 `{n}`을
올린다.** 같은 version 행의 내용을 바꿔 재등록하면
`sentences.provenance_json.prompt_version`이 어떤 prompt를 가리키는지
사후에 알 수 없다.

`active`는 task_type당 최대 하나이며 **partial unique index**로 강제한다.

``` text
UNIQUE (task_type) WHERE active
```

"가장 최근 행이 active"로 추론하지 않는다. 추론하면 옛 version으로
되돌리는 rollback이 불가능해진다.

### 등록 절차

prompt 본문은 Git에 파일로 두고(`backend/app/llm/prompts/`) DB에는
registry만 둔다. 등록은 **idempotent upsert 스크립트**로 하며 직접
INSERT하지 않는다.

``` text
1. (task_type, version) 으로 upsert (provider / model 갱신)
2. 같은 task_type의 다른 행을 active = false 로 내린 뒤
   대상 행을 active = true 로 올린다 (한 트랜잭션)
```

worker는 실행 시점에 `active = true` 행을 읽는다. 없으면 그 job은
`dead_letter`다(`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`).

## Seed Data

초급 사용자의 첫 세션을 가능하게 하기 위해 **작은 version-controlled
starter seed set**을 둔다.

-   everyday high-frequency word / grammar / expression
-   `learning_items.origin = seed`
-   빈도 정보는 새 컬럼 없이 `learning_items.metadata_json`의
    `frequency_rank`로 싣고, seed loader가 같은 `metadata_json`에
    `seed_order`(적재 순서)를 채운다. 두 값의 canonical 정의와 loader
    규약은 `06_LEARNING_ENGINE.md`의 `Exploration Item 선정`에 있다
-   seed 문장을 함께 두어 첫 세션의 new/exploration pool의 **재료**를
    확보한다. seed 적재는 `learning_items` / `sentences` /
    `sentence_items` / `sentence_item_spans` /
    `sentence_item_explanations`까지만 만들고
    **`user_sentence_candidates`는 만들지 않는다.** candidate는 사용자별
    데이터이고 적재 시점에 사용자가 없을 수 있다. Ready Pool은
    `06_LEARNING_ENGINE.md`의 `Candidate Materialization`이 세션 시작
    시점에 이 seed 콘텐츠에서 만든다.
-   정확한 개수는 제품 명세에 고정하지 않는다

seed는 Git으로 관리하고 migration 또는 별도 seed 절차로 적재한다.

### 알려진 공백 --- seed가 감당해야 하는 규모와 추가 적재

**아래 두 가지는 결정되지 않았다.** 사실만 적는다.

-   **MVP에서 `learning_items`의 공급원은 seed뿐이다.** worker는
    `learning_items`를 만들지 않고(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`)
    새 어휘 공급은 Future다. 반면 이 절은 seed를 "작은 starter seed set"으로,
    `06_LEARNING_ENGINE.md`의 `Cold Start`는 "첫 몇 세션"용으로 적고 있고,
    `13_ACCEPTANCE_CRITERIA.md`는 기술 검증 뒤 실제 2\~4주 사용 평가를 요구한다.
    세 조항을 합치면 **2\~4주 평가 기간에 쓰일 item 전량이 seed에서 와야 한다.**
    이 결론은 그동안 어디에도 적혀 있지 않았다. seed 규모는 실사용 평가 기간을
    감당해야 하지만 **그 규모는 정하지 않았다**(위 "정확한 개수는 제품 명세에
    고정하지 않는다"는 그대로다).
-   **추가 적재 의미론이 없다.** 이미 seed가 적재된 DB에 item을 더하는 절차가
    명세에 없다. 현재 loader는 `origin = seed` 행이 하나라도 있으면 적재 전체를
    거부한다. `learning_items`에는 seed 파일의 안정 키가 저장되지 않고 `lemma`
    유일성 제약도 없어, 이미 적재된 item을 DB에서 식별할 안정 키가 없다. 학습
    기록이 쌓인 뒤에는 `make db-reset`으로 다시 만드는 경로도 쓸 수 없다(데이터를
    지운다).

## Demo Data

Public Demo는 static frontend fixture이며 **DB를 사용하지 않는다.**
demo user row, demo state, `mode` 컬럼을 두지 않는다. 따라서 demo가
private mastery를 오염시킬 경로 자체가 존재하지 않는다.

## Migration Rule

DB schema 변경은 Alembic migration 없이 직접 production DB에 적용하지
않는다. 빈 DB에서 migration만으로 전체 schema를 재현할 수 있어야 한다.

### 운영 DB에 migration을 적용하는 경로 (MVP 확정)

데이터가 있는 DB의 schema를 올리는 경로는 **데이터를 보존하는
`alembic upgrade head` 하나**다. 개발용 초기화(`make db-reset`: DROP → CREATE →
upgrade)는 데이터를 지우고 `APP_ENV = production`에서 거부되므로 이 경로가 아니다.

``` text
1. 대상 출력    password를 가린 DSN(host, port, database)을 먼저 출력한다
2. pending 확인 현재 revision이 이미 head면 아무것도 하지 않고 성공으로 끝낸다
3. 직전 백업    pending migration이 있으면 백업을 만든다
                (spec/04_SECURITY_AND_DATA.md의 Backup. 새 백업 검증까지 포함)
                백업이 실패하면 migration을 하지 않고 실패로 끝낸다
4. upgrade      alembic upgrade head
```

-   **pending migration이 있으면 백업은 생략할 수 없다.** 백업을 건너뛰는 옵션을
    두지 않는다. 근거는 셋이다. 사용자 1명 규모라 비용은 몇 초다. 되돌릴 수 없는
    schema 변경 직전의 유일한 안전망이다. 강제하지 않으면 운영자가 빠뜨린다.
-   **이미 head면 백업도 만들지 않는다.** 바뀌는 것이 없어 안전망이 필요 없고,
    배포 때마다 생기는 불필요한 백업이 보관 개수
    (`spec/04_SECURITY_AND_DATA.md`의 `주기와 보관 개수`)를
    채워 옛 백업을 밀어내지 않게 한다.
-   **롤백은 downgrade가 아니라 3에서 만든 백업의 복원이다.** 운영 경로에
    downgrade 명령을 두지 않는다. downgrade는 테이블·컬럼을 DROP하는 방향이라
    데이터가 있는 DB에서는 되돌림이 아니라 추가 손실이고, 데이터 위에서 검증된
    적도 없다. migration 파일의 `downgrade()`는 빈 DB에서의 migration 왕복 테스트에
    쓰이며, 이 규칙은 그것을 지우라는 뜻이 아니다.
-   **대상 DB를 먼저 출력하는 이유:** DSN이 두 가지다. 컨테이너 안에서 쓰는 DSN은
    compose 서비스 이름을 host로 쓰고, 호스트에서 쓰는 DSN은 loopback에 열린 port를
    쓴다. 셸에 남아 있던 다른 `DATABASE_URL`(예: 로컬 개발 DB)로 실행하면 백업과
    migration이 함께 엉뚱한 DB에 적용된다. password는 출력하지 않는다
    (`make db-reset`의 출력과 같다).
-   **3부터 4가 끝날 때까지 API와 worker를 멈춘다.** 복원은 백업 이후의 쓰기를
    전부 잃으므로, 그 사이에 학습 기록이 쓰이면 롤백이 그것을 조용히 지운다. 새
    schema 위에서 옛 코드가 도는 창도 함께 없어진다.
-   upgrade가 실패하거나 upgrade 뒤에 문제가 드러나면 3의 백업으로 복원한다. 위
    `learning_events`의 unique index처럼 **위반 행을 정리하는 migration 단계를 두지
    않는** 경우 migration 실패는 설계된 결과이며, 이 경로가 그 실패를 우회하지
    않는다.
