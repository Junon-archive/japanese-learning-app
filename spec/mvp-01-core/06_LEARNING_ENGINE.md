# Learning Engine

## Inputs

due FSRS, exposure count, mastery, recent events, mix, topics, Ready
Pool, backlog.

## Outputs

target item(s), role, desired difficulty/topic, probe 여부, pool
replenishment 필요 여부.

초기 config: 70/20/10, 신규 1\~2, 12분, probe 2\~4, min exposure 5.

No-click만으로 mastery 상승 금지. Exploration은 희귀어 랜덤 공급이
아니라 mastery 정보가 부족한 적절한 item을 탐색하는 것. 다음 문장은
Ready Pool 우선, 부족하면 background job.

구체 선정 기준은 아래 `Exploration Item 선정` 절에 둔다.

## Ready Sentence Pool

Sentence 자체(global content)와 사용자별 Ready Pool을 분리한다.

``` text
Ready Pool = 해당 user의 user_sentence_candidates 중 status = ready 인 집합
```

candidate는 "이 사용자에게 지금 어떤 목적으로 보여주는가"를 가진다.

``` text
presentation_role : review | new | exploration
review_reason     : fsrs_due | reinforcement | context_repair
context_stage     : anchor | near_original | varied | new_context
status            : queued | ready | shown | consumed | quarantined | expired
```

target item은 `user_sentence_candidate_targets` join table로 연결하며
문장당 1\~2개를 지원한다. 스키마는 `04_DB_SPEC.md`를 따른다.

## Category Mix 계산

비율의 단위는 **한 Study Session에서 실제로 제시된 sentence
presentation 수**다.

``` text
Review      70%
New         20%
Exploration 10%
```

정확한 정수 quota를 세션 시작 시 고정하지 않는다. 매 다음 sentence 선택
시 각 category의 deficit을 계산한다.

``` text
deficit = target_ratio * total_presented - actual_presented
```

여기서 `total_presented`는 **이번에 제시할 presentation을 포함한
수**로 계산한다(세션 첫 문장에서도 deficit이 모두 0이 되지 않게 한다).

deficit이 가장 큰 category 중 사용 가능한 pool이 있는 것을 선택한다.
Pool이 없는 category는 건너뛰고 사용 가능한 category 중 deficit이 가장
큰 것을 선택한다. 따라서 15문장처럼 비율이 정확히 나누어지지 않아도
자연스럽게 근사한다.

동률일 때는 stable deterministic tie-break를 사용한다
(`review → new → exploration` 순).

초기 기본값(review 0.70 / new 0.20 / exploration 0.10)의 **canonical
정의는 `14_CONFIGURATION.md`에 둔다.** 다른 문서의 수치 표기는 설명용이며
충돌 시 config 값이 우선한다. Acceptance Criteria에는 숫자를 하드코딩하지
않는다(`13_ACCEPTANCE_CRITERIA.md`).

## Review Reason 선택

Category Mix에서 `review` 슬롯이 선택된 뒤, 그 슬롯을 어떤
`review_reason`으로 채울지는 이 절에서 정한다. **review reason 선택의
canonical 정의는 여기에 둔다.** 각 reason 값의 의미와 발생 조건은
`07_SRS_SPEC.md`를 따른다.

기본 우선순위:

``` text
1. context_repair   직전 새 문맥 실패를 방치하면 오답이 굳는다
2. fsrs_due         스케줄 준수가 SRS의 본질
3. reinforcement    FSRS를 왜곡하지 않는 보충이므로 마지막
```

reason의 **사용 가능 여부는 Category Mix와 같은 기준**이다. 즉 해당
`review_reason`을 가진 `status = ready` candidate가 Ready Pool에
존재하는지로 판단한다. 사용 가능한 reason이 하나도 없으면 review 슬롯을
포기하고 `Pool Fallback` 절차로 넘어간다.

reason 선택 자체는 FSRS rating도 mastery evidence도 만들지 않는다. 무신호
review 처리는 그대로 `07_SRS_SPEC.md`의 passive exposure + temporary
deferral을 따른다.

### reinforcement 최소 지분

우선순위만 적용하면 due가 밀린 사용자에게 `reinforcement`가 영구히 굶고,
최소 meaningful exposure 5회가 FSRS 일정에만 의존하게 된다. 이는 "FSRS
interval을 cap하지 않고 reinforcement로 5회를 채운다"는
`07_SRS_SPEC.md`의 전제를 깬다. 이를 막기 위해 review 슬롯 안에서
reinforcement의 최소 지분을 보장한다.

단위는 Category Mix와 동일하게 **이번 세션에서 실제로 제시된 review
presentation 수**다.

``` text
reinforcement_deficit =
    reinforcement_min_share_of_review * review_total_presented
    - reinforcement_presented
```

-   `review_total_presented`: 이번 세션에서 이미 제시된 review
    presentation 수 + **이번에 제시할 presentation 1**. reason과 무관하게
    모든 review presentation이 분모에 들어간다.
-   `reinforcement_presented`: 이번 세션에서 이미 제시된
    `review_reason = reinforcement` presentation 수.

선택 절차:

``` text
1. context_repair 사용 가능하면          -> context_repair
2. reinforcement_deficit > 0 이고
   reinforcement 사용 가능하면           -> reinforcement
3. fsrs_due 사용 가능하면                -> fsrs_due
4. reinforcement 사용 가능하면           -> reinforcement
5. 아무것도 없으면                       -> Pool Fallback
```

최소 지분은 `fsrs_due`보다만 앞서고 `context_repair`는 넘지 않는다.
context_repair는 직전 실패에 의해서만 생기므로 수가 제한적이고, 미루면
틀린 이해가 굳기 때문이다.

`reinforcement_min_share_of_review`의 canonical 값은
`14_CONFIGURATION.md`에 둔다. 이 값은 category ratio와 달리 review 슬롯
**내부** 지분이므로 `review_ratio + new_ratio + exploration_ratio = 1.0`
검증에 포함되지 않는다. 값이 0이면 최소 지분 규칙은 꺼지고 순수
우선순위만 적용된다.

이 계산은 Category Mix의 deficit과 같은 이유로 **최소 지분을 앞쪽에서
먼저 갚는다.** 예: share = 0.2이고 context_repair가 없으며 모든 reason이
사용 가능하면, 세션의 review presentation 순서는
`reinforcement, fsrs_due, fsrs_due, fsrs_due, fsrs_due, reinforcement, ...`
가 된다. 누적 reinforcement 비중은 review presentation 수가 늘수록
설정값으로 수렴한다.

reason이 정해진 뒤 같은 reason 안에서의 정렬은 아래 `Review Ordering`을
따른다.

## Review Ordering

Due review 정렬 기본 순서:

1.  `deferred_until IS NULL` 또는 `deferred_until <= now`
2.  `next_review_at ASC`
3.  낮은 `comprehension_mastery` 우선 (NULL은 낮은 값으로 취급)
4.  stable deterministic tie-break (`learning_item_id` 등)

세션에서 보여주지 못한 due item은:

-   lapse 처리하지 않는다.
-   실패 처리하지 않는다.
-   그대로 due 상태를 유지한다.

## Backlog

``` text
backlog = 현재 시점 기준 eligible due item count
```

`backlog_threshold` 이상이면 configured review ratio를 높이고 new ratio를
낮출 수 있다. threshold와 adjusted ratio는 config다.

adjusted ratio는 일부 키만 바꾸는 것이 아니라 세 ratio를 `backlog_*`
**세트로 통째로 교체**하는 것이다. 교체된 세트도 같은 deficit 계산에
그대로 들어가므로 합이 1.0이어야 하며 config 로드 시 검증한다
(`14_CONFIGURATION.md`).

사용자가 바쁜 날에도 `overdue 93` 같은 부채감 UX를 만들지 않는다.

## Exploration Item 선정

Exploration은 희귀어 랜덤 공급이 아니라 **mastery 정보가 부족한 item을
확인하는 것**이다. **exploration target item 선정의 canonical 정의는
여기에 둔다.**

### 후보 조건

다음을 모두 만족하는 `learning_item`만 exploration target이 된다.

``` text
1. user_mastery 행이 없거나 comprehension_mastery IS NULL
2. user_item_learning_state 행이 없거나
   is_active_learning_target = false
3. 최근 exploration_recent_days 안에 해당 사용자에게 노출되지 않음
```

조건 1의 NULL은 "능력이 0"이 아니라 **"아직 충분한 evidence가 없음"**
이다(`02_LEARNING_POLICY.md`). 조건 2는 incidental click 등으로 이미 정식
학습 대상으로 승격된 item을 exploration으로 다시 잡지 않기 위한 것이다.

조건 3의 판정 소스는 **`item_exposures`**다. denormalized cache인
`review_states.meaningful_exposure_count`는 이 판정에 쓰지 않는다
(`07_SRS_SPEC.md`).

``` text
최근 노출됨 = 다음을 만족하는 item_exposures row가 1건 이상 존재
    user_id           = 현재 사용자
    learning_item_id  = 후보 item
    invalidated_at IS NULL
    created_at        > now - exploration_recent_days
```

이미 Ready Pool에 있는 exploration candidate를 선택할 때도 그 target
item이 위 조건을 여전히 만족하는지 확인한다. 만족하지 않으면 건너뛰고
다음 candidate로 넘어간다.

### 정렬

``` text
1. difficulty_distance ASC
2. frequency_rank ASC   (아래 정의, 없는 item은 맨 뒤)
3. learning_item_id ASC (결정론적 tie-break)
```

``` text
difficulty_distance = | rank(learning_items.difficulty_label)
                      - rank(users.starting_level) |
```

`rank()`는 `difficulty_label`과 `starting_level`이 공유하는 단조 ladder의
index다. MVP ladder는 다음 3단계이며 이 정의가 canonical이다.

``` text
beginner = 0  <  intermediate = 1  <  advanced = 2
```

`difficulty_label`이 NULL이거나 ladder에 없는 값이면 distance를 계산할 수
없으므로 **정렬 맨 뒤**로 보낸다(알려진 label을 모두 소진한 뒤에만
선택된다). label을 추가하려면 ladder를 먼저 갱신한다. MVP에서 실사용하는
`starting_level`은 `beginner` 하나다(`Cold Start`).

### 고빈도 판정과 그 한계

`frequency_rank`는 다음 순서로 결정론적으로 정한다. **`learning_items`에
frequency 컬럼을 추가하지 않는다.**

``` text
1. learning_items.metadata_json.frequency_rank (정수, 작을수록 고빈도)
2. 없으면 seed 적재 순서 (version-controlled seed 파일의 행 순서)
3. 둘 다 없으면 없음으로 취급하고 정렬 맨 뒤
```

`frequency_rank`는 seed 파일이 함께 들고 오는 값이며 기존
`learning_items.metadata_json`에 담는다. 스키마 변경이 아니다
(`04_DB_SPEC.md`). seed는 Git으로 관리되므로 적재 순서도 재현 가능하다.

**한계:** `origin = generated` item에는 frequency 정보가 없다. 따라서
빈도 정렬은 사실상 seed item에만 적용되고, generated item은 같은
difficulty_distance 안에서 seed item 뒤에 놓인 뒤 `learning_item_id`로만
정렬된다. 코퍼스 기반 frequency는 MVP 범위가 아니다.

### Cold start의 exploration

첫 세션에는 `user_mastery`와 `item_exposures`가 거의 비어 있어 후보 조건을
만족하는 item이 과다하다. 이때 별도 분기를 두지 않는다. 위 정렬이 그대로
"**starter seed item 중 고빈도부터**"를 만든다. 초기 사용자는
`starting_level = beginner`이고 seed item이 저난이도 label을 가지므로
difficulty_distance가 동률이 되어 `frequency_rank`가 순서를 결정한다.

## Cold Start

신규 사용자에게 Review 70%를 **강제로 만들지 않는다.** Category pool이
없으면 available category만 사용한다.

-   초기 사용자는 `starting_level = beginner`를 기본으로 한다.
-   긴 onboarding JLPT 시험이나 placement test는 MVP에 없다.
-   초기 세션은 **new + exploration 중심**으로 시작하고, Review pool이
    생기면 configured ratio로 점진적으로 수렴한다.

초기 학습 item 공급을 위해 **작은 version-controlled starter seed
set**을 둔다.

-   초급 사용자의 첫 몇 세션을 시작할 수 있게 하는 것이 목적이다.
-   everyday high-frequency word/grammar/expression 중심.
-   정확한 개수는 제품 명세에 고정하지 않는다.

seed data 요구사항은 `04_DB_SPEC.md`의 Seed Data 절을 따른다. 초기 세션의
exploration 대상 선정은 위 `Exploration Item 선정` 절을 따른다.

## Pool Fallback

선택 대상 category의 Ready candidate가 없으면 다음 순서로 처리한다.

``` text
1. 다른 available category 선택
2. 안전한 기존 anchor/near-original reinforcement candidate 사용
3. background replenishment job enqueue
```

세션을 LLM 응답 대기로 block하지 않는다. **모든 pool이 비어도 API
request handler에서 provider를 synchronous 호출하지 않는다**
(`08_LLM_SPEC.md`의 LLM 호출 경계).

사용자에게는 짧은 안내만 표시하고 무한 spinner를 보여주지 않는다
(`10_ERROR_HANDLING.md`).
