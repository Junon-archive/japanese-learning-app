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

review sentence에서 FSRS rating을 만드는 explicit evidence가 없었다면
**rating을 추론하지 않는다.**

``` text
no-click != Good
no-click != Easy
```

**무엇이 "신호 있음"인지의 canonical 정의와 그 경우의 처리는
`07_SRS_SPEC.md`의 `No-signal review`다.** 요약하면 self-report 3종과
probe 응답 3종(`known/uncertain/unknown`)만 신호이며, 위 `Auxiliary
signal` 목록과 `mastery_probe_skipped`는 있어도 무신호다.

## Active Probe

사용자가 unknown-unknown을 가질 수 있으므로 앱이 먼저 확인한다. 12분
세션당 초기 목표 약 2\~4회 이하, configurable.

**세션 안에서 probe를 언제 제시하는지(간격·상한·min을 강제하지 않는
이유)는 `06_LEARNING_ENGINE.md`의 `Probe Pacing`이 canonical이다.** 아래
`Probe 대상 우선순위`는 "어떤 item을 묻는가"를 정하고, `Probe Pacing`은
"언제 묻는가"를 정한다.

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

**MVP 확정 목록은 2단이다.** 위에서부터 처음 만족하는 순위로 정한다.

1.  explicit evidence가 아직 없는 item
    (`user_mastery` 행이 없거나 `comprehension_mastery IS NULL`)
2.  오래 probe하지 않은 uncertain item

1번 안에서는
`user_item_learning_state.passive_no_signal_count >= passive_exposures_before_probe`
인 item을 **먼저** 묻는다. 반복해서 스쳐 지나갔는데 한 번도 말하지 않은
item이 확인 가치가 가장 크다.

2번의 `uncertain`은 `comprehension_mastery`가 위 `Mastery를 실제로
변경하는 explicit evidence`의 세 observation 값 중 `애매함`에 가장 가까운
경우다(같은 거리면 `애매함` 쪽으로 본다). 새 임계값을 만들지 않는다. "오래 probe하지 않은"은 별도 정렬
기준이 아니라 아래 `probe cooldown` 제외가 이미 보장한다.

v0.2의 4단 목록에서 두 항목이 빠진 이유는 다음과 같다
(`docs/decisions/ADR-011-probe-target-priority.md`).

-   **"passive exposure가 반복됐지만 explicit evidence가 없는 item"은
    독립 순위가 될 수 없다.** `user_mastery` 행은 explicit evidence가
    발생할 때 만들어지고 그 시점에 `evidence_count = 1`,
    `comprehension_mastery`가 non-NULL이 된다. 따라서
    `evidence_count = 0`인 상태는 **항상 1번에 먼저 걸린다.** 원래 의도인
    "passive 노출이 쌓인 것부터"는 위와 같이 1번 **내부의 정렬 기준**으로
    남긴다.
-   **"서로 충돌하는 evidence가 있는 item"은 MVP에서 순위로 두지
    않는다.** EMA 갱신(`mastery_ema_alpha`) 아래에서 `알고 있었음`과
    `몰랐음`이 섞인 item의 mastery는 가운데로 모이므로 2번이 이미 잡는다.
    충돌을 따로 판정하려면 `learning_events`를 되짚는 새 규칙이 필요하고
    그 규칙 자체가 새 정책이 된다. 필요성이 실사용에서 드러나면 그때
    정의한다.

다음은 probe하지 않는다.

-   방금 explicit feedback을 받은 item
-   probe cooldown 중인 item

### Skip

``` text
skip = mastery evidence 아님
skip = FSRS grade 아님
skip = 무신호          (07_SRS_SPEC.md의 No-signal review)
```

skip 후 같은 item을 즉시 다시 묻지 않는다. 연속 skip에 대한 세션 단위
probe budget 축소는 **MVP에서 구현하지 않는다.** 같은 item을 다시 묻지
않는 것은 `probe_skip_cooldown_days`가 item 단위로 이미 보장한다
(`06_LEARNING_ENGINE.md`의 `Probe Pacing`).

관련 config: `probe_skip_cooldown_days`,
`passive_exposures_before_probe`.

## Incidental Item Click

사용자가 target이 아닌 tappable expression을 눌렀을 때:

-   click 자체는 raw event로만 남긴다.
-   **바로 SRS에 등록하지 않는다.**

이후 사용자가 `몰랐음` 또는 `애매함`을 선택하면 해당 LearningItem을 개인
학습 상태에 활성화하고 신규 learning target으로 등록한다
(`user_item_learning_state.is_active_learning_target`).

그 시점에 일어나는 일은 정확히 다음 넷이다.

``` text
is_active_learning_target = true
anchor_sentence_id        = 그 presentation의 sentence_id   (NULL이었을 때만)
FSRS                      07_SRS_SPEC.md의 mapping대로 즉시 기록한다
item_exposures            만들지 않는다
                          (그 item은 이 presentation의 target이 아니다)
```

그 결과 이 item은 **exposure 0건인 학습 target**이 되어 `new` pool에 들어가고,
첫 `new` presentation에서 **사용자가 그것을 만났던 바로 그 문장**을 anchor로
다시 본다(`06_LEARNING_ENGINE.md`의 `role별 규칙`). 최초 문맥을 잃지 않으면서도
"스쳐 지나간 것을 exposure로 세지 않는다"를 지키는 방법이 이것이다. canonical
정의는 `07_SRS_SPEC.md`의 `target item의 canonical 정의`와
`anchor_sentence_id 지정`이다.

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
`07_SRS_SPEC.md`와 `04_DB_SPEC.md`의 `item_exposures`를 따른다. 이 문맥
사다리를 **언제 한 칸 올리고 내리는지**(`context_stage` 전이)의 canonical
정의도 `07_SRS_SPEC.md`의 `Context Progression`이다.

MVP에는 audio가 없으므로 listening exposure는 Future다
(`spec/future/LISTENING.md`).

## Topic

개인화하되 특정 관심사 과적합 금지.

MVP는 simple topic tag와 최근 topic 반복 회피까지만 한다. 정교한 topic
budget은 Future다.
