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
-   **학습 대상 언어는 콘텐츠 엔티티의 축이다(MVP-03).** `language TEXT NOT NULL
    CHECK (language IN ('ja','en'))`를 `learning_items`, `sentences`, `study_sessions`,
    `prompt_versions`, `generation_jobs`에 둔다. **사용자별 학습 테이블에는 두지 않는다** ---
    `learning_item_id`(또는 `sentence_id`)가 이미 언어를 결정한다(불변식 21, ADR-023 결정 1).
    `server_default`를 두지 않는다. 기본값이 있으면 언어를 빠뜨린 INSERT가 조용히 일본어가 된다.

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

### 계정 수와 공유 범위 (확정)

**계정은 소유자와 소수의 지인용이다.** 하나로 제한하지 않는다. 회원가입은 계속 없고
(`03_UI_UX_SPEC.md`의 `Login`) 계정은 CLI로만 만든다.

``` text
계정마다 따로인 것   user_mastery, review_states, user_item_learning_state, item_exposures,
                     user_sentence_candidates, study_presentations, study_sessions, learning_events
                     -> 진도·mastery·FSRS·세션이 완전히 갈린다. 서로의 기록을 볼 수 없다
모든 계정이 공유하는 것  learning_items, sentences, sentence_items, sentence_item_explanations
                     (global content. 같은 문장 풀을 각자의 진도로 본다)
                     prompt_versions, config (학습 정책값)
                     **LLM 사용량 한도** --- 아래
```

-   **학습 대상 언어와 계정은 별개 축이다.** 계정을 언어별로 나누지 않는다. 한 계정이 두
    언어를 다 쓰고, 계정이 둘이면 각자 두 언어를 쓴다(ADR-023 결정 1, 사용자 결정 2026-10-01).
-   **`daily_request_limit` / `daily_token_limit`은 계정별이 아니라 전역이다.** 두 번째 계정이
    학습하면 소유자의 provider 키로 생성이 돌고 같은 하루 한도를 쓴다. **한도에 걸리면 모든
    계정이 함께 멈춘다**(`09_BACKGROUND_JOBS.md`의 `Cost Guard`). 비용을 계정별로 나누거나
    제한하는 수단은 MVP에 없고 만들지 않는다 --- 지인 몇 명 규모에서 그 장치의 복잡도가 이익보다
    크다.
-   **계정을 추가해도 따로 할 설정이 없다.** 첫 세션에서 그 사용자 몫의 candidate가 기존
    global content에서 만들어진다(`06_LEARNING_ENGINE.md`의 `Candidate Materialization`).
-   계정 삭제·비활성화 절차는 정하지 않았다. `users.is_active`가 있지만 그것을 쓰는 운영
    절차가 없다.

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
-   **language: `ja | en` (MVP-03)**
-   type: `word | grammar | expression`
-   lemma (표제형 = 기본형. 컬럼은 하나다 --- API가 설명 응답에서 이 값을 `canonical_form`
    이라는 이름으로 내보낸다. 문장 속 활용형은 `sentence_items.surface_form`이다)
-   reading **nullable (MVP-03)**
-   default_meaning (canonical/default 의미. 문맥 의미와 혼동 금지)
-   difficulty_label nullable (MVP는 coarse label 하나만)
-   topic_tags nullable (simple tag 목록)
-   origin: `seed | generated`
-   **seed_id nullable (MVP-03. seed 파일의 안정 키)**
-   metadata_json
-   created_at

### language와 type (MVP-03 확정)

`type`의 허용값은 **두 언어가 같다.** 영어용 값(`phrasal_verb`, `idiom`, `slang` 등)을 더하지
않는다. 구동사·관용구·담화 표지·축약형의 성격은 `topic_tags`로 적으며, 그 **고정 집합과 배정
규칙은 `spec/mvp-03-english/01_ENGLISH_CONTENT.md`가 canonical**이다. 고정 집합 강제는 seed
loader가 한다 --- DB CHECK로 배열 원소를 제약하면 집합을 바꿀 때마다 migration이 필요하다.

### reading이 nullable인 이유 (MVP-03 확정)

**영어 item은 `reading = NULL`이다.** 영어에 발음 표기(IPA·한글 근사)를 하지 않는다. IPA는
사용자가 읽을 줄 모르면 소음이고, 한글 근사는 영어 음운을 왜곡한다. 발음은 브라우저 TTS가
맡는다(ADR-025 결정 4).

**일본어는 아무것도 바뀌지 않는다.** 기존 행은 전부 non-NULL이고 loader·worker·validation이
일본어 콘텐츠에 대해 계속 값을 요구한다. 제약이 DB에서 애플리케이션으로 내려온 것뿐이다.
`language = 'ja'`일 때만 NOT NULL인 CHECK를 걸 수도 있지만, 같은 규칙을
`sentence_item_explanations`에는 걸 수 없어서(그 테이블에 `language`가 없다) 강제 위치를 한
곳으로 모은다 --- **seed loader와 생성 validation이 강제한다**(ADR-023 결정 3).

### seed_id (MVP-03 확정)

``` text
값      seed 파일의 seed_id 그대로 (it_shigoto, en_it_0001)
제약    UNIQUE (seed_id) WHERE seed_id IS NOT NULL      -- partial unique index
NULL    origin = generated 인 행
```

-   **언어를 key에 섞지 않는다.** 영어 seed 파일이 자기 이름공간(`en_`)을 쓴다. 섞으면
    `(language, seed_id)` 복합 유일성이 필요해지고, 그것은 "같은 seed_id가 두 언어에 존재할 수
    있다"는 뜻인데 그런 상태에 의미가 없다.
-   기존 일본어 seed 행의 backfill 규칙은 아래 `Seed Data`의 `증분 적재 (MVP-03 확정)`에 있다.

**MVP에 `origin = generated` 행을 만드는 경로는 없다.** worker는 요청에
실어 보낸 item만 annotate하고 새 `learning_items`를 만들지 않는다
(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`). 값은 컬럼 허용값으로
남긴다.

Future-ready: item senses, register, active-use/recognize-only, richer
difficulty, morphology provenance, audio metadata, production mastery는
모두 Future다(`spec/future/` 참조). MVP에서는 nullable 확장 여지만 남기고
구현하지 않는다.

여기의 `morphology provenance`는 **item의 형태소 분석 메타데이터**(lemma·품사 등을 분석기로 채운 기록)를
뜻하며 여전히 Future다. MVP-02의 후리가나 계산 기록은 이것이 아니다. 그것은 `sentences.ruby_json` 안의
분석기·사전 버전이고(아래 `sentences`의 `ruby_json`, ADR-021), `learning_items`에는 아무것도 더하지 않는다.

## sentences

Sentence는 **global content entity**다. "이 사용자에게 지금 어떤
목적으로 보여주는가"는 sentence가 아니라 `user_sentence_candidates`가
가진다.

-   id
-   **language: `ja | en` (MVP-03)**
-   **text** (문장 원문. MVP-03에서 `japanese`를 리네임했다 --- 아래 `text 리네임`)
-   korean_translation (두 언어 모두 한국어 번역이다)
-   source_type (MVP: `generated | seed`)
-   source_id nullable
-   difficulty_json (MVP는 coarse label 중심)
-   provenance_json (model / provider / prompt_version / generated_at /
    parent_sentence_id)
-   generation_job_id nullable
-   parent_sentence_id nullable (review context 재생성 lineage)
-   normalized_hash (duplicate 검출용 정규화 해시. **규칙이 언어별이다** ---
    `08_LLM_SPEC.md`의 `normalized_hash`)
-   status: `draft | validated | quarantined | retired`
-   ruby_json JSONB nullable (MVP-02, 후리가나. 아래 `ruby_json`)
-   **seed_id nullable (MVP-03)**
-   created_at

`sentences`에는 `user_id`도, 사용자별 role도 두지 않는다.

### text 리네임 (MVP-03 확정)

`sentences.japanese`를 `sentences.text`로 바꿨다(사용자 결정 2026-10-01, ADR-023 결정 2).
`ALTER TABLE sentences RENAME COLUMN japanese TO text`는 **데이터를 보존**하므로 운영 DB에서
안전하고 불변식 26을 어기지 않는다. 같은 이름이 네 계층에 걸쳐 함께 바뀐다.

``` text
DB              sentences.japanese              -> sentences.text
모델            Sentence.japanese               -> Sentence.text
API 응답        presentation payload "japanese" -> "text"          05_API_SPEC.md
LLM 응답 스키마  {"japanese": ...}              -> {"text": ...}    08_LLM_SPEC.md. prompt version을 올린다
LLM 요청 context avoid_japanese                 -> avoid_examples   08_LLM_SPEC.md
seed 파일        japanese:                      -> text:            두 언어 파일 모두
```

-   **`korean_translation`은 그대로 둔다.** 설명·번역 언어가 두 언어 모두 한국어이므로 이 이름은
    거짓이 아니다.
-   **배포 중 구버전 frontend가 잠시 깨진다.** 두 이름을 동시에 싣는 호환 기간을 두지 않는다 ---
    그 기간 동안 payload에 같은 값이 둘이고 떼어내는 작업이 다시 생긴다. 사용자 한 명이고
    새로고침하면 끝이다.

### ruby_json (MVP-02 확정) --- 일본어 전용 (MVP-03)

문장 전체 한자의 후리가나다. **표시 보조이며 학습 신호가 아니다**(`02_LEARNING_POLICY.md`의
`학습 신호가 아닌 것 (MVP-02)`). 결정 배경은 ADR-021이다.

**`language = 'ja'` 전용이다(불변식 23, MVP-03).** 영어 문장에는 대응물이 없다.

``` text
CHECK (language = 'ja' OR ruby_json IS NULL)
```

-   **여기는 DB CHECK를 둔다.** 아래 "DB CHECK를 두지 않는다"는 ruby **내용**의 무결성(좌표·겹침·
    경계) 이야기이고, 이 CHECK는 같은 행의 다른 컬럼 하나만 본다. 영어 문장에 ruby가 붙는 것은
    어떤 경로로도 정상이 아니므로 DB가 막는다.
-   seed loader·worker·demo fixture 스크립트는 `language = 'en'`이면 **분석기를 부르지 않고**
    계산을 건너뛴다. `scripts/backfill_ruby.py`의 대상 조회에도 `language = 'ja'`를 더한다 ---
    더하지 않으면 영어 문장이 전부 "계산 실패"로 집계되어 exit 2가 된다.

``` json
{
  "algorithm_version": 2,
  "analyzer":   {"name": "sudachipy",        "version": "0.6.11"},
  "dictionary": {"name": "sudachidict_core", "version": "20260723"},
  "split_mode": "C",
  "computed_at": "2026-09-13T09:00:00Z",
  "spans": [[5, 7, "たなか"], [10, 11, "まか"]],
  "omitted": {"tappable_boundary": 0, "numeric": 0, "no_reading": 0},
  "corrected": {"explanation_tokens": 1, "table_rules": 0}
}
```

``` text
NULL          미계산. 아직 계산하지 않았거나 계산이 예외로 끝났다. backfill의 대상이다
spans = []    계산했고 달 읽기가 없다(한자가 없거나 전부 생략). backfill 대상이 아니다
spans[i]      [start_codepoint, end_codepoint, reading]  sentence_item_spans와 같은 [start, end)
              start 오름차순, 서로 겹치지 않는다
reading       비어 있지 않은 히라가나 문자열 (U+3041..U+3096, ゝ ゞ ー)
omitted       생략 사유 세 개의 토큰 수. 값이 0이어도 키 세 개가 항상 있다
corrected     explanation_tokens = explanation.reading으로 덮인 분석기 토큰 수
              table_rules        = 교정 표 규칙이 적중한 토큰 수. 두 키가 항상 있다
computed_at   UTC ISO-8601. 호출자가 주입한 시각 (ADR-007: 계산 모듈이 시계를 읽지 않는다)
```

-   **원문 `text`와 `sentence_item_spans`를 바꾸지 않는다.** ruby는 옆 컬럼이다.
-   **모든 ruby span은 `is_tappable = true`인 span과 겹치지 않거나 그 안에 들어간다.** 경계를 넘게 되는
    토큰은 읽기를 생략한다. 정렬·교정·생략 규칙은 ADR-021이 canonical이다.
-   **provenance는 이 값 안에 둔다**(`algorithm_version`, `analyzer`, `dictionary`, `split_mode`).
    `provenance_json`에 넣지 않는다 --- 그 컬럼은 생성 provenance이고, backfill이 그 컬럼을 고치면 생성
    기록과 표시 보조의 기록이 한 값에 섞인다.
-   **`algorithm_version`**은 정렬 규칙과 교정 표를 합친 규칙 버전이다. 규칙이나 교정 표가 바뀌면 1씩
    올린다. 첫 배포 값은 2다(1은 배포된 적이 없다).
-   **DB CHECK를 두지 않는다.** 지켜야 하는 무결성(원문 길이 안, 겹침 없음, tappable 경계 안)은 다른
    컬럼·테이블과 대조해야 한다. 같은 검증 함수(`app/render.py`의 ruby 검증)를 계산 시점과 표시 시점에
    **둘 다** 부른다. 표시 시점에 통과하지 못하면 payload의 ruby를 비운다(`05_API_SPEC.md`의
    `render_segments[].ruby`).
-   **계산 지점은 넷이다:** seed 적재, worker 저장(검증 통과 뒤), backfill, demo fixture 생성. **API 요청
    경로는 이 컬럼을 읽기만 한다.** 계산 실패는 NULL로 남기고 문장은 그대로 `validated`다
    (`10_ERROR_HANDLING.md`의 `후리가나 계산 실패 (MVP-02)`).
-   미계산 잔량은 `SELECT count(*) FROM sentences WHERE ruby_json IS NULL`로 본다. 새 테이블을 두지 않는다.

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
-   reading **nullable (MVP-03)**
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

**`reading`은 `language = 'ja'`에서만 쓴다(MVP-03). 영어 설명의 `reading`은 NULL이다** --- 영어에
발음 표기를 하지 않는다(위 `learning_items`의 `reading이 nullable인 이유`). UI는 `null`이면
설명 패널에서 그 줄을 **그리지 않는다**(빈 줄이나 `-`를 넣지 않는다).

**`reading`은 문장 속 표면형의 읽기다(MVP-02 확정).** 기본형(`learning_items.lemma`. 응답에서는 `canonical_form`)의 읽기가 아니다.
예: 문장의 `任せて`에 붙은 item이면 `まかせ`처럼 span 표면형을 읽은 값이다. 기존 `explain_item_v1` prompt의
정의("the reading of the expression as it appears in this sentence")와 같다. MVP-02 후리가나 계산은 이 값을
tappable item span의 읽기로 먼저 쓴다(교정 계층 1, ADR-021).

-   **한계:** 이 뜻을 강제하는 검증은 없고 prompt도 바꾸지 않는다. **기본형 읽기가 올 가능성이 큰 곳은 현재의 주
    생성 경로다.** 문장 생성(`sentence_gen_v1`)과 review context(`review_context_v1`) prompt에는 `reading`의
    정의가 없고, 요청의 `target_items`에는 기본형(`learning_items.reading`)의 읽기가 실린다(`08_LLM_SPEC.md`의
    `요청 context`). 그래서 생성 문장에서는 교정 계층 1의 정렬이 자주 성립하지 않고 분석기 읽기로 넘어가며
    `ruby.reading_mismatch`가 늘 수 있다(`11_OBSERVABILITY.md`). 정렬이 성립하지 않으면 설명 읽기를 쓰지 않으므로
    ruby의 경계·형식 안전성은 그대로다. 설명의 `reading` 자체는 고치지 않는다.

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
-   **language: `ja | en` (MVP-03). 한 세션은 한 언어다 --- 아래 `세션 언어`**
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

### 세션 언어 (MVP-03 확정)

**한 세션은 한 언어다**(불변식 22, ADR-023 결정 7). 세션이 시작될 때 정해지고 바뀌지 않는다.

``` text
Ready Pool 조회 · candidate materialization · category mix · backlog 판정 · exploration · cold start
  -> 전부 그 세션의 language 범위 안에서만 센다        (06_LEARNING_ENGINE.md)
```

-   **섞지 않는 이유:** 섞으면 12분 세션의 70/20/10이 두 언어에 걸쳐 계산되어 한 언어의 review
    backlog가 다른 언어의 신규 공급을 줄인다. 그 결합에 학습상 근거가 없다.
-   **backlog도 세션 언어 범위에서 센다.** 영어를 쉬는 동안 쌓인 영어 복습이 일본어 세션의
    비율을 바꾸지 않는다.
-   언어를 바꾸는 경로와 409 분기는 `05_API_SPEC.md`의 `세션 언어와 409`가 canonical이다.
    **열린 세션을 조용히 닫지 않는다** --- `active_seconds`와 `summary_json`이 남는 기록이다.
-   `policy_snapshot_json`에 language를 따로 넣지 않는다. 같은 행의 컬럼이다.

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
-   **language: `ja | en` (MVP-03)**
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

### language (MVP-03 확정)

**enqueue가 job의 언어를 고정한다.** worker는 claim한 job의 `(job_type, language)`로
`prompt_versions`에서 `active = true` 행 하나를 읽는다(`08_LLM_SPEC.md`의 `Provider 선택과
model 출처`).

-   target item을 join해 파생할 수도 있지만 **컬럼으로 둔다.** 파생으로 두면 "한 job의 target
    item이 서로 다른 언어"라는 상태를 DB가 막지 못한다.
-   **한 job의 target item은 전부 같은 언어다.** enqueue 쪽이 보장한다
    (`09_BACKGROUND_JOBS.md`의 `Enqueue 트리거와 idempotency key`).
-   `idempotency_key`에 언어를 넣을지는 `09_BACKGROUND_JOBS.md`가 정한다. 키 형식의 canonical
    정의가 그쪽에 있다.
-   사용량 한도(`daily_request_limit`, `daily_token_limit`)는 **언어로 나누지 않는다.** 계정
    전체에 하나이고 UTC 일 경계로 판정한다(`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`).

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
-   **language: `ja | en` (MVP-03)**
-   version (형식은 아래)
-   provider (실행 구현 이름. `openai | stub`. `stub`은 테스트 fixture만
    만드는 값이며 `LLM_PROVIDER`의 허용값이 아니다 --- `08_LLM_SPEC.md`의
    `Provider 선택과 model 출처`)
-   model (모델 문자열. business logic에 하드코딩하지 않는다)
-   created_at
-   **active** (현재 사용 중인 버전 표시)

Unique: `(task_type, language, version)` (MVP-03. 이전에는 `(task_type, version)`이었다).

### version 형식과 active 유일성 (MVP 확정) --- MVP-03에서 언어별

``` text
task_type                ja version 형식        en version 형식
GENERATE_SENTENCE_BATCH  sentence_gen_v{n}      sentence_gen_en_v{n}
GENERATE_REVIEW_CONTEXT  review_context_v{n}    review_context_en_v{n}
EXPLAIN_ITEM             explain_item_v{n}      explain_item_en_v{n}
```

이름은 `spec/06_LLM_ENGINEERING_PRINCIPLES.md` 6번의 것을 그대로 쓰고
`{n}`은 1부터 증가하는 정수다. **prompt 본문이 바뀌면 반드시 `{n}`을
올린다.** 같은 version 행의 내용을 바꿔 재등록하면
`sentences.provenance_json.prompt_version`이 어떤 prompt를 가리키는지
사후에 알 수 없다.

-   **컬럼이 따로 있는데 version 문자열에도 언어를 적는 이유:**
    `provenance_json.prompt_version`이 **문자열 하나**이고, 그 값만 보고 어느 prompt였는지 알 수
    있어야 한다. provenance에 language를 따로 싣지 않는다 --- 문장 자체가 `sentences.language`를
    가진다(ADR-023 결정 5).
-   **prompt 본문뿐 아니라 요청 context의 키 이름이 바뀌어도 `{n}`을 올린다.** 요청 context는
    JSON으로 직렬화되어 provider 요청에 그대로 실리므로, 키 이름이 바뀌면 정적 지시문이 한
    글자도 바뀌지 않아도 모델이 받는 요청이 달라진다. `prompt_version` 하나로 "그때 무엇을
    보냈는가"를 되짚을 수 있어야 한다는 요구가 본문과 키에 똑같이 적용된다.
-   **일본어 version도 MVP-03에서 한 번 올라간다.** `sentence_gen_v2` / `review_context_v2` /
    `explain_item_v2`다. 근거는 둘로 갈린다.
    -   `sentence_gen` / `review_context`: 응답 스키마의 `japanese` → `text` 때문에 **본문이
        바뀌었다**(위 `text 리네임`).
    -   `explain_item`: 그 task의 응답 스키마에는 `japanese` 필드가 없고 **본문이 한 글자도
        바뀌지 않았다.** 올린 근거는 **요청 context 키 개명**(`japanese` → `text`,
        `08_LLM_SPEC.md`의 `요청 context`)이다. 이 근거가 없으면 "내용이 같은데 version을
        올린" 것이 되어 위 형식 원칙과 어긋난다.
-   prompt 본문 파일은 언어별 디렉터리에 둔다: `backend/app/llm/prompts/<language>/`.

`active`는 **task_type과 language의 조합당** 최대 하나이며 **partial unique index**로
강제한다(MVP-03).

``` text
UNIQUE (task_type, language) WHERE active
```

"가장 최근 행이 active"로 추론하지 않는다. 추론하면 옛 version으로
되돌리는 rollback이 불가능해진다.

**한 언어의 active 행이 없으면 그 언어의 job만 `dead_letter`다.** 다른 언어는 영향받지
않는다(`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`).

### 등록 절차

prompt 본문은 Git에 파일로 두고(`backend/app/llm/prompts/`) DB에는
registry만 둔다. 등록은 **idempotent upsert 스크립트**로 하며 직접
INSERT하지 않는다.

``` text
1. (task_type, language, version) 으로 upsert (provider / model 갱신)
2. 같은 (task_type, language)의 다른 행을 active = false 로 내린 뒤
   대상 행을 active = true 로 올린다 (한 트랜잭션)
```

worker는 실행 시점에 **job의 `(job_type, language)`로** `active = true` 행을 읽는다. 없으면 그
job은 `dead_letter`다(`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`).

## Seed Data

초급 사용자의 첫 세션을 가능하게 하기 위해 **작은 version-controlled
starter seed set**을 둔다.

-   everyday high-frequency word / grammar / expression
-   `learning_items.origin = seed`
-   빈도 정보는 새 컬럼 없이 `learning_items.metadata_json`의
    `frequency_rank`로 싣고, seed loader가 같은 `metadata_json`에
    `seed_order`(적재 순서)를 채운다. 두 값의 canonical 정의와 loader
    규약은 `06_LEARNING_ENGINE.md`의 `Exploration Item 선정`에 있다
-   **seed는 언어별 디렉터리에 둔다(MVP-03).**

    ``` text
    seed/README.md        공통 규약
    seed/ja/items.yaml  seed/ja/sentences.yaml
    seed/en/items.yaml  seed/en/sentences.yaml  seed/en/README.md (출처 표기와 라이선스)
    ```

    loader는 `--language`로 디렉터리를 고르고 **두 언어를 한 번에 적재하지 않는다** --- 한
    트랜잭션에 섞으면 한쪽 실패가 다른 쪽을 되돌린다. 파일 형식과 키 이름은 두 언어가 같고,
    문장의 원문 키는 `text:`다(위 `text 리네임`). 영어는 `reading` 키를 생략한다.
-   **영어 seed의 내용 기준은 `spec/mvp-03-english/01_ENGLISH_CONTENT.md`가 canonical이다** ---
    무엇을 고르는가, `topic_tags` 고정 집합, 설명 다섯 필드의 요구, loader 검증 11가지.
    1차 규모는 300표현 / 문장 약 1000이다.
-   **외부 어휘 자료 원본은 저장소에 넣지 않는다**(불변식 27). `data/wordlists/`에 두고
    gitignore한다. 커밋하는 것은 선별 결과와 선별 스크립트와 출처 표기다(ADR-024 결정 1).
-   seed 문장을 함께 두어 첫 세션의 new/exploration pool의 **재료**를
    확보한다. seed 적재는 `learning_items` / `sentences` /
    `sentence_items` / `sentence_item_spans` /
    `sentence_item_explanations`까지만 만들고
    **`user_sentence_candidates`는 만들지 않는다.** candidate는 사용자별
    데이터이고 적재 시점에 사용자가 없을 수 있다. Ready Pool은
    `06_LEARNING_ENGINE.md`의 `Candidate Materialization`이 세션 시작
    시점에 이 seed 콘텐츠에서 만든다.
-   정확한 개수는 제품 명세에 고정하지 않는다
-   **MVP-02:** seed 적재는 문장마다 후리가나를 계산해 같은 트랜잭션에서 `sentences.ruby_json`에 넣는다.
    입력은 원문, tappable span, seed 파일의 `explanation.reading`이다. 한 문장의 계산이 실패하면 그 문장은
    `ruby_json = NULL`로 적재하고 적재를 계속한다. 분석기 자체를 적재하지 못하면 seed 명령이 시작에서
    실패한다. 적재 출력에 계산 요약을 남긴다(`11_OBSERVABILITY.md`의 `MVP-02 추가: 후리가나 계산 결과`).
    **MVP-03: `--language en`이면 이 단계 전체를 건너뛴다** --- 분석기를 부르지 않고 `ruby_json`은
    NULL이다(불변식 23). 분석기 적재 실패도 영어 적재를 막지 않는다

seed는 Git으로 관리하고 migration 또는 별도 seed 절차로 적재한다.

### 증분 적재 (MVP-03 확정)

**MVP-01이 여기 적어 둔 `알려진 공백 --- 추가 적재 의미론이 없다`를 해소한다.** 그것이 없으면
운영 DB에 영어 seed를 넣을 수 없다 --- 현재 loader는 `origin = seed` 행이 하나라도 있으면 적재
전체를 거부하고, 운영 DB는 reset하지 않으므로(불변식 26) 다시 만드는 길도 없다. 결정 배경은
ADR-023 결정 4다.

#### 안정 키

`learning_items.seed_id`와 `sentences.seed_id`가 seed 파일의 `seed_id`를 그대로 담는다. 제약은
위 `learning_items`의 `seed_id`에 있다.

#### loader 모드

``` text
기본            지금 그대로. origin = seed 행이 하나라도 있으면 적재 전체를 거부한다. 빈 DB 전용
--incremental   파일의 seed_id 중 DB에 없는 것만 INSERT한다
                이미 있는 seed_id는 건너뛴다. 기존 행을 UPDATE하지 않는다
```

-   **이미 있는 행을 고치지 않는다.** seed 내용을 바꾸는 경로는 이 결정에 없다. 학습
    기록(`item_exposures`, `review_states`)이 붙은 item의 `lemma`를 바꾸는 것은 적재가 아니라
    콘텐츠 마이그레이션이고, 그 의미론을 정한 적이 없다. 필요해지면 그때 따로 설계한다.
-   **item을 먼저, 문장을 나중에 넣는다.** 문장의 `items[].item_seed_id`가 이미 적재된 item을
    가리킬 수 있어야 한다. 한 트랜잭션 안에서 item → sentence 순이다.
-   **부분 실패는 없다.** 한 트랜잭션이고 하나라도 실패하면 전부 롤백한다.
-   증분 적재도 `user_sentence_candidates`를 만들지 않는다(위 규칙 그대로).
-   `metadata_json.seed_order`는 **그 언어 안에서** 1부터 매긴다. 증분 적재는 그 언어의 기존
    최대 `seed_order` 다음부터 이어 붙인다 --- 재사용하면 exploration 정렬의 tie-break가
    충돌한다(`06_LEARNING_ENGINE.md`의 `seed_order`).
-   적재 출력에 요약을 남긴다: 파일 항목 수, 건너뛴 수, 넣은 수, 언어.

#### 기존 일본어 seed 행의 seed_id backfill

기존 765 문장 / 200 item에는 `seed_id`가 없다. `scripts/backfill_seed_id.py`가 채운다.

``` text
learning_items   metadata_json.seed_order = N  <->  seed/ja/items.yaml 배열의 N번째 항목
sentences        origin=seed 중 id 오름차순 N번째 <-> seed/ja/sentences.yaml 배열의 N번째 항목
```

-   `seed_order`는 loader가 1부터 매긴 적재 순서이고 seed 파일 배열 순서와 1:1이다
    (`06_LEARNING_ENGINE.md`의 `seed_order`). 문장에는 `seed_order`가 없지만 "문장 순서 =
    `sentences.id` 순서"가 seed 파일의 규약이다.
-   **대조 후에만 쓴다.** item은 `lemma`와 `reading`이, 문장은 원문 전체가 파일의 해당 항목과
    정확히 같은지 확인하고, **하나라도 다르면 아무것도 쓰지 않고 exit 2**다. 틀린 키를 붙이면
    다음 증분 적재가 다른 item을 "이미 있다"고 판단해 건너뛴다.
-   형태는 `scripts/backfill_ruby.py`와 같다(대상 출력 → 조회 → dry-run 기본 → `--apply`는
    강제 백업 → 같은 조건을 다시 건 UPDATE → 멱등).

### 알려진 공백 --- seed가 감당해야 하는 규모

**아래는 결정되지 않았다.** 사실만 적는다.

-   **MVP에서 `learning_items`의 공급원은 seed뿐이다.** worker는
    `learning_items`를 만들지 않고(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`)
    새 어휘 공급은 Future다. 반면 이 절은 seed를 "작은 starter seed set"으로,
    `06_LEARNING_ENGINE.md`의 `Cold Start`는 "첫 몇 세션"용으로 적고 있고,
    `13_ACCEPTANCE_CRITERIA.md`는 기술 검증 뒤 실제 2\~4주 사용 평가를 요구한다.
    세 조항을 합치면 **2\~4주 평가 기간에 쓰일 item 전량이 seed에서 와야 한다.**
    seed 규모는 실사용 평가 기간을 감당해야 하지만 **일본어 쪽 규모는 정하지 않았다**(위
    "정확한 개수는 제품 명세에 고정하지 않는다"는 그대로다).
-   **MVP-03에서 공급 수단은 생겼다.** 위 증분 적재로 언제든 더할 수 있으므로, 규모를 미리
    정하지 못하는 것이 더는 막다른 길이 아니다. 영어 1차 규모(300표현)는 정했고 2차 시점과
    규모는 실사용 2\~4주 뒤에 판단한다(`spec/mvp-03-english/00_SCOPE.md`의 `알려진 공백`).

## Demo Data

Public Demo는 static frontend fixture이며 **DB를 사용하지 않는다.**
demo user row, demo state, `mode` 컬럼을 두지 않는다. 따라서 demo가
private mastery를 오염시킬 경로 자체가 존재하지 않는다.

MVP-02의 demo fixture는 **`seed/` 파일에서 스크립트로 만든다.** DB에서 읽지도 DB에 적재하지도 않는다.
선택 규칙·검사·재생성 일치는 `03_UI_UX_SPEC.md`의 `Demo`의 `fixture`가 canonical이다. fixture의
ruby는 seed 적재와 같은 계산 함수로 만든다.

**MVP-03: fixture가 언어마다 하나씩이다.** `scripts/build_demo_fixture.py`가 `--language`를 받고
`seed/<language>/`를 읽어 `frontend/src/demo/<language>/fixture-data.ts`를 만든다. 선택
규칙(greedy set cover, cap 200)과 `--check` 재생성 일치는 그대로다. **영어 fixture에는 ruby가
없다** --- `language = 'en'`이면 후리가나 계산을 건너뛴다(불변식 23). 진도 저장 key도 언어별로
갈린다(`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`).

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

### MVP-02: additive migration과 후리가나 backfill (MVP-02 확정)

**운영 DB는 reset하지 않는다. MVP-02의 migration은 additive만 쓰고 기존 학습 기록을 보존한다**(불변식 19).
MVP-02 schema 변경은 `sentences`에 `ruby_json JSONB NULL`(default 없음)을 더하는 것 하나다. 적용은 위
`운영 DB에 migration을 적용하는 경로`를 그대로 따른다.

기존 문장의 ruby는 migration이 아니라 **backfill 스크립트**(`scripts/backfill_ruby.py`)가 채운다. 형태는
`scripts/db_migrate.py`와 같다.

``` text
1 대상 출력   password를 가린 DSN, 현재 algorithm_version
2 대상 조회   WHERE ruby_json IS NULL ORDER BY id
              tappable span과 explanation.reading(status = validated 중 id가 가장 작은 행)을 함께 읽는다
3 계산        메모리에서만. 요약, 규칙별 적중, 불일치 목록을 출력한다
4 dry-run     --apply가 없으면 "dry-run: nothing written"을 출력하고 7로 간다
5 --apply     쓸 행(계산에 성공한 행)이 0이면 백업 없이 7로 간다
              있으면 백업을 만들고 검증한다(--pg-bin 필수). 실패하면 쓰기 없이 exit 2
              백업을 건너뛰는 옵션은 없다
6 쓰기        한 트랜잭션. 조회와 같은 조건을 UPDATE에 다시 건다
              UPDATE sentences SET ruby_json = :value WHERE id = :id AND ruby_json IS NULL
              commit 뒤 갱신 행 수를 출력한다
7 종료 코드   계산 실패가 하나라도 있으면 쓸 행 수와 무관하게 exit 2 (dry-run, 쓸 행 0 포함)
              그 밖은 exit 0. 실패한 문장은 NULL로 남아 다음 실행이 다시 본다
```

-   **멱등 판정은 대상 조건 하나다.** 두 번째 실행은 대상 0, 백업 없음, exit 0이다(계속 실패하는 문장이 없을 때). 동시에 들어온 worker
    행이나 다른 backfill의 결과는 UPDATE에 다시 건 조건 때문에 덮어쓰지 않는다. 늦은 쪽은 0행 갱신으로
    끝난다.
-   **이미 계산된 행을 다시 계산하는 옵션은 두지 않는다.** 첫 배포 `algorithm_version`이 2라서 지금은 대상이
    없다. 교정 표·정렬 규칙·사전 버전을 바꾸는 미래 변경이 재계산 수단을 함께 설계한다. 그때까지 옛 규칙으로
    계산된 행은 그대로 남고, `ruby_json`의 버전 필드로 조회할 수 있다.
-   **API와 worker를 멈추지 않아도 된다.** 읽고 쓰는 것은 `sentences`와 콘텐츠 annotation뿐이고 학습
    테이블에 닿지 않는다. 위 migration 경로의 "3부터 4까지 멈춘다"는 migration 단계에만 적용된다.
-   **운영 대상 확인은 절차가 한다.** 스크립트는 `APP_ENV = production`을 거부하지 않는다(목적이 운영
    DB다). 운영 절차가 ADR-020 결정 7의 대상 확인 체인을 명령 앞에 둔다(`infra/DEPLOY.md`).
-   `computed_at`은 진입점이 한 번 읽은 시각을 모든 행에 넣는다(ADR-007).
-   **되돌림:** 표시 보조 컬럼이므로 `UPDATE sentences SET ruby_json = NULL`로 충분하다. 강제 백업은 이
    되돌림과 무관하게 유지한다.
-   Makefile 타깃 이름은 구현이 정한다.

### MVP-03: 다언어 migration과 seed_id backfill (MVP-03 확정)

**운영 DB는 reset하지 않는다. MVP-03의 migration은 비파괴만 쓴다**(불변식 26) --- 컬럼 추가,
컬럼 리네임, NOT NULL 완화, 제약·index 교체까지이며 **테이블·컬럼을 DROP하지 않는다.** 적용은 위
`운영 DB에 migration을 적용하는 경로`를 그대로 따른다(대상 출력 → pending 확인 → 강제 백업 →
upgrade, 그 사이 API·worker 정지).

MVP-02의 불변식 19("additive migration만")를 MVP-03이 **비파괴 전체**로 넓혔다. rename과 NOT
NULL 완화는 additive가 아니지만 데이터를 잃지 않는다. 그 둘이 필요한 이유는 ADR-023 결정 2·3에
있다.

#### 한 migration이 하는 일

``` text
1 RENAME    sentences.japanese -> sentences.text
2 ADD       learning_items.language, sentences.language, study_sessions.language,
            prompt_versions.language, generation_jobs.language
            (NULL로 추가 -> UPDATE ... SET language = 'ja' -> SET NOT NULL + CHECK)
3 ADD       learning_items.seed_id, sentences.seed_id   (TEXT NULL)
            + UNIQUE (seed_id) WHERE seed_id IS NOT NULL
4 DROP NOT NULL   learning_items.reading, sentence_item_explanations.reading
5 ADD CHECK (sentences.language = 'ja' OR sentences.ruby_json IS NULL)
6 REPLACE   prompt_versions UNIQUE (task_type, version)      -> (task_type, language, version)
            prompt_versions UNIQUE (task_type) WHERE active  -> (task_type, language) WHERE active
```

-   **2의 세 단계가 한 migration 안에 있다.** `server_default`를 두지 않으므로 중간의 UPDATE가
    기존 행을 채운다. 기본값을 두면 언어를 빠뜨린 INSERT가 조용히 일본어가 된다.
-   **5의 CHECK는 기존 행에서 바로 성립한다.** 기존 문장은 전부 `language = 'ja'`다.
-   **`downgrade()`는 빈 DB 왕복 테스트용이다.** 운영 롤백은 downgrade가 아니라 백업 복원이다
    (위 규칙 그대로). rename의 downgrade는 데이터를 보존하지만, 그 사실이 운영 경로에 downgrade를
    두는 근거가 되지 않는다 --- 같은 migration의 다른 단계(컬럼 추가)는 되돌리면 데이터를 지운다.

#### 제약·index 이름

**이름 없는 제약을 만들지 않는다.** 이름이 없으면 `downgrade()`에서 DROP할 수 없고, migration이
무엇을 바꿨는지를 이름 집합으로 대조할 수도 없다. 이 migration이 더하는 것과 빼는 것의 이름은
다음으로 고정된다.

``` text
더하는 것
ck_learning_items_language                       CHECK language IN ('ja','en')   convention
ck_sentences_language                            같음                            convention
ck_study_sessions_language                       같음                            convention
ck_prompt_versions_language                      같음                            convention
ck_generation_jobs_language                      같음                            convention
ck_sentences_ruby_json_ja_only                   CHECK (language='ja' OR ruby_json IS NULL)  convention
uq_learning_items_seed_id                        partial unique index            명시
uq_sentences_seed_id                             partial unique index            명시
uq_prompt_versions_task_type_language_version    UNIQUE (task_type, language, version)  convention
uq_prompt_versions_active                        partial unique index. 이름 유지, 컬럼만 교체  명시

빼는 것
uq_prompt_versions_task_type_version             위 unique가 대체한다
```

-   **`convention`으로 적은 이름은 SQLAlchemy metadata의 naming convention에서 유도된다**
    (`ck_%(table_name)s_%(constraint_name)s`, `uq_%(table_name)s_%(column_0_N_name)s`). 모델은
    제약 이름을 적지 않고 뒷부분(`language`, `ruby_json_ja_only`)만 주며, migration은 애플리케이션
    코드를 import하지 않으므로 같은 결과를 `op.f()`로 고정한다. **convention은 첫 migration 전에
    고정했고 바꾸지 않는다** --- 바꾸면 이미 적용된 제약의 이름이 전부 달라진다.
-   **`명시`로 적은 셋은 convention을 타지 않는다.** index는 `ix_%(column_0_label)s`를 타므로
    이름을 주지 않으면 unique index에 `ix_` 접두가 붙고, 컬럼을 나열하는 `uq` 형식을 흉내 내면
    PostgreSQL identifier 한계(63자)에서 잘린다. 그래서 짧은 이름을 직접 적는다.
-   **`uq_prompt_versions_active`는 이름을 유지하고 컬럼만 `(task_type)` → `(task_type,
    language)`로 바꾼다.** 이 이름은 구현에서 상수다.
-   `language` enum은 PostgreSQL native enum이 아니라 **VARCHAR + 명명된 CHECK**다(기존 enum
    컬럼과 같은 물리 타입). 그래서 2단계가 더하는 것이 type이 아니라 위 `ck_*_language`다.

#### migration이 하지 않는 것

``` text
seed_id 채우기        scripts/backfill_seed_id.py 가 한다 (위 Seed Data)
영어 seed 적재        load_seed --language en --incremental 이 한다
prompt_versions 행    등록 스크립트가 한다 (위 prompt_versions의 등록 절차)
```

-   **셋 다 migration 밖이다.** migration은 schema만 바꾸고 콘텐츠를 넣지 않는다. 기존 규칙과
    같다 --- MVP-02의 후리가나 backfill도 migration이 아니라 스크립트였다.
-   **순서가 있다.** schema migration → `backfill_seed_id` → prompt 등록 → 영어 seed 증분 적재.
    `backfill_seed_id`가 먼저여야 증분 적재가 기존 일본어 행을 "이미 있다"고 올바로 판단한다.
    운영 절차는 `infra/DEPLOY.md`가 적는다.

#### 되돌림

``` text
컬럼 추가·리네임    백업 복원 (위 규칙 그대로)
seed_id backfill    UPDATE ... SET seed_id = NULL. 그러나 증분 적재를 이미 했다면 복원이 맞다
영어 seed 적재      DELETE 하지 않는다. 학습 기록이 붙었을 수 있다. 복원이 맞다
```
