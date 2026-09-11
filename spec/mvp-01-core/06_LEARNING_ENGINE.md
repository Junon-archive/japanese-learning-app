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

사용자가 바쁜 날에도 `overdue 93` 같은 부채감 UX를 만들지 않는다.

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

seed data 요구사항은 `04_DB_SPEC.md`의 Seed Data 절을 따른다.

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
