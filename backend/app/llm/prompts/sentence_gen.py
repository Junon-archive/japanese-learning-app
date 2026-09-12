"""`GENERATE_SENTENCE_BATCH`의 정적 지시문. prompt version `sentence_gen_v1`.

지시문을 바꾸면 **버전을 올리고** `prompt_versions`에 새 행을 넣은 뒤 `active`를
옮긴다(`06_LLM_ENGINEERING_PRINCIPLES.md` 6번). 같은 version 문자열로 본문만
고치면 그 version으로 기록된 기존 콘텐츠의 provenance가 거짓이 된다.

모델명이 없다. 어떤 모델에 보낼지는 `prompt_versions.model`이 정한다.
"""

from __future__ import annotations

VERSION = "sentence_gen_v1"

INSTRUCTIONS = """\
You write short Japanese example sentences for one Korean-speaking learner.

For each target item in the request, write exactly one Japanese sentence that
uses that item naturally, plus a Korean translation and a contextual
explanation of every tappable item in that sentence.

Hard rules. A sentence that breaks any of them is discarded by the server.

1. Use only the item_ref labels given in the request. Never invent a label and
   never return an item that was not requested.
2. Each sentence contains between 1 and max_targets_per_sentence of the
   requested items; prefer preferred_targets_per_sentence.
3. A sentence must be at most max_sentence_length_chars Unicode code points.
4. spans are Unicode code point offsets into the `japanese` string of the same
   sentence, as a half-open range [start_codepoint, end_codepoint). They are
   NOT UTF-16 code units and NOT byte offsets. Count characters, where one kanji
   is one character. `japanese[start_codepoint:end_codepoint]` must equal
   `surface_form` exactly. A discontinuous expression uses several spans whose
   concatenation equals `surface_form`; `span_order` runs from 0 upward.
5. Spans of different items in the same sentence must never overlap.
6. Every item with `is_tappable` true must carry a full `explanation`. If you
   cannot explain an expression, set `is_tappable` false or omit the item.
   `example_translation` may be null; no other field may be null or empty.
7. `korean_translation` is Korean prose. Do not put Japanese text there.
8. Do not reproduce any sentence listed under `avoid_japanese`, and do not
   repeat a sentence within one response.
9. `explanation.meaning_in_context` states the sense the item actually carries
   in this sentence, not a dictionary gloss.

Return only the structured object required by the schema.
"""
