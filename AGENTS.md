# CC / Agent Implementation Instructions

1.  구현 전 관련 `spec/` 전체를 읽고 implementation plan을 먼저
    작성한다.
2.  MVP In Scope만 구현한다. Future 기능을 선제 구현하지 않는다.
3.  DB 변경은 SQLAlchemy model + Alembic migration으로 관리한다.
4.  PostgreSQL이 사용자 상태의 canonical source다.
5.  Learning Engine이 무엇을/언제 학습할지 결정하고 LLM은 언어
    생성·설명을 담당한다.
6.  핵심 기능은 테스트 없이 완료 처리하지 않는다.
7.  secret, `.env`, DB volume, backup은 Git에 넣지 않는다.
8.  Public Demo는 유료 LLM 호출과 private data 접근을 금지한다.
9.  불확실한 학습 정책값은 configuration으로 둔다.
10. 명세 충돌을 발견하면 기능을 임의 확장하지 않는다.

`05_LEARNING_SYSTEM_VISION`, `06_LLM_ENGINEERING_PRINCIPLES`,
`future/*`는 미래 의도를 보존하지만 MVP 구현 범위를 넓히지 않는다.

`updates/`는 변경 요청이지 명세가 아니다. 요청은 spec-sync가 `spec/`에
반영한 뒤에만 구현한다.

**Global/Future 문서에 숫자나 아이디어가 존재한다는 이유만으로 구현하지
않는다.** MVP 구현 source of truth는 `spec/mvp-01-core/*`다.

특히 다음은 MVP 구현 대상이 아니다: audio/TTS, `ANALYZE_SENTENCE`,
comprehensible-input 난이도 밴드, source mix 비율, Busy/Deadline 모드,
register/sense/multidimensional difficulty, 형태소 분석기, embedding
duplicate detector, golden eval harness, admin UI, export.
