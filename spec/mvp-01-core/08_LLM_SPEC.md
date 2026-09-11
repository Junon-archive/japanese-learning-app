# LLM Specification

## Principle

LLM은 language intelligence layer이다. 사용자 상태와 학습 정책의 source
of truth가 아니다.

## MVP Tasks

### GENERATE_SENTENCE_BATCH

여러 문장을 한 요청에서 생성한다.

Input concept: - target/review items - user level summary - desired
topic distribution - new-item constraints - recent duplicate/avoid
context - register preference: natural spoken Japanese

Output concept: - sentence - Korean translation - item annotations -
reading/meaning metadata where appropriate - provenance

가능하면 생성과 기본 분석을 한 번에 반환하여 추가 API 호출을 줄인다.

### ANALYZE_SENTENCE

기존 문장을 구조화해야 할 때 사용한다. 이미 generation output에 충분한
분석이 있으면 중복 호출하지 않는다.

### EXPLAIN_ITEM

DB에 설명이 없거나 새 sense/context 설명이 필요할 때 생성한다. 일반적인
매 클릭마다 호출하지 않는다.

### GENERATE_REVIEW_CONTEXT

due item을 새로운 자연스러운 문맥에서 재노출하기 위한 콘텐츠를 batch
생성한다.

## Structured Output

가능한 경우 schema-constrained structured output을 사용한다. 서버는
결과를 다시 parse/validate한다.

## Prompt Versioning

예: - `sentence_gen_v1` - `explain_item_v1` - `review_context_v1`

생성 콘텐츠에 model/provider/prompt_version/generated_at을 기록한다.

## Cost Policy

-   user interaction path에서 불필요한 live call 금지
-   batch generation 우선
-   설명/문장 재사용
-   Ready Sentence Pool 유지
-   일일 request/token budget 설정 가능
-   Public Demo는 paid call 금지

## Model Routing

구체적인 model name은 명세에 영구 고정하지 않는다. 비용·품질·지연
benchmark를 통해 task별 provider/model을 교체할 수 있도록 abstraction을
둔다.
