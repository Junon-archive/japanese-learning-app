# LLM Specification

MVP tasks: - `GENERATE_SENTENCE_BATCH` - `EXPLAIN_ITEM` (background
repair job 전용) - `GENERATE_REVIEW_CONTEXT`

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

## Deterministic Content Validation

Ready 처리 전 최소 검사 항목:

1.  Structured schema parsing 성공
2.  일본어 sentence non-empty
3.  configurable max sentence length 이하
4.  Korean translation 존재
5.  target LearningItem 수 1\~2
6.  target surface/spans가 실제 sentence와 일치
7.  span boundary 유효 (code point index 범위 내)
8.  ambiguous tappable overlap 없음
9.  contextual explanation 필수 field 존재
10. 신규 target item 수가 configured max 이하
11. exact duplicate hash가 최근/Ready pool에 없음
12. simple similarity가 threshold를 초과하지 않음

단, `near_original` 목적으로 **의도적으로 생성된 review context는 일반
duplicate 제거와 별도로 취급한다.** 의도된 near-original 재노출을
중복으로 오인해 제거하지 않는다.

### Sense correctness limitation

deterministic validation만으로

> target expression이 정확히 의도한 sense로 자연스럽게 사용되었는가

를 **완전히 보장할 수 없다.** MVP는 structured output의
`meaning_in_context`와 span consistency를 확인하는 수준까지만 검증하고,
나머지는 사용자 content flag와 실제 사용 feedback으로 보완한다.

Mandatory second-model judge는 MVP 범위 밖이다.
