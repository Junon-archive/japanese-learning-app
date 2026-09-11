# SRS Specification

## Scheduling

복습 시점(`WHEN`)은 검증된 FSRS 계열 알고리즘을 사용한다. 자체 간격
알고리즘을 새로 발명하지 않는다.

## Content Selection

복습 콘텐츠(`WHAT`)는 Learning Engine이 결정한다.

## Meaningful Exposure

각 LearningItem은 최소 5회 meaningful exposure를 갖는다. 단순히 화면에
스쳐 지나간 것을 모두 exposure로 세지 않는다.

의미 있는 노출의 예: - target으로 포함된 문장을 실제로 본 경우 - mastery
probe에서 확인한 경우 - review interaction을 수행한 경우 - listening
target으로 들은 경우

구체적인 count 규칙은 테스트 가능하게 정의한다.

## Context Progression

초기에는 기억 anchor를 위해 원문/near-original을 유지하고, 이후
transfer를 위해 새로운 문맥으로 이동한다.

예: 1. `この仕事、田中さんに任せてもいい？` 2. 같은 원문 또는 최소 변형
3. `あとは彼に任せるよ。` 4. 다른 일상 상황 5. 가능하면 listening
context

`2회 성공하면 종료` 같은 규칙은 사용하지 않는다.

## Failure / Uncertainty

`몰랐음`, probe 오답, review 실패는 FSRS와 mastery update에 강한 부정
evidence로 사용한다. `애매함`은 중간 evidence로 처리한다.

## Separation of Concerns

FSRS state와 mastery score는 동일한 값이 아니다. Scheduling state와
사용자 능력 추정치를 별도로 저장한다.
