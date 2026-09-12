"""`EXPLAIN_ITEM`의 정적 지시문. prompt version `explain_item_v1`.

missing explanation repair job 전용이다. 문장을 새로 만들지 않고 이미 저장된
`sentence_item` 하나의 contextual explanation만 만든다(`08_LLM_SPEC.md`).
"""

from __future__ import annotations

VERSION = "explain_item_v1"

INSTRUCTIONS = """\
You explain one expression as it is used in one Japanese sentence, for a
Korean-speaking learner.

The sentence and the expression already exist; do not rewrite either one and do
not return a new sentence.

Hard rules. A response that breaks any of them is discarded by the server.

1. `reading` is the reading of the expression as it appears in this sentence.
2. `core_meaning` is the general meaning of the expression, in Korean.
3. `meaning_in_context` is the sense the expression actually carries in this
   sentence, in Korean. It is not a dictionary gloss.
4. `nuance` is in Korean.
5. `example_sentence` is a different Japanese sentence using the expression.
   `example_translation` is its Korean translation, or null.
6. No field other than `example_translation` may be null or empty.

Return only the structured object required by the schema.
"""
