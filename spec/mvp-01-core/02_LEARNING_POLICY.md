# Learning Policy

## Mastery

MVP는 두 축을 저장한다.

-   comprehension: 문장을 읽고 표현의 의미/용법을 이해하는 정도
-   listening: 소리로 들었을 때 표현을 인식하고 이해하는 정도

클릭하지 않은 item은 자동으로 Known 처리하지 않는다.

## Mastery Signals

강한 신호: - explicit `몰랐음` - explicit `애매함` - explicit
`알고 있었음` - mastery probe 정답/오답 - 실제 review 결과

보조 신호: - item click - explanation reveal - translation reveal -
audio replay

단순 page view 또는 no-click은 약하거나 중립적인 신호로 취급한다.

## Active Mastery Probe

사용자는 자신이 모르는 사실을 모를 수 있으므로 앱이 일부 item을 먼저
확인한다.

초기 정책: - 한 12분 세션에서 약 2\~4회 이하를 목표로 한다. - 정확한
빈도는 configuration으로 둔다. -
`뜻을 안다 / 애매함 / 잘 모르겠다 / 건너뛰기` 또는 간단한 객관식 형태를
지원할 수 있다. - 모든 문장에 probe를 넣지 않는다.

## Sentence Novelty

-   신규 LearningItem: 문장당 **권장 1개**
-   필요한 경우 최대 **2개**
-   초급 단계에서 자연스러운 문장 생성을 위해 2개를 허용한다.

## Session Mix

초기 목표: - Review 70% - New 20% - Exploration 10%

Exploration은 mastery DB에 충분한 정보가 없지만 예상 수준에 맞는 표현을
의도적으로 탐색하는 콘텐츠다.

Review backlog가 증가하면 new 비율을 낮추고 review 비율을 높일 수 있다.

## Exposure

-   LearningItem은 최소 5회의 meaningful exposure를 보장한다.
-   `알고 있음` 응답 1\~2회만으로 학습 완료 처리하지 않는다.
-   5회는 종료 조건이 아니라 최소 보장값이다.
-   이후에도 FSRS가 due로 판단하면 재노출한다.

초기 문맥 전략: 1. 첫 노출: original context 2. 초기 재노출: original
또는 near-original 3. 중기: 약간 다른 문맥 4. 이후: 새로운 일상 문맥 5.
가능하면 listening exposure 포함

정확한 전환 시점은 실사용 데이터로 조정할 수 있도록 configuration으로
둔다.

## Topic Balance

개인 관심사를 사용하되 과적합하지 않는다. 장기적으로 daily life,
conversation, work/research, hobbies, travel, random/general 등의 topic
budget을 유지한다.
