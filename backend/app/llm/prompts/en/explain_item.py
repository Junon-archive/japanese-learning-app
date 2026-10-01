"""`EXPLAIN_ITEM`의 정적 지시문 (영어). prompt version `explain_item_en_v1`.

missing explanation repair job 전용이다. 문장을 새로 만들지 않고 이미 저장된
`sentence_item` 하나의 contextual explanation만 만든다(`08_LLM_SPEC.md`).
"""

from __future__ import annotations

VERSION = "explain_item_en_v1"

INSTRUCTIONS = """\
You explain one expression as it is used in one English sentence, for a
Korean-speaking learner who reads English fine but struggles with real-time
conversation and with following native speakers in shows and podcasts.

The sentence and the expression already exist; do not rewrite either one and
do not return a new sentence.

Hard rules. A response that breaks any of them is discarded by the server.

1. `reading` is always null for English. Never write a pronunciation or IPA
   string there.
2. `core_meaning` is the general meaning of the expression, in Korean.
3. `meaning_in_context` is the sense the expression actually carries in this
   sentence, in Korean. It is not a dictionary gloss.
4. `nuance` is in Korean and must state the register (casual, neutral, or
   formal) and who would plausibly say this to whom. That is the information
   this learner actually lacks, not the dictionary meaning of the words.
5. `example_sentence` is a different spoken-style English sentence using the
   expression -- not literary, academic, or test-prep English.
   `example_translation` is its Korean translation, or null.
6. No field other than `example_translation` and `reading` may be null or
   empty.

Return only the structured object required by the schema.
"""
