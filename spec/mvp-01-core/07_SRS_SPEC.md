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

### deferral 해제

`deferred_until`은 **explicit evidence가 그 item의 FSRS review로 기록되는
순간 `NULL`로 지운다.** 해제 지점은 rating을 기록하는 그 자리 하나다.

``` text
explicit review 기록 (self-report 3종 | probe 응답 3종)
    -> review_states.deferred_until = NULL
```

deferral의 존재 이유는 "이 review에 증거가 없었다" 하나뿐이다. 증거가
도착하면 FSRS가 `next_review_at`을 다시 계산하므로 그때부터는 스케줄이 곧
답이고, deferral을 남겨 두면 `Again` 직후 몇 분 뒤로 잡힌 due를 12시간 동안
가린다. 그것은 `06_LEARNING_ENGINE.md`가 말하는 "스케줄 준수"가 아니라 스케줄
무시다.

해제해도 무한 due loop는 돌아오지 않는다. loop를 막는 것은 deferral의
**지속**이 아니라 무신호 presentation마다 다시 거는 동작이고, 증거가 있는
presentation은 애초에 loop의 대상이 아니다. 다음 presentation이 또 무신호이면
그 시점에 다시 걸린다.

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

### target item의 canonical 정의

**조건 1의 `target item`은 그 presentation의
`user_sentence_candidate_targets` row다.** materialization 시점에 고정되며
(`06_LEARNING_ENGINE.md`), 화면에 보인 `is_tappable` item 전체가 아니다.

따라서 target이 **아닌** item을 눌러 `몰랐음`/`애매함`을 고른 경우, 그
evidence는 mastery와 FSRS에 그대로 기록되지만
(`02_LEARNING_POLICY.md`의 `Incidental Item Click`) **그 presentation은
그 item의 exposure를 만들지 않는다.** 같은 이유로 `context_stage` 전이와
`context_repair` 판정도 그 item에는 적용하지 않는다.

근거:

-   exposure는 "엔진이 그 item을 위해 고른 문맥을 몇 번 경험했는가"를 세는
    값이다. 문장의 모든 item을 세면 "단순히 스쳐 지나간 것을 모두 exposure로
    세지 않는다"가 무너지고, 한 문장에 tappable이 10개면 9개가 공짜 노출을
    얻는다.
-   다른 item을 위해 고른 문맥의 `context_stage`가 이 item의 ladder를 움직이면
    progression이 자기 item의 노출 이력과 무관해진다. 최초 만남이 곧바로
    `new_context` 실패로 기록되는 것이 그 예다.
-   **그 문맥이 버려지는 것은 아니다.** 그 self-report는 item을 학습 target으로
    승격시키면서 그 문장을 `anchor_sentence_id`로 남기므로(아래 `Context
    Progression`), 그 item의 첫 `new` presentation이 **같은 문장**을 anchor로
    다시 제시한다(`06_LEARNING_ENGINE.md`의 `role별 규칙`). 최초 문맥은 5회
    중 1회로 정상 계상되며 그 시점이 한 presentation 뒤로 밀릴 뿐이다.

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

ladder 순서는 다음이며, `06_LEARNING_ENGINE.md`의 `context_repair` 판정도
같은 순서를 쓴다.

``` text
anchor < near_original < varied < new_context
```

실패가 한 번도 없을 때의 기본 진행:

``` text
Exposure 1 -> anchor
Exposure 2 -> anchor 또는 near_original
Exposure 3 -> near_original 또는 varied
Exposure 4 -> varied / new_context
Exposure 5 -> new_context
```

예 (`任せる`):

``` text
1. この仕事、田中さんに任せてもいい？   anchor
2. 같은 원문 또는 최소 변형              near_original
3. あとは彼に任せるよ。                  varied
4. 다른 일상 상황                        new_context
```

`2회 성공하면 종료` 같은 규칙은 사용하지 않는다.

### 전이 규칙 (MVP 확정)

**`context_stage`를 누가 언제 바꾸는지의 canonical 정의는 이 절이다.** 위 표의
"또는"은 여기서 결정론적으로 해소된다.

주체와 시점:

``` text
주체   presentation을 닫는 단일 경로 (`/complete` 와 `/finish` 가 공유한다)
시점   meaningful exposure를 기록하는 바로 그 트랜잭션
대상   그 presentation에서 exposure가 기록된 item
       (= 이 문서의 `target item의 canonical 정의`를 만족하는 item)
```

exposure를 만들지 않는 presentation(quarantined content)은 stage도 바꾸지
않는다. 이미 닫힌 presentation을 다시 닫아도 바뀌지 않는다. 전이는 exposure
기록과 **같은 idempotency를 공유한다.**

전이:

``` text
S_shown = 그 presentation의 context_stage
          (= 방금 기록된 item_exposures.context_stage)
S_cur   = user_item_learning_state.context_stage

그 (presentation, item)에 explicit `몰랐음`이 있으면
   (self_report_unknown | mastery_probe_unknown)
        S_cur <- min(S_cur, one_step_down(S_shown))     # 바닥은 anchor
아니면
        S_cur <- max(S_cur, one_step_up(S_shown))       # 천장은 new_context
```

`알고 있었음` / `애매함` / **무신호**는 모두 올린다. 위 표의 단위가 signal이
아니라 exposure 수이기 때문이다. 내리는 것은 explicit `몰랐음` 하나뿐이며,
그것이 아래 `New-context Failure`가 말하는 실패다.

왜 이 규칙인가:

-   실패가 없는 경로를 따라가면 위 표의 exact sequence와 같은 결과가 나온다
    (anchor → near_original → varied → new_context → new_context). `任せる`
    예시와 정확히 일치한다.
-   `Exposure 2 -> anchor 또는 near_original`의 "또는"은 **첫 노출에서
    실패했는가**였다. 첫 문맥에서 `몰랐음`이면 같은 anchor를 한 번 더 보고,
    아니면 near_original로 간다.
-   `min` / `max`를 쓰는 이유는 **이미 진행한 ladder를 낮은 stage의
    presentation이 끌어내리지 않게** 하기 위해서다. Ready Pool에 남아 있던
    낮은 stage candidate나 `Pool Fallback` 2단계의 anchor reinforcement는
    성공해도 stage를 되돌리지 않는다. 반대로 실패는 **실제로 본 문맥**을
    기준으로 한 단계 내려간다.
-   `anchor`에서 `몰랐음`이면 내려갈 곳이 없어 anchor에 머문다. 같은 anchor
    문장이 반복되는 이 상태는 `01_PRODUCT_PRINCIPLES.md`가 금지한 "문맥 없는
    반복"이 아니다. 전이 규칙이 없어서가 아니라 **증거가 계속 실패를 가리켜서**
    일어나며, 한 번이라도 `몰랐음`이 아닌 결과가 나오면 즉시 ladder를 오른다.

이 ladder에는 **config 키를 두지 않는다.** "config로 조정 가능하다"던 v0.2
서술은 철회한다. 조정 대상이 될 만한 값은 "한 stage에 몇 번 머무는가"인데,
그것을 키로 두려면 *현재 stage에서 몇 번 노출했는가*를 알아야 하고
`user_item_learning_state`에 새 컬럼이 필요하다(직전 stage 변경 시각이
없으므로 `item_exposures`만으로는 복원되지 않는다). MVP는 새 컬럼을 만들지
않으므로, ladder를 바꾸는 것은 config 변경이 아니라 **이 절의 명세 변경**이다.
노출 총량을 조정하는 키는 `minimum_meaningful_exposures` 하나로 충분하다
(`14_CONFIGURATION.md`).

### anchor_sentence_id 지정

`anchor_sentence_id`는 그 item의 **최초 학습 문맥**이다(`04_DB_SPEC.md`).
값이 NULL인 동안 다음 두 시점 중 먼저 오는 쪽이 기록한다.

``` text
1. 그 item이 explicit `몰랐음`/`애매함`으로 학습 target이 되는 시점
   -> 그 self-report가 일어난 presentation의 sentence_id
      (02_LEARNING_POLICY.md의 Incidental Item Click)

2. materialization이 `anchor` stage 문장을 고르는 시점
   -> 06_LEARNING_ENGINE.md의 `stage → sentence` 표
```

1이 필요한 이유는, 사용자가 실제로 만나 물어본 문장이 그 item의 최초 학습
문맥이기 때문이다. 1이 없으면 사용자가 A 문장에서 누른 item의 anchor가
`sentences.id ASC`로 뽑힌 낯선 B 문장이 되고, `anchor`와 `near_original` 노출이
전부 사용자가 본 적 없는 계열로 채워진다.

이미 값이 있으면 **덮어쓰지 않는다.** 유일한 예외는 quarantine 재지정이며 그
규칙의 canonical 정의는 `06_LEARNING_ENGINE.md`의
`anchor 문장을 더는 쓸 수 없을 때`다.

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

**"한 단계 쉬운 context"는 `context_stage`의 한 단계 하강을 뜻한다.** 같은
stage 안에서 다른 문장을 고르는 것이 아니다. 상태 전이 자체는 위 `전이 규칙`이
정의하며 **결정론적이고 조건부가 아니다** --- explicit `몰랐음`이면 stage는
언제나 내려간다(바닥 `anchor`). `할 수 있다`가 걸리는 것은 그 다음
presentation이 실제로 `context_repair`가 되는지이고, 그 판정과 우선순위는
`06_LEARNING_ENGINE.md`(`review candidate: reason 판정`, `Review Reason 선택`)가
canonical이다. 되돌린 stage의 노출이 실제로 일어나면 repair 조건이 스스로
꺼진다.

stage가 이미 `anchor`면 내려갈 곳이 없으므로 `context_repair`도 생기지 않는다.
anchor보다 쉬운 문맥은 MVP에 없다.

콘텐츠가 flag/quarantine되면 그 presentation에서 파생된 negative
evidence는 무효화할 수 있다(`10_ERROR_HANDLING.md`).
