# Learning Engine

Learning Engine은 사용자에게 **무엇을 보여줄지** 결정한다. LLM은
결정자가 아니다.

## Inputs

-   due FSRS reviews
-   meaningful exposure count
-   comprehension/listening mastery
-   recent learning events
-   current session mix
-   recent topics
-   ready sentence pool
-   review backlog

## Outputs

다음 Sentence 선택에 필요한: - target LearningItem(s) - role:
review/new/exploration - desired difficulty - desired topic - whether a
mastery probe is useful - content requirement if pool replenishment is
needed

## Initial Policy

-   review/new/exploration = 70/20/10
-   preferred new item count = 1
-   max new item count = 2
-   default session = 12 minutes
-   active mastery probe ≈ 2\~4 per session maximum target
-   minimum meaningful exposure = 5

이 값은 configuration으로 관리한다.

## Backlog Control

Review backlog가 많으면 신규 item 공급을 줄인다. 사용자가 바쁜 날에도
`overdue 93` 같은 부채감 UX를 만들지 않는다.

## No-click Rule

Sentence를 넘겼다는 이유만으로 모든 포함 item의 mastery를 올리지 않는다.
명시적 evidence가 없는 경우 보수적으로 유지한다.

## Exploration

Mastery 정보가 부족한 item을 가끔 노출하거나 probe하여 사용자 수준을
추정한다. Exploration은 무작위 희귀어 공급이 아니다.

## Pool-first

사용자가 다음 문장을 요청할 때 LLM 생성을 기다리지 않도록 Ready Sentence
Pool에서 선택한다. Pool이 부족하면 background job을 생성한다.
