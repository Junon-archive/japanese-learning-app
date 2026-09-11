# Learning Policy

## Mastery

MVP는 두 축을 저장한다.

-   comprehension: 문장을 읽고 표현의 의미/용법을 이해하는 정도
-   listening: 소리로 들었을 때 표현을 인식하고 이해하는 정도

저장 형식:

``` text
comprehension_mastery: nullable float [0.0, 1.0]
listening_mastery:     nullable float [0.0, 1.0]
```

의미:

``` text
NULL = 아직 충분한 evidence 없음
0.0  = 매우 낮은 mastery
1.0  = 매우 높은 mastery
```

boolean Known/Unknown으로 구현하지 않는다.

MVP-01에는 audio가 없으므로 `listening_mastery`는 **초기값 NULL이며
MVP에서 갱신하지 않는다.** NULL은 listening 능력이 0이라는 뜻이 아니라
아직 측정하지 않았다는 뜻이다(`spec/future/LISTENING.md`).

## Signals

강한 신호: explicit known/uncertain/unknown, probe 정오답, review
result.\
보조 신호: click, explanation reveal, translation reveal.\
no-click/page view는 중립 또는 매우 약한 신호.

### Mastery를 실제로 변경하는 explicit evidence

MVP에서 mastery 값을 직접 갱신하는 것은 다음 explicit evidence뿐이다.

``` text
몰랐음 / probe incorrect    -> observation 0.0
애매함 / probe uncertain    -> observation 0.4
알고 있었음 / probe correct -> observation 0.8
```

MVP UI에는 사용자가 직접 누르는 `Easy` 버튼이 없다.

갱신은 configurable EMA로 정의한다.

``` text
new_mastery = old_mastery * (1 - alpha) + observation * alpha
```

`old_mastery`가 NULL이면:

``` text
new_mastery = observation
```

`alpha`는 `mastery_ema_alpha` config 값이다(`14_CONFIGURATION.md`).

### Auxiliary signal

다음은 raw LearningEvent로 보존하지만 **MVP에서 mastery 값을 직접
변경하지 않는다.**

``` text
item_clicked
explanation_revealed
translation_revealed
sentence_viewed
passive exposure
```

이로써 `clicked = unknown`과 `not clicked = known` 둘 다 성립하지 않게
한다.

`evidence_count`는 **mastery update에 실제 사용된 explicit evidence
개수**이며 meaningful exposure count와 혼동하지 않는다.

### No-signal review

사용자가 review sentence를 보고 item을 누르지도, self-report도, probe도
하지 않고 다음 문장으로 이동했다면 **FSRS rating을 추론하지 않는다.**

``` text
no-click != Good
no-click != Easy
```

이 경우의 처리는 `07_SRS_SPEC.md`의 passive exposure + temporary
deferral 규칙을 따른다.

## Active Probe

사용자가 unknown-unknown을 가질 수 있으므로 앱이 먼저 확인한다. 12분
세션당 초기 목표 약 2\~4회 이하, configurable.

### Probe UI (MVP 확정)

MVP probe UI는 **하나로 고정한다.** 객관식 의미 문제는 구현하지 않는다.

문구:

``` text
이 표현을 알고 계세요?
```

선택지:

``` text
알고 있었음 / 애매함 / 몰랐음 / 건너뛰기
```

### Probe 대상 우선순위

1.  mastery = NULL
2.  passive exposure가 반복됐지만 explicit evidence가 없는 item
3.  서로 충돌하는 evidence가 있는 item
4.  오래 probe하지 않은 uncertain item

다음은 probe하지 않는다.

-   방금 explicit feedback을 받은 item
-   probe cooldown 중인 item

### Skip

``` text
skip = mastery evidence 아님
skip = FSRS grade 아님
```

skip 후 같은 item을 즉시 다시 묻지 않는다. 연속 skip 사용자는 해당
세션의 probe budget을 줄일 수 있다.

관련 config: `probe_skip_cooldown_days`,
`passive_exposures_before_probe`.

## Incidental Item Click

사용자가 target이 아닌 tappable expression을 눌렀을 때:

-   click 자체는 raw event로만 남긴다.
-   **바로 SRS에 등록하지 않는다.**

이후 사용자가 `몰랐음` 또는 `애매함`을 선택하면 해당 LearningItem을 개인
학습 상태에 활성화하고 신규 learning target으로 등록한다
(`user_item_learning_state.is_active_learning_target`).

`알고 있었음`이면 SRS 신규 item으로 강제 등록하지 않는다.

클릭 후 아무 self-report 없이 넘어가면 candidate evidence로만 남기고
추후 probe 대상이 될 수 있다.

## Novelty

신규 item 권장 1, 최대 2. 초급 단계에서 자연스러운 문장 생성을 위해 2개를
허용한다.

## Mix

Review 70 / New 20 / Exploration 10. backlog가 많으면 review↑ new↓.

비율의 단위와 선택 알고리즘은 `06_LEARNING_ENGINE.md`에 정의한다. 초기
수치는 `14_CONFIGURATION.md`에만 둔다.

## Exposure

최소 meaningful exposure 5회. 5회는 졸업 조건이 아님. 초기
원문/near-original → 약간 다른 문맥 → 새로운 일상 문맥.

meaningful exposure의 판정 규칙과 canonical source는
`07_SRS_SPEC.md`와 `04_DB_SPEC.md`의 `item_exposures`를 따른다.

MVP에는 audio가 없으므로 listening exposure는 Future다
(`spec/future/LISTENING.md`).

## Topic

개인화하되 특정 관심사 과적합 금지.

MVP는 simple topic tag와 최근 topic 반복 회피까지만 한다. 정교한 topic
budget은 Future다.
