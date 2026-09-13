# LLM Specification

MVP tasks: - `GENERATE_SENTENCE_BATCH` - `EXPLAIN_ITEM` (background
repair job 전용) - `GENERATE_REVIEW_CONTEXT`

이 세 이름은 `generation_jobs.job_type` 값과 그대로 같다. 허용값 집합의
canonical 정의는 `04_DB_SPEC.md`의 `generation_jobs`에 있다.

`ANALYZE_SENTENCE`는 **MVP에서 호출자가 없으므로 MVP task 목록에서
제외하고 Future로 이동한다**(`spec/future/CONTENT_SYSTEM.md`). MVP
콘텐츠는 전부 generation 결과이므로 기존 문장을 다시 구조화할 경로가
없다.

가능하면 generation에서 translation/item
annotation/reading/meaning/provenance까지 한 번에 생성.
Structured output 사용. Prompt version 기록. Batch/Ready Pool/재사용
우선. Public Demo generation 금지. 모델명은 business logic에 고정하지
않는다.

register metadata는 생성하더라도 MVP에서는 저장·사용하지 않는다
(`00_SCOPE.md`). register 기반 content control은 Future다.

## LLM 호출 경계 (MVP 확정)

**MVP에서 모든 외부 LLM provider 호출은 background worker에서만
발생한다.**

FastAPI user request handler는 다음까지만 한다.

``` text
DB 읽기
event 저장
candidate 선택
필요 시 job enqueue
```

다음은 금지한다.

``` text
item tap        -> live provider call   금지
next sentence   -> live provider call   금지
translation reveal -> live provider call 금지
```

Ready Pool이 비어도 request handler에서 provider를 synchronous 호출하지
않는다. 대신 `06_LEARNING_ENGINE.md`의 Pool Fallback을 따른다.

### Task별 호출 주체

``` text
GENERATE_SENTENCE_BATCH  -> worker only
GENERATE_REVIEW_CONTEXT  -> worker only
EXPLAIN_ITEM             -> worker only (missing explanation repair job)
```

`GENERATE_SENTENCE_BATCH`는 가능한 한 한 번의 structured output으로
다음까지 생성한다.

``` text
sentence
translation
SentenceItems
spans
contextual explanations
```

이렇게 해야 사용자가 item을 tap한 순간 live LLM fallback이 필요 없다
(아래 Ready invariant, `04_DB_SPEC.md`의
`sentence_item_explanations`).

## Provider 선택과 model 출처 (MVP 확정)

두 축을 섞지 않는다.

``` text
어떤 client 코드를 쓰는가    환경변수 LLM_PROVIDER = openai  (기본값 없음)
어떤 모델에 무엇을 보내는가  prompt_versions 행 (task_type, version, provider, model)
```

-   **모델명과 provider 이름을 코드나 config YAML에 고정하지 않는다**
    (원칙 8). worker는 job의 `job_type`으로 `prompt_versions`에서
    `active = true`인 행 하나를 읽고 그 행의 `model`을 요청에 쓴다. 행이
    없으면 재시도해도 결과가 같으므로 그 job은 `dead_letter`다
    (`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`).
-   `LLM_API_KEY`는 **worker 프로세스에만** 주입한다. API 프로세스는
    provider client를 만들지 않으므로 키를 읽지 않는다. 두 환경변수의
    canonical 정의는 `spec/04_SECURITY_AND_DATA.md`의
    `LLM provider 자격증명 (MVP 확정)`이다.
-   **실제 키 없이 generation 경로 전체를 실행하는 수단은 주입이다.**
    프로세스 진입점(`scripts/run_worker.py`)이 `LLM_PROVIDER` /
    `LLM_API_KEY`를 읽어 `build_provider(name, api_key=...)`로 client를
    만들고 **worker loop에 인자로 넘긴다.** 테스트는 같은 인자 자리에
    `backend/tests/`의 test double(고정 fixture를 돌려주고 네트워크를 쓰지
    않는다)을 넣는다. 그래서 claim / lease / validation / 저장 / completed가
    전부 실제 코드로 실행되면서 provider 호출만 대체된다.
-   **mock을 가리키는 `LLM_PROVIDER` 값은 없다.** 앱 코드에 mock 구현을 두지
    않는다(ADR-015). `APP_ENV = production` 검사로 막던 것을 구현체의 부재로
    막는다. `LLM_PROVIDER`가 없거나 허용값이 아니면, 또는 `openai`인데 키가
    없으면 worker가 부팅에 실패한다(fail-closed). 근거와 버린 대안은
    `docs/decisions/ADR-016-llm-provider-selection.md`(원안 개정 포함).
-   test double의 응답도 **똑같은 deterministic validation을 통과해야**
    저장된다. 검증을 건너뛰는 경로를 만들면 mock으로 통과한 Wave 3이 실제
    provider에서 처음 실패한다.
-   provider SDK는 `build_provider`가 고른 구현체 모듈 안에서만 import한다.
    API 프로세스는 그 모듈을 적재하지 않으며, `12_TEST_PLAN.md`의 request
    경로 테스트가 그 사실을 검사한다. SDK 버전은 명세가 아니라 의존성
    manifest가 정한다.

`sentences.provenance_json`에는 실제로 실행된 값을 기록한다.

``` text
provider            실행한 구현 이름 (openai | stub). prompt_versions 행의 값
model               실제 요청한 모델 문자열 (stub이면 "stub")
prompt_version      prompt_versions.version
generated_at        UTC
parent_sentence_id  GENERATE_REVIEW_CONTEXT의 near_original일 때만
```

`provider = "stub"`은 **test double이 만든 콘텐츠**를 뜻한다. `LLM_PROVIDER`가
가질 수 있는 값이 아니라 `prompt_versions` 행이 가질 수 있는 값이며, 테스트
fixture만 그 행을 만든다. 이 기록이 있어야 stub으로 만든 콘텐츠를 사후에 골라낼
수 있다.

## Structured Output 스키마 (MVP 확정)

`GENERATE_SENTENCE_BATCH`와 `GENERATE_REVIEW_CONTEXT`는 **같은 응답
스키마**를 쓴다. 두 task의 차이는 요청 context와 저장 시 lineage
(`parent_sentence_id`)이지 응답 모양이 아니다.

``` json
{
  "sentences": [
    {
      "japanese": "...",
      "korean_translation": "...",
      "difficulty_label": "beginner | intermediate | advanced",
      "items": [
        {
          "item_ref": "it0",
          "surface_form": "...",
          "is_tappable": true,
          "spans": [
            {"start_codepoint": 0, "end_codepoint": 3, "span_order": 0}
          ],
          "explanation": {
            "reading": "...",
            "core_meaning": "...",
            "meaning_in_context": "...",
            "nuance": "...",
            "example_sentence": "...",
            "example_translation": "..."
          }
        }
      ]
    }
  ]
}
```

-   모든 field는 스키마에서 **required**이고, `null`을 허용하는 것은
    `explanation`(item 단위)과 `explanation.example_translation`뿐이다.
    strict structured output은 optional field를 잘 다루지 못하므로
    "없음"은 field 생략이 아니라 `null`로 표현한다.
-   **모델이 id를 만들지 않는다.** 응답에 `sentence_id`,
    `learning_item_id`, `sentence_item_id` 같은 우리 쪽 식별자가 없다.
    item 지시는 요청에 실어 보낸 불투명 라벨 `item_ref`로만 한다.
-   `item_ref`는 **요청 로컬 라벨**이며 형식은 `it{n}`(n은 요청 안에서
    0부터 증가하는 순번)이다. worker는 요청을 만들 때
    `item_ref -> learning_item_id` 맵을 들고 있다가 응답을 되돌린다. DB
    id를 프롬프트에 싣지 않으므로 모델이 유효해 보이는 id를 지어낼 수
    없다.
-   응답의 `items`는 요청이 보낸 `item_ref` 집합의 **부분집합**이어야
    한다. 요청에 없는 ref가 오면 그 문장을 버린다(`unknown_item_ref`).
-   `register`, `topic`, `tags`, `provenance`, `model` 같은 field를
    스키마에 두지 않는다. register metadata는 MVP에서 **요청하지도
    저장하지도 않는다**(`00_SCOPE.md`, 위 register 조항). provenance는
    응답이 아니라 worker의 실행 context에서 채운다.
-   `difficulty_label`의 허용값은 `06_LEARNING_ENGINE.md`의 difficulty
    ladder와 같은 3단계다. 다른 값은 스키마 parsing 단계에서 걸린다.
-   `spans`는 `japanese`에 대한 **Unicode code point index**이며
    `[start_codepoint, end_codepoint)` 반열림 구간이다(`04_DB_SPEC.md`의
    `sentence_item_spans`). 불연속 표현은 span 여러 개로 표현하고
    `span_order`는 0부터 증가한다.

### 요청 context

전체 mastery 목록을 보내지 않는다(원칙 2). 한 요청에 싣는 것은 다음으로
제한한다.

``` text
learner_level      users.starting_level
target_items       [{item_ref, type, lemma, reading, default_meaning}]
                   개수 상한은 llm.sentences_per_batch
preferred_targets  문장당 선호 target 수 = learning.preferred_new_items_per_sentence
max_targets        문장당 상한         = learning.max_new_items_per_sentence
max_length         content.max_sentence_length_chars
avoid_japanese     target item이 이미 등장한 기존 문장의 japanese.
                   item당 최대 llm.avoid_examples_per_item개
```

`avoid_japanese`는 중복 생성을 줄이기 위한 힌트이고 실제 판정은 아래
deterministic duplicate 검사가 한다. 사용자 식별자, `login_id`, event
원문, mastery 수치를 프롬프트에 싣지 않는다.

**알려진 공백 --- 출력 토큰 상한:** provider 요청에 출력 토큰 상한을 싣는 조항이
없고, 현재 구현도 싣지 않는다. 출력이 폭주하면 호출 1회가 모델의 최대 출력 길이까지
간다. 반대로 상한을 너무 낮게 잡으면 structured output이 중간에 잘려 parsing 실패와
retry가 늘고 비용이 오히려 커진다. 상한을 둘지와 그 값은 결정하지 않았다.

## GENERATE_SENTENCE_BATCH 대상 선정 (MVP 확정)

**payload에 item 목록을 넣지 않는다.** replenishment job의
`idempotency_key`가 하루 단위 억제 창을 쓰고 enqueue가
`ON CONFLICT DO NOTHING`이므로, 그날 처음 만들어진 job의 payload가 그대로
고정된다. 그 사이에 학습이 진행되면 payload의 item 목록은 실행 시점에 이미
낡아 있다.

payload는 두 값만 가진다(key/payload 표의 canonical은
`09_BACKGROUND_JOBS.md`의 `Enqueue 트리거와 idempotency key`).

``` text
{"user_id": <id>, "presentation_role": "review | new | exploration"}
```

worker는 **실행 시점에** 대상 item을 다시 계산한다. 계산은
`06_LEARNING_ENGINE.md`의 role별 대상 item 조건·정렬을 그대로 쓰고 다음
조건을 추가로 건다.

``` text
그 item을 포함하면서 Ready invariant를 만족하는 문장이 0건이다
```

즉 **materialization이 문장을 찾지 못해 candidate를 만들지 못한 item만**
생성 대상이다. 문장이 이미 있는 item에 새 문장을 만들면 pool이 아니라
비용만 는다.

``` text
role = exploration  Exploration Item 선정의 후보 조건 + 정렬을 그대로 적용
role = new          role별 규칙의 new 대상 조건
role = review       role별 규칙의 review 대상 조건
```

정렬 순서대로 앞에서 최대 `llm.sentences_per_batch`개 item을 고르고 **item
하나당 문장 하나**를 요청한다. 대상이 0건이면 provider를 호출하지 않고
job을 `completed`로 끝낸다. 빈 결과는 실패가 아니다.

`role = review`의 대상은 "그 item에 쓸 문장이 아예 없는" 경우다. 문장은
있는데 **현재 `context_stage` 조건에 맞는 문장만 없는** 경우는
`GENERATE_REVIEW_CONTEXT`가 맡는다. 두 job의 경계가 이것이다.

## GENERATE_REVIEW_CONTEXT 입력

payload는 `{user_id, learning_item_id, context_stage, anchor_sentence_id}`
이고 응답 스키마는 위와 같으며 `sentences`는 1개다.

``` text
near_original  anchor 문장을 요청 context에 싣고 "표현은 유지, 주변 문맥만
               최소 변경"을 지시한다. 저장 시 parent_sentence_id = anchor
varied         anchor와 다른 상황을 지시한다. parent_sentence_id = NULL
new_context    varied와 같은 지시.        parent_sentence_id = NULL
```

`near_original`은 **의도된 near-duplicate**이므로 아래 duplicate 검사에서
similarity 항목(12번)을 적용하지 않는다. exact hash(11번)는 적용한다.

## EXPLAIN_ITEM 입력

payload는 `{sentence_item_id}`다. 응답은 위 스키마의 `explanation` 객체
하나이며 문장을 새로 만들지 않는다. worker는 그 `sentence_item`의
문장·`surface_form`·span을 요청 context에 싣고, 받은 explanation을
`status = validated`로 저장한다. 이미 `validated` explanation이 있으면
provider를 호출하지 않고 `completed`로 끝낸다(at-least-once 대비).

## worker가 만들지 않는 것 (MVP 확정)

-   **worker는 `learning_items` 행을 만들지 않는다.** 생성된 문장에서
    `sentence_items`를 만드는 대상은 요청에 실어 보낸 `item_ref` 집합뿐
    이다. 그래서 MVP에는 `origin = generated` learning_item을 만드는
    경로가 없다. 값은 컬럼 허용값으로 남지만 쓰이지 않는다
    (`04_DB_SPEC.md`의 `learning_items`). 문장 안의 그 밖의 표현은
    `sentence_items`가 되지 않으므로 tappable하지 않고 Ready invariant의
    대상도 아니다. 새 어휘를 사전화하는 일은 Future다
    (`spec/future/CONTENT_SYSTEM.md`).
-   **worker는 `user_sentence_candidates` 행을 만들지 않는다**
    (`09_BACKGROUND_JOBS.md`, `06_LEARNING_ENGINE.md`).
-   **worker는 `user_mastery` / `review_states` / `item_exposures` /
    `user_item_learning_state`를 건드리지 않는다.** 학습 상태는 request
    경로의 것이다.

## Deterministic Content Validation

Ready 처리 전 최소 검사 항목:

1.  Structured schema parsing 성공
2.  일본어 sentence non-empty
3.  configurable max sentence length 이하
4.  Korean translation 존재
5.  target LearningItem 수가 1 이상이고
    `learning.max_new_items_per_sentence` 이하 (기본값 2,
    `14_CONFIGURATION.md`. 아래 `target 수 상한의 출처와 검사 10의 지위`)
6.  target surface/spans가 실제 sentence와 일치
7.  span boundary 유효 (code point index 범위 내)
8.  ambiguous tappable overlap 없음
9.  `is_tappable = true`인 **모든** item에 contextual explanation 필수
    field 존재 (아래 `Ready invariant와 같은 범위`)
10. 신규 target item 수가 configured max 이하
    (`learning.max_new_items_per_sentence`. MVP에서는 구조적으로 발화하지
    않는다 --- 아래 `target 수 상한의 출처와 검사 10의 지위`)
11. exact duplicate hash가 duplicate corpus에 없음 (아래)
12. simple similarity가 `content.duplicate_similarity_threshold`를
    초과하지 않음
13. 응답의 모든 `item_ref`가 요청이 보낸 집합 안에 있음

단, `near_original` 목적으로 **의도적으로 생성된 review context는 일반
duplicate 제거와 별도로 취급한다.** 의도된 near-original 재노출을
중복으로 오인해 제거하지 않는다. 구체적으로 12번을 적용하지 않는다.

### target 수 상한의 출처와 검사 10의 지위 (MVP 확정)

검사 5의 상한은 리터럴이 아니라 `learning.max_new_items_per_sentence`이고
기본값이 2다. 학습 정책값을 검사에 박지 않는다 --- 이 키는
`13_ACCEPTANCE_CRITERIA.md`가 기본값으로 승인한 정책값이며, 값을 1로 낮추면
리터럴 "1\~2"는 `06_LEARNING_ENGINE.md`의 "문장당 target item 수는
`max_new_items_per_sentence` 이하"와 정면으로 충돌한다(06은 전체 target 1개를
요구하는데 08은 2개를 통과시킨다). 하한 1은 config가 아닌 고정값이다 ---
target이 없는 문장은 어떤 candidate도 만들지 못하므로 생성 비용만 쓴다.

검사 10의 상한도 MVP에서는 **같은 config 키 하나**에서 온다. 신규 target 수는
항상 전체 target 수 이하이므로, 두 상한이 한 값인 동안 검사 10이 발화할
조건(신규 수 > 상한)은 검사 5가 먼저 탈락시키는 조건(전체 수 > 상한)에 반드시
포함된다. 따라서 **검사 10은 MVP에서 구조적으로 발화하지 않는다.** 이 사실은
구현이 회귀 테스트로 고정해 두었다
(`test_check_ten_cannot_fire_while_both_limits_share_one_config_key`).

그래도 검사 10을 지우지 않는다.

-   **두 검사가 세는 대상이 다르다.** 5번은 그 문장의 target 전부를, 10번은
    그중 신규 item만 센다. 두 상한은 장래에 분리될 수 있다(예: 전체 3, 신규
    1). 두 검사를 하나로 합치면 그 구분이 명세에서 사라진다.
-   **상한이 분리되는 순간 유효해지는 backstop이다.** 구현도 그래서 두 상한을
    별도 인자로 들고 있다 --- `app/llm/validation.py`의 `SentencePolicy`가 그
    이유를 docstring에 적어 두었다. 하나로 합치면 분리 시점에 검사를 다시
    설계해야 한다.
-   **상한 분리는 MVP 범위가 아니다.** 분리하는 변경이 들어오면 그때 검사
    10의 handler 경로를 밟는 테스트를 추가해야 한다. 지금은 그 경로에 도달할
    입력이 없어서 handler가 검증되지 않은 상태로 남아 있다.

### Ready invariant와 같은 범위 (MVP 확정)

검사 9번의 대상은 **target item만이 아니라 그 문장의
`is_tappable = true`인 모든 item**이다. 가장 강한 해석을 쓴다.

Ready invariant의 canonical 정의는 `06_LEARNING_ENGINE.md`의
`Candidate Materialization`에 있고 그 판정도 같은 범위이며, seed loader도
같은 해석으로 적재한다. generation validation만 약한 해석(target only)을
쓰면 **생성 validation은 통과했는데 candidate는 될 수 없는 문장**이 조용히
쌓인다. 그 문장은 어느 지표에도 실패로 잡히지 않으므로 pool이 비는 이유가
보이지 않는다.

따라서 다음이 성립한다.

``` text
target item은 반드시 is_tappable = true 다
is_tappable = true 인 item은 반드시 explanation 6 field를 가진다
        (example_translation만 null 허용)
설명을 붙일 수 없는 표현은 is_tappable = false 로 두거나
        애초에 item으로 만들지 않는다
```

### normalized_hash (MVP 확정)

`sentences.normalized_hash`의 계산 규칙은 다음이 canonical이다.

``` text
normalized = NFKC(japanese) 에서 모든 Unicode whitespace 제거
hash       = sha256(normalized.encode("utf-8")) 의 소문자 hex 64자
```

이미 seed loader가 이 규칙으로 seed 문장의 해시를 채웠다. **규칙을 바꾸면
기존 seed 행의 해시가 새 값과 비교 불가능해져 duplicate 검사가 seed를 못
본다.** 그래서 현행 규칙을 그대로 승계하고, seed loader와 worker가 **같은
함수 하나**를 쓴다. 대소문자·구두점·표기 흔들림을 더 접는 정규화는
Future다.

### duplicate 비교 corpus (MVP 확정)

검사 11·12번의 "최근/Ready pool"은 다음을 뜻한다.

``` text
비교 대상 = sentences 전체 중 status != 'retired'
            (draft / validated / quarantined 를 모두 포함한다)
사용자별로 자르지 않는다 --- sentences는 global content다
```

-   **`quarantined`를 반드시 포함한다.** 빼면 사용자가 flag해서 격리한
    문장을 다음 generation이 그대로 다시 만들고, 새 id를 받은 그 문장이
    `validated`가 되어 다시 Ready로 선택된다.
    `13_ACCEPTANCE_CRITERIA.md`의 "flag된 content가 다시 Ready로 선택되지
    않음"이 그 경로로 깨진다.
-   `retired`만 제외하는 이유는 MVP에 그 상태로 보내는 경로가 없고,
    은퇴시킨 문장과 같은 내용을 다시 만드는 것을 막을 이유가 없기
    때문이다.
-   11번은 `normalized_hash` 동등 비교다.
-   12번의 "simple similarity"는 위 `normalized` 문자열끼리의 문자 기반
    유사도이며 MVP는 표준 라이브러리
    (`difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()`)로
    계산한다. `autojunk=False`로 고정하는 이유는 기본값이 긴 입력에서 자주
    나오는 문자를 junk로 빼기 시작해 길이에 따라 판정 기준이 달라지기
    때문이다. embedding semantic similarity는 MVP 의무가 아니다
    (`spec/06_LLM_ENGINEERING_PRINCIPLES.md`의 `MVP 구현 의무 범위`).
-   **한계:** 12번은 corpus 전체를 훑는 O(N) 비교다. 개인 사용 규모에서는
    충분하고, corpus가 커져 문제가 되면 그때 후보를 좁힌다. 지금 좁히는
    규칙을 만들면 근거 없는 숫자가 하나 더 생긴다.

### 탈락한 콘텐츠의 처리 (MVP 확정)

**validation을 통과하지 못한 문장은 어떤 행으로도 저장하지 않는다.**
`sentences.status = draft`로 남기지 않는다.

-   validation은 DB 쓰기 **이전에** 끝난다. 통과한 문장만
    `status = validated`로 INSERT한다. 그래서 MVP에는 `draft` 상태의
    `sentences` 행을 만드는 경로가 없다(`04_DB_SPEC.md`).
-   `draft`로 남기면 아무도 읽지 않는 행이 쌓이는데, 그것을 정리하는
    maintenance job은 MVP job_type에 없고 사람이 볼 수단(admin UI)도
    Future다.
-   대신 **사유 코드**를 `generation_jobs.result_ref.rejected`와 로그에
    남긴다. 배치의 일부 문장만 탈락하면 통과한 문장은 저장하고 탈락 건수와
    사유를 함께 기록한다. 전부 탈락하면 그 job은 재시도 대상이다
    (`09_BACKGROUND_JOBS.md`).

사유 코드 집합(이 목록이 canonical이며 `11_OBSERVABILITY.md`의 validation
failure 집계 단위다). 오른쪽은 위 검사 번호다.

``` text
schema_parse_failed         1
empty_japanese              2
sentence_too_long           3
missing_translation         4
target_count_out_of_range   5
surface_not_found           6
span_out_of_range           7
span_overlap                8
missing_explanation         9
too_many_targets           10
duplicate_hash             11
duplicate_similarity       12
unknown_item_ref           13
```

### difficulty_json (MVP 확정)

`sentences.difficulty_json`은 응답의 label을 그대로 담는다.

``` text
{"label": "beginner | intermediate | advanced"}
```

허용값은 스키마 enum이 강제하므로 별도 검증을 하지 않고, 그 label이 실제
난이도와 맞는지도 **검증하지 않는다.** MVP에 판정 근거가 없고
`06_LEARNING_ENGINE.md`가 이 값을 문장 선택에 쓰지 않는다
(`difficulty_distance`는 `learning_items.difficulty_label`로 계산한다).
multidimensional difficulty는 Future다.

### Sense correctness limitation

deterministic validation만으로

> target expression이 정확히 의도한 sense로 자연스럽게 사용되었는가

를 **완전히 보장할 수 없다.** MVP는 structured output의
`meaning_in_context`와 span consistency를 확인하는 수준까지만 검증하고,
나머지는 사용자 content flag와 실제 사용 feedback으로 보완한다.

Mandatory second-model judge는 MVP 범위 밖이다.
