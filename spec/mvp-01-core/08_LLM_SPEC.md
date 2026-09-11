# LLM Specification

MVP tasks: - `GENERATE_SENTENCE_BATCH` - `ANALYZE_SENTENCE` (이미 생성
결과에 분석이 있으면 중복 호출 금지) - `EXPLAIN_ITEM` -
`GENERATE_REVIEW_CONTEXT`

가능하면 generation에서 translation/item
annotation/reading/meaning/register/provenance까지 한 번에 생성.
Structured output 사용. Prompt version 기록. Batch/Ready Pool/재사용
우선. Public Demo generation 금지. 모델명은 business logic에 고정하지
않는다.
