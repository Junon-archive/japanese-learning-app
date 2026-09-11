# Test Plan

## Unit Tests

-   Learning policy ratio/config
-   no-click does not become Known
-   mastery signal mapping
-   meaningful exposure count
-   FSRS wrapper
-   content validation
-   duplicate detection
-   auth permission checks

## Integration Tests

-   FastAPI ↔ PostgreSQL
-   session creation ↔ sentence selection
-   event write ↔ mastery/review update
-   generation job ↔ worker ↔ sentence pool
-   Alembic migration from empty DB
-   Demo mode cannot access private data or paid generation

## Core E2E Scenario

1.  신규 사용자/테스트 사용자 생성
2.  `任せる`가 포함된 문장 노출
3.  item 클릭
4.  설명 표시
5.  `몰랐음` 선택
6.  event 저장
7.  mastery/review state 생성
8.  due 시점으로 테스트 clock 이동
9.  review 문장 노출
10. exposure가 누적
11. 초기 원문 후 새로운 문맥으로 재노출
12. 최소 5회 노출 이후에도 FSRS due라면 계속 복습 가능

## Demo E2E

-   anonymous visitor가 demo를 시작할 수 있다.
-   설명/번역/probe를 체험할 수 있다.
-   private user data가 노출되지 않는다.
-   LLM paid call이 발생하지 않는다.

## Regression

prompt/model 변경 시 소규모 golden dataset으로 schema, target inclusion,
난이도/자연스러움 표본을 재검토한다. MVP에서는 별도 LLM judge를 필수로
사용하지 않는다.
