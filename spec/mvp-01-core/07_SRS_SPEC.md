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

## No-signal review

사용자가 review sentence를 보고

-   item을 누르지 않고
-   self-report도 하지 않고
-   probe도 없고
-   그냥 다음 sentence로 이동

했다면 **FSRS rating을 추론하지 않는다.**

``` text
no-click != Good
no-click != Easy
```

FSRS memory state(stability/difficulty/reps/lapses)는 **변경하지
않는다.** 대신 `review_states.deferred_until`을 설정해 같은 due item이
같은 세션에서 계속 반복되지 않게 한다.

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
