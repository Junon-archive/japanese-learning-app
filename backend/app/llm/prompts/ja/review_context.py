"""`GENERATE_REVIEW_CONTEXT`의 정적 지시문. prompt version `review_context_v1`.

응답 스키마는 `GENERATE_SENTENCE_BATCH`와 **같고** `sentences`는 1개다. 다른 것은
요청 context와 저장 시 lineage(`parent_sentence_id`)뿐이다(`08_LLM_SPEC.md`).

`context_stage`별 지시 차이는 요청 context가 나른다. 여기 정적 지시문에는
"near_original이면 중복 검사를 건너뛴다" 같은 문장이 없다 --- 그 판단은 요청
쪽에서 계산하는 것이지 모델이 자기 응답에 표시할 수 있는 것이 아니다.
"""

from __future__ import annotations

VERSION = "review_context_v1"

INSTRUCTIONS = """\
You write one new Japanese sentence that re-exposes a single target item that a
Korean-speaking learner has already met, in the context stage the request asks
for.

context_stage meanings:

- near_original: keep the target expression and its immediate wording as in the
  anchor sentence, and change only the surrounding context minimally.
- varied: use the same target expression in a clearly different situation from
  the anchor sentence.
- new_context: same as varied.

Hard rules. A sentence that breaks any of them is discarded by the server.

1. Return exactly one sentence, and use only the item_ref given in the request.
2. The sentence must be at most max_sentence_length_chars Unicode code points.
3. spans are Unicode code point offsets into the `japanese` string of the same
   sentence, as a half-open range [start_codepoint, end_codepoint). They are
   NOT UTF-16 code units and NOT byte offsets.
   `japanese[start_codepoint:end_codepoint]` must equal `surface_form` exactly.
   A discontinuous expression uses several spans whose concatenation equals
   `surface_form`; `span_order` runs from 0 upward.
4. Spans of different items in the same sentence must never overlap.
5. Every item with `is_tappable` true must carry a full `explanation`. If you
   cannot explain an expression, set `is_tappable` false or omit the item.
   `example_translation` may be null; no other field may be null or empty.
6. `korean_translation` is Korean prose. Do not put Japanese text there.
7. Never return the anchor sentence itself, and never reproduce any sentence
   listed under `avoid_japanese`.

Return only the structured object required by the schema.
"""
