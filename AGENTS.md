# Implementation Instructions

이 프로젝트를 구현하는 에이전트/CC는 `spec/`을 source of truth로
사용한다.

## 필수 작업 순서

1.  구현 대상 milestone의 관련 명세를 모두 읽는다.
2.  구현 전에 변경 파일, DB migration, API, 테스트를 포함한
    implementation plan을 작성한다.
3.  `In Scope`만 구현한다. Future/Out of Scope 기능을 선제 구현하지
    않는다.
4.  DB schema 변경은 SQLAlchemy model과 Alembic migration으로 관리한다.
5.  사용자 학습 상태의 canonical source는 PostgreSQL이다. LLM
    conversation state를 사용자 상태 저장소로 사용하지 않는다.
6.  LLM은 콘텐츠 생성·설명 역할만 한다. 학습 대상·복습 시점·세션 구성은
    Learning Engine이 결정한다.
7.  테스트 없는 핵심 기능을 완료로 처리하지 않는다.
8.  lint/typecheck/unit/integration/E2E acceptance test를 실행하고
    결과를 보고한다.
9.  명세와 구현이 충돌하면 임의로 기능 범위를 넓히지 않는다.
10. 비밀키, 실제 DB 데이터, 백업 파일은 Git에 commit하지 않는다.

## MVP 원칙

-   단순하게 구현하되 일회용 코드는 만들지 않는다.
-   미래 확장을 위한 인터페이스는 허용하지만 미래 기능 구현은 금지한다.
-   불확실한 학습 정책값은 하드코딩하지 않고 configuration으로 둔다.
-   Public Demo에서는 실시간 유료 LLM 호출을 하지 않는다.
