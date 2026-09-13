# Future --- Content System

Sources: real source / source transformation / fully generated / manual.

개인화 prompt는 known vocab/grammar, interests, register, difficulty를
사용하되 관심사 과적합을 막는다. 장기적으로
situation→dialogue→expressions 콘텐츠를 지원한다.

문법적으로 맞지만 부자연스러운 일본어도 quality failure다. 사용자
feedback: unnatural, wrong explanation, too easy, too hard, not
interested.

Real/source-transformed/generated의 60/30/10은 실험 가이드이지 확정값이
아니다.

## ANALYZE_SENTENCE

기존 문장을 구조화하는 `ANALYZE_SENTENCE` LLM task는 Future다.

MVP 콘텐츠는 전부 `GENERATE_SENTENCE_BATCH` 결과이므로 MVP에는 호출자가
없다(`spec/mvp-01-core/08_LLM_SPEC.md`). real source / manual text /
YouTube transcript 같은 외부 문장을 받아들이는 시점에 필요해진다.

이미 generation output에 충분한 분석이 있으면 중복 호출하지 않는다는
원칙은 그대로 유지한다.

## Future Content Metadata

register metadata, active-use/recognize-only 구분, multidimensional
difficulty scorer, 정교한 topic budget, sense hierarchy,
morphological analyzer, embedding 기반 duplicate detector는 모두
Future다. MVP는 simple difficulty label과 simple topic tag까지만
사용한다(`spec/mvp-01-core/00_SCOPE.md`).

(주석, MVP-02) 형태소 분석기는 MVP-02에서 **콘텐츠 적재·생성 시점의 후리가나 계산 용도로만** 도입했다
(ADR-021, `spec/mvp-02-onboarding/00_SCOPE.md`). 나머지 용도(metadata 채우기, lemma·난이도 판정 등)는 여전히
Future다.
