# Acceptance Criteria

MVP-01은 아래 조건을 만족해야 Verified로 본다.

## Core UX

-   모바일에서 앱을 열고 학습 세션을 시작할 수 있다.
-   Sentence가 표시되고 LearningItem을 눌러 설명을 즉시 볼 수 있다.
-   reading과 핵심 의미가 표시된다.
-   한국어 번역은 reveal 전까지 숨겨져 있다.
-   self-report는 선택 사항이며 다음 문장 진행을 막지 않는다.
-   mastery probe를 건너뛸 수 있다.

## Learning

-   no-click만으로 Known 처리되지 않는다.
-   comprehension/listening 두 mastery 필드가 존재한다.
-   FSRS scheduling이 동작한다.
-   meaningful exposure가 별도 집계된다.
-   최소 5회 노출 정책을 지원한다.
-   신규 item은 기본 1개, 최대 2개 정책을 지원한다.
-   70/20/10 비율을 configuration으로 변경할 수 있다.

## LLM

-   사용자 item click이 매번 live LLM 호출을 요구하지 않는다.
-   sentence batch generation이 background에서 가능하다.
-   structured result가 코드 validation을 통과한 경우만 Ready Pool에
    들어간다.
-   Public Demo에서 paid LLM call이 발생하지 않는다.

## Data / Security

-   PostgreSQL이 canonical state이다.
-   DB schema는 migration으로 재현 가능하다.
-   PostgreSQL이 인터넷에 직접 노출되지 않는다.
-   secret이 frontend bundle/Git에 포함되지 않는다.
-   anonymous user가 private learning data에 접근할 수 없다.

## Reliability

-   backend/worker restart 후 DB state가 유지된다.
-   failed generation job이 무한 retry하지 않는다.
-   backup과 restore 절차가 문서화되고 최소 한 번 검증된다.

## Validation Period

기술 acceptance 이후 실제 사용자가 2\~4주 사용하며 다음을 관찰한다. -
매일/자주 열게 되는가 - 설명 확인이 귀찮지 않은가 - 문장이 자연스럽고
흥미로운가 - contextual SRS가 기억에 도움이 되는가 - 12분 세션이 실제
일정에 맞는가

이 사용 결과는 MVP-02 또는 정책 수정의 근거가 된다.
