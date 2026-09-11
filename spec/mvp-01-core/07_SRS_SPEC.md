# SRS Specification

-   WHEN: FSRS.
-   WHAT: Learning Engine + contextual content.
-   최소 meaningful exposure 5.
-   단순 화면 통과를 모두 exposure로 세지 않는다.
-   초기 original/near-original anchor 후 varied context.
-   2회 성공 후 종료 같은 규칙 금지.
-   몰랐음/오답은 강한 negative evidence, 애매함은 중간 evidence.
-   FSRS scheduling state와 mastery score는 분리한다.

## Explicit signal → FSRS rating

MVP mapping:

``` text
몰랐음       -> Again
애매함       -> Hard
알고 있었음  -> Good

probe incorrect -> Again
probe uncertain -> Hard
probe correct   -> Good
```

`Easy`는 MVP UI에서 사용하지 않는다.

## FSRS 라이브러리 바인딩

MVP는 PyPI distribution `fsrs` 6.x를 사용한다
(`docs/decisions/ADR-003-fsrs-library-binding.md`).

``` text
Rating: Again = 1 | Hard = 2 | Good = 3 | Easy = 4
```

MVP는 `1~3`만 기록한다. `Card` 필드와 `review_states` 컬럼의 대응은
`04_DB_SPEC.md`를 따른다.

fuzzing은 MVP에서 끈다(`Scheduler(enable_fuzzing = False)`). fuzzing은
대규모 덱의 due 쏠림을 흩는 ± jitter이며 사용자 1명 규모에서는 이득이
없고 테스트 재현성만 깎는다. 이것은 **interval cap이 아니다.** FSRS가
계산한 interval을 jitter 없이 그대로 쓰는 것이므로 아래 `Minimum 5
Exposures와 FSRS의 분리`의 "interval을 cap하지 않는다"와 충돌하지 않는다.
값의 canonical 정의는 `14_CONFIGURATION.md`의 `srs.fsrs_enable_fuzzing`에
둔다.

## No-signal review

**무신호 판정의 canonical 정의는 이 절이다.**

판정 단위는 presentation 전체가 아니라 **(presentation, target item)
쌍**이다. 한 문장에 target이 둘이고 하나만 self-report를 받았다면 다른
하나는 무신호다.

``` text
신호 있음 = 그 (presentation, learning_item)에 대해
            FSRS rating을 만드는 explicit evidence event가 존재한다

self_report_known | self_report_uncertain | self_report_unknown
mastery_probe_known | mastery_probe_uncertain | mastery_probe_unknown

무신호   = 위 6개 중 어느 것도 없다
```

따라서 다음은 **전부 무신호다.** 있어도 무신호 처리를 막지 못한다.

``` text
item_clicked
explanation_revealed
translation_revealed
mastery_probe_shown          (probe를 냈지만 답하지 않음)
mastery_probe_skipped        (건너뛰기)
sentence_viewed
sentence_completed
```

v0.2의 "item을 누르지 않고 / self-report도 하지 않고 / probe도 없고"라는
서술은 이 목록을 **신호로 오해하게 만든다.** 문자 그대로 읽으면 click 한
번이나 probe 제시만으로 무신호가 아니게 되고, 그러면
`deferred_until`이 설정되지 않아 그 due item이 같은 세션에서 무한히 다시
뽑힌다. 이는 `13_ACCEPTANCE_CRITERIA.md`의 "무신호 review가 무한 due
loop를 만들지 않음"과 `12_TEST_PLAN.md`의 Scenario B를 정면으로 어긴다.

기준을 "FSRS rating을 만드는가"로 두는 이유는 무신호 처리의 목적 자체가
둘이기 때문이다.

``` text
1. 증거 없는 review가 FSRS를 오염시키지 않게 한다
2. 그러면서도 무한 due loop를 막는다
```

`item_clicked`는 `02_LEARNING_POLICY.md`에서 auxiliary signal이고 mastery도
FSRS rating도 만들지 않는다. `mastery_probe_skipped`도 같은 문서의 `Skip`
규칙에서 "mastery evidence 아님 / FSRS grade 아님"이다. 둘 다 목적 1에
기여하지 않으므로 목적 2를 포기할 이유가 없다.

무신호일 때 **FSRS rating을 추론하지 않는다.**

``` text
no-click != Good
no-click != Easy
```

FSRS memory state(`stability` / `difficulty` / `state` / `step`)도,
애플리케이션 카운터(`reps` / `lapses`)도 **변경하지 않는다.** 대신 `review_states.deferred_until`을 설정해 같은 due item이
같은 세션에서 계속 반복되지 않게 한다.

무신호 처리는 `presentation_role = review`인 presentation에만 적용한다.
`new` / `exploration`에는 `review_states` 행이 아직 없을 수 있고, 아직
스케줄이 없는 item을 defer할 대상도 없다. 이때는
`user_item_learning_state.passive_no_signal_count`만 올린다
(`02_LEARNING_POLICY.md`의 `passive_exposures_before_probe`가 이 값을
쓴다).

무신호 처리로 하는 일은 정확히 다음 둘이다.

``` text
review_states.deferred_until = now + passive_review_deferral_hours
user_item_learning_state.passive_no_signal_count += 1
```

``` text
passive_review_deferral_hours = 12   # 초기 기본값, configurable
```

이 동작은 FSRS review 성공/실패가 아니라

``` text
passive exposure + temporary deferral
```

이다. `next_review_at`은 그대로 유지되며 due 상태도 유지된다.

## Minimum 5 Exposures와 FSRS의 분리

**minimum meaningful exposure 5회는 FSRS scheduling을 왜곡해서 달성하지
않는다.**

예: 첫 노출에서 `알고 있었음` → FSRS Good → 다음 정식 review가 멀리
잡혀도, Learning Engine은 별도의 **reinforcement exposure**를 추가해
meaningful exposure가 최소 5회에 도달하도록 한다.

``` text
FSRS            = 정식 복습 시점(WHEN)
Exposure policy = 충분한 문맥 경험 보장
```

FSRS interval을 억지로 cap하여 5회를 채우지 않는다.

Presentation의 상위 role은 다음 3개만 사용한다.

``` text
review / new / exploration
```

review 내부의 reason은 다음으로 구분한다.

``` text
fsrs_due        # FSRS가 due로 판단한 정식 복습
reinforcement   # 최소 노출 보장을 위한 추가 노출
context_repair  # 새 문맥 실패 후 한 단계 쉬운 문맥으로 되돌림
```

사용자별 학습 role을 sentence 자체에 저장하지 않는다. v0.2까지 있던
`sentence_items.role = incidental` 설계는 제거한다(`04_DB_SPEC.md`).

## Meaningful Exposure 정의

각 LearningItem은 최소 5회 meaningful exposure를 갖는다. 단순히 화면에
스쳐 지나간 것을 모두 exposure로 세지 않는다.

canonical source는 integer counter가 아니라 `item_exposures` row다
(`04_DB_SPEC.md`). `review_states.meaningful_exposure_count`는
denormalized cache일 뿐이다.

``` text
노출 건수 = invalidated_at IS NULL 인 item_exposures row 수
```

**엔진 판정에는 cache를 쓰지 않는다.** reinforcement 판정, context
progression, exploration 후보 조건처럼 결과가 candidate 선택이나 mastery /
FSRS 상태에 영향을 주는 계산은 전부 `item_exposures`를 센다. cache를 읽어도
되는 곳은 **결과가 학습 결정에 영향을 주지 않는 표시·집계**뿐이다
(`11_OBSERVABILITY.md`). 이유는 content flag/quarantine이
`invalidated_at`을 설정하는 시점과 cache 재계산 시점이 어긋날 수 있기
때문이다(`10_ERROR_HANDLING.md`).

### MVP에서 meaningful exposure로 인정하는 조건

세 조건을 모두 만족할 때 1회로 센다.

1.  target item이 포함된 sentence를 실제로 표시했다.
2.  사용자가 그 sentence에서 `Next`로 이동했거나 세션을 정상
    완료했다.
3.  해당 presentation이 invalid/quarantined content가 아니다.

### 중복 집계 금지

``` text
같은 study_presentation + 같은 learning_item = 최대 1 exposure
```

item click, explanation reveal, self-report를 각각 별도 exposure로
중복 집계하지 않는다. mastery probe와 review interaction은 그 자체로
별도 exposure를 만들지 않고, 해당 presentation의 exposure 1회에
포함된다.

`modality`는 MVP에서 사실상 `reading`만 사용한다. listening이 추가되면
별도 modality로 확장한다.

## Context Progression

Context progression은 `user_item_learning_state`로 추적한다
(`04_DB_SPEC.md`).

``` text
context_stage: anchor | near_original | varied | new_context
```

초기 progression 기본 정책:

``` text
Exposure 1 -> anchor
Exposure 2 -> anchor 또는 near_original
Exposure 3 -> near_original 또는 varied
Exposure 4 -> varied / new_context
Exposure 5 -> new_context
```

이는 rigid한 exact sequence가 아니라 Learning Engine의 기본 정책이며
config로 조정 가능하다.

예 (`任せる`):

``` text
1. この仕事、田中さんに任せてもいい？   anchor
2. 같은 원문 또는 최소 변형              near_original
3. あとは彼に任せるよ。                  varied
4. 다른 일상 상황                        new_context
```

`2회 성공하면 종료` 같은 규칙은 사용하지 않는다.

## New-context Failure

새로운 context에서 실패했다고 해서 즉시 item 자체의 완전한 lapse라고
단정하지 않는다. 문장 난이도 때문일 수도 있다.

-   explicit `몰랐음`이 발생했다면 FSRS rating은 **Again으로 기록한다.**
-   다음 presentation은 `context_repair` reason으로 **한 단계 쉬운
    context**를 선택할 수 있다.

즉 다음 둘을 별도 의사결정으로 취급한다.

``` text
FSRS evidence      (기록)
다음 context 선택   (Learning Engine)
```

콘텐츠가 flag/quarantine되면 그 presentation에서 파생된 negative
evidence는 무효화할 수 있다(`10_ERROR_HANDLING.md`).
