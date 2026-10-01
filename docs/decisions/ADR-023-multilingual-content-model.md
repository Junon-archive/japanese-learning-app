# ADR-023 --- 다언어 콘텐츠 모델 (일본어 + 영어)

Status: Accepted

Decision: 학습 대상 언어를 **콘텐츠 엔티티의 축**으로 넣는다. `learning_items`와 `sentences`에
`language`를 더하고, `study_sessions`와 `prompt_versions`와 `generation_jobs`에도 같은 값을 둔다.
**사용자별 학습 테이블에는 두지 않는다** --- `learning_item_id`가 이미 언어를 결정한다. 일본어 전용
이름인 `sentences.japanese`는 `sentences.text`로 리네임하고, 일본어 전용 기능(후리가나, 가나 학습)은
`language = 'ja'`에만 성립하는 것으로 명시한다. seed는 안정 키 `seed_id`를 DB에 저장해 **증분 적재**가
가능해진다.

``` text
language 축을 갖는 것      learning_items, sentences, study_sessions, prompt_versions, generation_jobs
language 축을 갖지 않는 것 user_mastery, review_states, user_item_learning_state, item_exposures,
                           user_sentence_candidates, study_presentations, learning_events
                           (learning_item_id / sentence_id가 언어를 결정한다)
허용값                     ja | en     (CHECK. 세 글자 이상으로 늘릴 계획을 지금 두지 않는다)
리네임                     sentences.japanese -> sentences.text
                           LLM 응답 스키마 japanese -> text      (prompt version을 올린다)
                           요청 context avoid_japanese -> avoid_examples
NULL 허용으로 완화          learning_items.reading, sentence_item_explanations.reading
                           (영어는 발음 표기를 하지 않는다. NULL)
일본어 전용                 sentences.ruby_json (CHECK: language = 'en'이면 NULL), 형태소 분석기, 가나 학습
seed 안정 키               learning_items.seed_id, sentences.seed_id (TEXT NULL, partial UNIQUE)
세션                       한 세션은 한 언어. study_sessions.language NOT NULL
```

`spec/`에 반영하기 전까지 구현 근거가 아니다(사용자 결정 2026-10-01).

---

## 맥락

사용자 결정(2026-10-01): 기존 일본어 학습 앱에 **영어 학습을 기능으로 더한다.** 새 앱을 만들지 않고
같은 Learning Engine·FSRS·mastery·LLM 생성 파이프라인을 그대로 쓴다. 첫 화면에서 일본어와 영어를
고른다.

현재 schema는 일본어를 전제한 곳이 여섯 군데다.

``` text
sentences.japanese                      컬럼 이름 자체가 언어다
learning_items.reading NOT NULL         가나 읽기를 전제한다
sentence_item_explanations.reading       같다
sentences.ruby_json + SudachiPy          후리가나. 영어에 대응물이 없다 (ADR-021)
prompt_versions (task_type, version)     active 유일성이 task_type 하나다. 언어별 프롬프트를 둘 수 없다
frontend/src/kana/                       가나 학습. 영어에 대응물이 없다
```

반대로 **언어와 무관한 것이 훨씬 많다.** FSRS scheduling, mastery EMA, probe 정책, context stage
ladder, meaningful exposure, candidate materialization, category mix, backlog, 세션 구조, 이벤트
모델은 전부 "item"과 "sentence"만 알고 언어를 모른다. 그래서 축 하나를 더하는 것으로 끝낼 수 있다.

### 셋 중 무엇을 하는가

``` text
(A) language 컬럼        콘텐츠 엔티티에 축을 하나 더한다
(B) 언어별 계정          일본어 계정 / 영어 계정을 따로 만든다
(C) 언어별 테이블 세트   english_items, english_sentences ... 를 따로 만든다
```

사용자가 (A)를 골랐다(2026-10-01). (B)는 schema를 거의 안 바꾸지만 로그인이 둘이 되고, 한 사람의
학습 기록이 두 계정으로 갈라져 `GET /api/auth/me`·history·백업·계정 생성이 전부 두 벌이 된다.
(C)는 엔진·SRS·이벤트 경로가 두 벌이 되어 "기존 알고리즘을 알차게 재사용한다"는 요구와 정면으로
어긋난다. 둘 다 버린다.

---

## 결정 1 --- `language`를 어디에 두는가

### 두는 곳

``` text
learning_items.language    TEXT NOT NULL  CHECK (language IN ('ja','en'))
sentences.language         TEXT NOT NULL  CHECK (language IN ('ja','en'))
study_sessions.language    TEXT NOT NULL  CHECK (language IN ('ja','en'))
prompt_versions.language   TEXT NOT NULL  CHECK (language IN ('ja','en'))
generation_jobs.language   TEXT NOT NULL  CHECK (language IN ('ja','en'))
```

-   `learning_items`와 `sentences`가 **진짜 출처**다. 나머지 셋은 그 둘에서 파생될 수 있지만 파생으로
    두면 안 되는 이유가 각각 있다.
    -   `study_sessions`: 세션을 **시작할 때** 언어가 정해지고, 그 시점에는 아직 presentation이
        없어서 파생할 대상이 없다. 빈 세션의 언어를 물을 수 없으면 Ready Pool 조회의 입력이 없다.
    -   `prompt_versions`: 아래 `결정 5`.
    -   `generation_jobs`: worker가 job을 claim한 시점에 **어느 prompt를 쓸지** 정해야 한다. target
        item을 join해서 파생할 수는 있지만, 그러면 "한 job의 target item이 서로 다른 언어"라는 불가능한
        상태를 DB가 막지 못한다. 컬럼으로 두면 enqueue가 한 언어로 고정한다.

### 두지 않는 곳과 그 이유

``` text
user_mastery, review_states, user_item_learning_state, item_exposures
user_sentence_candidates, user_sentence_candidate_targets, study_presentations, learning_events
```

-   **`learning_item_id` 또는 `sentence_id`가 이미 언어를 결정한다.** 같은 값을 두 곳에 두면 한쪽만
    고쳐지는 순간 갈라진다. 사용자 한 명 규모에서 join 비용은 문제가 되지 않는다.
-   특히 `user_sentence_candidates`에 두고 싶은 유혹이 있다 --- Ready Pool 조회가 매번
    `sentences`를 join해야 하기 때문이다. 두지 않는다. 그 join은 어차피 `status`·`difficulty_json`
    때문에 하고 있고, denormalize하면 "sentence의 언어"와 "candidate의 언어"가 다른 상태를 만들 수
    있다. 그 상태에 의미가 없다.
-   **`users`에도 두지 않는다.** 사용자는 두 언어를 다 쓴다. "마지막으로 고른 언어"를 저장하고 싶어질
    수 있지만 그것은 학습 상태가 아니라 UI 편의값이고, 공개 화면의 언어 선택은 서버를 부르지 않는다
    (불변식 13). 필요해지면 브라우저에 둔다.

### 값

`ja`와 `en` 둘뿐이다. **세 번째 언어를 위한 구조를 지금 만들지 않는다.** BCP 47 전체를 허용하거나
`languages` 테이블을 두는 것은 지금 쓰지 않는 유연성이고(`CLAUDE.md` 2번), CHECK 제약에 값을 더하는
migration은 나중에도 싸다.

### 기존 행의 처리

migration은 한 파일 안에서 세 단계를 한다. **데이터를 지우지 않으므로 additive 규칙(불변식 19)을
어기지 않는다.**

``` text
1  ADD COLUMN language TEXT NULL
2  UPDATE <table> SET language = 'ja'      (기존 행은 전부 일본어다)
3  ALTER COLUMN language SET NOT NULL + CHECK 추가
```

**server_default를 두지 않는다.** 기본값을 두면 언어를 넣는 것을 잊은 INSERT가 조용히 일본어가
된다. 2단계가 기존 행을 채우므로 기본값이 필요 없다.

---

## 결정 2 --- `sentences.japanese`를 `sentences.text`로 리네임한다

사용자 결정(2026-10-01). `ALTER TABLE sentences RENAME COLUMN japanese TO text`는 **데이터를
보존**하므로 운영 DB에서 안전하다. 같은 migration 안에서 `결정 1`과 함께 적용한다.

같은 리네임이 네 계층에 걸친다.

``` text
DB            sentences.japanese            -> sentences.text
모델          Sentence.japanese             -> Sentence.text
API 응답      presentation payload "japanese" -> "text"
LLM 응답 스키마 {"japanese": ...}            -> {"text": ...}        prompt version을 올린다
LLM 요청 context avoid_japanese             -> avoid_examples
```

-   **`korean_translation`은 그대로 둔다.** 설명·번역 언어는 한국어로 고정이므로(`결정 6`) 이 이름은
    거짓이 아니다. 영어 문장의 `korean_translation`도 한국어다.
-   **LLM 응답 스키마가 바뀌므로 prompt version을 올린다.** 같은 version 행의 내용을 바꿔 재등록하지
    않는다(`04_DB_SPEC.md`의 `version 형식과 active 유일성`). 기존 일본어 prompt도 `sentence_gen_v2`로
    올라가며, 본문 변경은 필드 이름 하나다.
-   **운영 배포 중 구버전 frontend가 잠시 깨진다.** 응답 필드 이름이 바뀌므로 배포 사이에 열려 있던
    탭은 문장을 못 그린다. 사용자 한 명이고 새로고침하면 끝이라 받아들인다. 두 이름을 동시에 싣는
    호환 기간을 두지 않는다 --- 그 기간 동안 payload에 같은 값이 둘이고, 떼어내는 작업이 다시 생긴다.

### 버린 대안

-   **이름 유지, 영어도 `japanese` 컬럼에 저장.** 변경이 가장 작지만 앞으로 이 코드를 읽는 모든
    사람이 매번 헷갈린다. 사용자가 이 안을 명시적으로 거절했다.
-   **`text`를 새로 추가하고 `japanese`를 단계적으로 폐기.** additive 규칙에 가장 엄밀히 맞지만,
    중간 기간 동안 두 컬럼을 동기화해야 하고 그 동기화가 어긋날 수 있다. rename이 데이터를 보존하는
    이상 더 안전하지 않다.

---

## 결정 3 --- `reading`을 nullable로 완화한다

``` text
learning_items.reading                NOT NULL -> NULL 허용
sentence_item_explanations.reading    NOT NULL -> NULL 허용
```

-   **영어 item은 `reading = NULL`이다.** 영어에 발음 표기(IPA·한글 근사)를 하지 않는다. IPA는
    사용자가 읽을 줄 모르면 소음이고, 한글 근사는 영어 음운을 왜곡해서 외운 발음을 고치기 어렵게
    만든다. 발음은 `ADR-025`의 브라우저 TTS가 맡는다.
-   **일본어는 아무것도 바뀌지 않는다.** 기존 행은 전부 non-NULL이고 loader·worker·validation이
    일본어 콘텐츠에 대해 계속 값을 요구한다. 제약이 DB에서 애플리케이션으로 내려온 것이다.
-   NOT NULL을 푸는 것은 **제약 완화**라서 기존 데이터를 건드리지 않는다.
-   API는 `/click` 응답의 `reading`이 `null`일 수 있게 되고, UI는 `null`이면 그 줄을 **그리지 않는다**
    (빈 줄이나 `-`를 넣지 않는다).

### 언어별 필수 여부는 어디서 강제하는가

DB CHECK로 "`language = 'ja'`이면 `reading IS NOT NULL`"을 걸고 싶어지지만 `learning_items`는 걸 수
있어도 `sentence_item_explanations`는 **`language` 컬럼이 없다**(결정 1: sentence를 통해 결정된다).
교차 테이블 CHECK는 PostgreSQL이 지원하지 않는다. 그래서 강제는 세 곳의 애플리케이션 검사다.

``` text
seed loader            ja 항목에 reading이 없으면 적재 실패
생성 validation        ja 문장의 explanation.reading이 없으면 그 문장을 버린다 (08_LLM_SPEC.md)
backfill/스크립트      같은 규칙을 쓴다
```

---

## 결정 4 --- seed 안정 키와 증분 적재

**이것이 없으면 운영 DB에 영어 seed를 넣을 수 없다.** 현재 loader는 `origin = seed` 행이 하나라도
있으면 적재 전체를 거부하고, `learning_items`에 seed 파일의 키가 저장되지 않아 "이미 적재된 것"을
식별할 방법이 없다(`04_DB_SPEC.md`의 `알려진 공백 --- seed가 감당해야 하는 규모와 추가 적재`).
운영 DB는 reset하지 않으므로(불변식 19) 다시 만드는 길도 없다.

### 안정 키

``` text
learning_items.seed_id  TEXT NULL
sentences.seed_id       TEXT NULL
UNIQUE (seed_id) WHERE seed_id IS NOT NULL      -- partial unique index
```

-   값은 seed 파일의 `seed_id`(`it_shigoto`, `sn_0001`)를 그대로 쓴다. **파일이 이미 가지고 있는
    키이고 사람이 읽을 수 있다.**
-   `origin = generated` 행은 `seed_id = NULL`이다. 그래서 partial unique다.
-   **key에 언어를 섞지 않는다.** 영어 seed 파일은 자기 이름공간을 쓴다(`en_it_0001`). 섞으면
    `(language, seed_id)` 복합 유일성이 필요해지고, 그러면 같은 `seed_id`가 두 언어에 존재할 수
    있다는 뜻이 되는데 그런 상태에 의미가 없다.

### 기존 일본어 seed 행의 backfill

기존 765 문장 / 200 item에는 `seed_id`가 없다. **`metadata_json.seed_order`로 복원한다.**

``` text
learning_items   seed_order N 인 행  <->  seed/items.yaml 배열의 N번째 항목의 seed_id
sentences        id 오름차순 N번째 seed 문장 <-> seed/sentences.yaml 배열의 N번째 항목의 seed_id
```

-   `seed_order`는 loader가 1부터 매긴 적재 순서이고 seed 파일 배열 순서와 1:1이다
    (`06_LEARNING_ENGINE.md`의 `seed_order`). 문장에는 `seed_order`가 없지만 "문장 순서 = `sentences.id`
    순서"가 seed 파일의 규약이다(`seed/sentences.yaml` 머리 주석).
-   backfill 스크립트는 **대조 후에만 쓴다.** item은 `lemma`와 `reading`이, 문장은 원문 전체가 seed
    파일의 해당 항목과 정확히 같은지 확인하고, 하나라도 다르면 **아무것도 쓰지 않고 exit 2**다.
    형태는 `scripts/backfill_ruby.py`와 같다(대상 출력 → 조회 → dry-run → `--apply`는 강제 백업 →
    같은 조건을 다시 건 UPDATE).
-   대조가 깨지는 경우(누군가 seed 파일 중간에 항목을 끼워 넣은 적이 있는 경우)에는 **실패가
    정답이다.** 틀린 키를 붙이면 다음 증분 적재가 다른 item을 "이미 있다"고 판단해 건너뛴다.

### loader의 증분 모드

``` text
기존 동작   origin = seed 행이 하나라도 있으면 적재 전체 거부
새 동작     --incremental:  파일의 seed_id 중 DB에 없는 것만 INSERT한다
                            이미 있는 seed_id는 건너뛴다. 기존 행을 UPDATE하지 않는다
            기본(비-incremental): 지금 그대로. 빈 DB 전용
```

-   **이미 있는 행을 고치지 않는다.** seed 내용을 바꾸는 경로는 이 결정에 없다. 바꾸고 싶으면
    그 변경을 따로 설계한다 --- 이미 학습 기록(`item_exposures`, `review_states`)이 붙은 item의
    `lemma`를 바꾸는 것은 적재가 아니라 콘텐츠 마이그레이션이고, 그 의미론을 정한 적이 없다.
-   **문장은 item보다 나중에 넣는다.** 문장의 `items[].item_seed_id`가 이미 적재된 item을 가리킬 수
    있어야 한다. 한 트랜잭션 안에서 item → sentence 순이다.
-   **부분 실패는 없다.** 한 트랜잭션이고 하나라도 실패하면 전부 롤백한다.
-   증분 적재도 일반 적재와 같이 `user_sentence_candidates`를 만들지 않는다.
-   증분 적재 뒤 요약을 출력한다: 파일의 항목 수, 건너뛴 수, 넣은 수, 언어별 내역.

---

## 결정 5 --- `prompt_versions`에 `language`를 더하고 active 유일성을 `(task_type, language)`로 바꾼다

``` text
현재   UNIQUE (task_type, version)
       UNIQUE (task_type) WHERE active
바뀜   UNIQUE (task_type, language, version)
       UNIQUE (task_type, language) WHERE active
```

-   worker는 job의 `(job_type, language)`로 `active = true` 행 하나를 읽는다. 없으면 그 job은
    `dead_letter`다(지금 규칙 그대로).
-   **version 문자열에 언어를 넣는다.** `sentence_gen_v2` / `sentence_gen_en_v1`처럼 적는다. 컬럼이
    따로 있는데 이름에도 넣는 이유는 `sentences.provenance_json.prompt_version`이 **문자열 하나**이고,
    그 값만 보고 어느 prompt였는지 알 수 있어야 하기 때문이다. provenance에 language를 따로 싣지
    않는다(문장 자체가 `sentences.language`를 가진다).
-   prompt 본문 파일도 언어별로 나눈다: `backend/app/llm/prompts/<language>/`.
-   기존 행의 migration: 전부 `language = 'ja'`로 채운다(`결정 1`의 3단계와 같은 방식).

---

## 결정 6 --- 일본어 전용 기능의 경계

``` text
후리가나(sentences.ruby_json)   language = 'ja' 전용.  CHECK (language = 'ja' OR ruby_json IS NULL)
형태소 분석기(SudachiPy)        language = 'ja' 콘텐츠를 적재·생성할 때만 부른다
가나 학습                       일본어 홈에만 있다
설명·번역 언어                  두 언어 모두 한국어다
```

-   **`ruby_json`에 CHECK를 건다.** `language` 컬럼이 같은 테이블에 있으므로 DB가 강제할 수 있다.
    영어 문장에 ruby가 붙는 것은 어떤 경로로도 정상이 아니다.
-   seed loader와 worker는 `language = 'en'`이면 후리가나 계산을 **건너뛴다.** 분석기를 부르지
    않는다. worker 부팅의 분석기 적재 검사(`08_LLM_SPEC.md`)는 그대로 유지한다 --- 같은 worker가
    일본어 job도 처리한다.
-   `scripts/backfill_ruby.py`의 대상 조회에 `language = 'ja'`를 더한다. 더하지 않으면 영어 문장이
    전부 "계산 실패"로 집계되어 exit 2가 된다.
-   **설명·번역은 두 언어 모두 한국어다.** `meaning_in_context`, `nuance`, `korean_translation`이
    전부 한국어다. 영어를 쉬운 영어로 설명하는 것(explanation language progression)은
    `spec/05_LEARNING_SYSTEM_VISION.md`가 이미 Future로 둔 항목이고 여기서 열지 않는다.

---

## 결정 7 --- 한 세션은 한 언어다

``` text
study_sessions.language          NOT NULL
POST /api/study/session          request body에 language 필수
Ready Pool 조회·candidate 생성    그 세션의 language로 범위를 좁힌다
Exploration·Cold Start           같다
```

-   **한 세션에 두 언어를 섞지 않는다.** 섞으면 12분 세션의 category mix(70/20/10)가 두 언어에
    걸쳐 계산되어, 한 언어의 review backlog가 다른 언어의 신규 공급을 줄인다. 그 결합에 학습상
    근거가 없다.
-   **다른 언어로 바꾸려면 지금 세션을 끝낸다.** 열린 세션이 있는데 다른 `language`로
    `POST /api/study/session`을 부르면 **409**이고, 응답이 열린 세션의 id와 언어를 알려준다. 화면은
    "일본어 학습이 진행 중이에요"를 보여주고 사용자가 누르면 `finish` 뒤 새 세션을 만든다.
    -   **조용히 기존 세션을 닫지 않는다.** `active_seconds`와 `summary_json`이 남는 기록이고,
        사용자가 의도하지 않은 종료로 그 값이 끊기면 안 된다.
    -   idle timeout(30분)을 넘겼으면 어차피 새 세션이므로 이 분기에 닿지 않는다.
-   `GET /api/study/session`의 응답에 `language`를 싣는다. 언어를 모르면 화면이 어느 언어로
    이어가는지 그릴 수 없다.
-   backlog 판정(`backlog_threshold`)도 **세션 언어 범위 안에서** 센다. 영어를 쉬는 동안 쌓인
    영어 복습이 일본어 세션의 비율을 바꾸지 않는다.

---

## 결정 8 --- 사용자별 학습 데이터는 그대로다

**바뀌지 않는 것을 명시한다.** 아래는 전부 `learning_item_id` 단위라서 언어가 섞이지 않는다.

``` text
FSRS scheduling (review_states)        item별이다
mastery EMA (user_mastery)             item별이다
meaningful exposure (item_exposures)   item별이다
context stage ladder                   item별이다
probe cooldown·우선순위                 item별이다
learning_events                        presentation을 통해 언어가 결정된다
```

-   **`user_mastery`에 언어별 집계를 두지 않는다.** history 화면이 언어별로 보고 싶어지면 조회에서
    join하면 된다. 저장하면 두 번째 source of truth가 된다.
-   `starting_level`(`users.starting_level`)은 **계정 하나에 하나**다. 일본어는 초급이고 영어는
    중급인 상태를 지금 표현하지 못한다. 이 값의 유일한 소비처는 생성 프롬프트의 `learner_level`이다
    (`08_LLM_SPEC.md`의 `요청 context`). **이번에 고치지 않는다** --- 사용자 한 명이고, 고치려면
    `users`에 언어별 레벨을 두거나 새 테이블을 만들어야 하는데 둘 다 "실사용 후 바꿀 값"이다.
    `spec/mvp-03-english/00_SCOPE.md`의 `알려진 공백`에 기록한다.

---

## 결과

### 바뀌는 schema (한 migration, 전부 비파괴)

``` text
ALTER TABLE sentences      RENAME COLUMN japanese TO text
ADD   learning_items.language, sentences.language, study_sessions.language,
      prompt_versions.language, generation_jobs.language        (NULL -> 'ja' 채움 -> NOT NULL + CHECK)
ADD   learning_items.seed_id, sentences.seed_id                 (TEXT NULL + partial UNIQUE)
ALTER learning_items.reading                DROP NOT NULL
ALTER sentence_item_explanations.reading    DROP NOT NULL
ADD   CHECK (sentences.language = 'ja' OR sentences.ruby_json IS NULL)
DROP  UNIQUE (prompt_versions.task_type, version)        -> (task_type, language, version)
DROP  UNIQUE (prompt_versions.task_type) WHERE active    -> (task_type, language) WHERE active
```

### 바뀌는 문서

``` text
spec/03_DOMAIN_MODEL.md                    Language 절 (신규)
spec/mvp-01-core/04_DB_SPEC.md             위 schema 전부, Seed Data의 증분 적재, 알려진 공백 해소
spec/mvp-01-core/05_API_SPEC.md            payload의 text, 세션 language, 409 분기
spec/mvp-01-core/06_LEARNING_ENGINE.md     Ready Pool·materialization·exploration·cold start의 언어 범위
spec/mvp-01-core/08_LLM_SPEC.md            응답 스키마 text, avoid_examples, 언어별 prompt, ja 전용 ruby 계산
spec/mvp-01-core/09_BACKGROUND_JOBS.md     job의 language, enqueue가 언어를 고정한다
spec/mvp-03-english/00_SCOPE.md            범위 delta와 불변식
```

### 버린 대안 모음

-   **`languages` 테이블과 FK.** 두 행짜리 테이블에 join을 하나 더한다. CHECK로 충분하다.
-   **BCP 47 전체 허용(`ja-JP`, `en-US`).** 지역 변종을 구분할 계획이 없는데 값 공간만 넓어진다.
    영어 발음은 미국 영어를 전제하지만 그것은 TTS 음성 선택(`ADR-025`)이지 콘텐츠 축이 아니다.
-   **`user_sentence_candidates.language` denormalize.** 위 `결정 1`.
-   **두 번째 DB / schema 분리.** 백업·migration·접속이 두 벌이 된다. 사용자 한 명 규모에서 얻는
    것이 없다.
