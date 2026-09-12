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
Ready Pool 우선, 비어 있으면 먼저 `Candidate Materialization`으로 채우고,
그래도 만들 것이 없으면 background job.

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

## Candidate Materialization

**`user_sentence_candidates` row를 누가 언제 만드는지의 canonical
정의는 이 절이다.** 다른 문서는 여기를 참조한다.

Ready Pool은 사용자별 테이블인데 seed 적재는 global content
(`learning_items` / `sentences` / `sentence_items` /
`sentence_item_spans` / `sentence_item_explanations`)만 만든다. 따라서
누군가 global content를 사용자·역할·stage에 투영해야 Ready Pool이
생긴다. 그 일은 **Wave 2의 Learning Engine이 request 경로에서 직접
한다.** background worker가 아니다.

근거:

-   materialization은 LLM 호출이 아니라 **결정론적 DB 연산**이다. 이미
    `validated`인 문장을 사용자에게 매핑할 뿐이므로 `08_LLM_SPEC.md`의
    `LLM 호출 경계`가 금지하는 provider 호출이 아니고, 같은 문서가
    request handler에 허용한
    `DB 읽기 / event 저장 / candidate 선택 / 필요 시 job enqueue`
    범위 안이다.
-   worker에 맡기면 seed만 적재된 신규 사용자의 Ready Pool이 worker가
    돌 때까지 비어 있다. 그러면 `12_TEST_PLAN.md`의 "seed 상태의 신규
    사용자가 첫 세션을 시작할 수 있다"와 `13_ACCEPTANCE_CRITERIA.md`의
    "신규 사용자가 seed 기반으로 첫 세션을 시작 가능"을 Wave 2에서 검증할
    수 없다.
-   **seed loader는 candidate를 만들지 않는다.** seed는 global content고
    candidate는 사용자별이다. 적재 시점에 사용자가 없을 수 있고, 나중에
    만들어진 사용자는 아무것도 받지 못한다.
-   **계정 생성 시점에도 만들지 않는다.** 같은 문제의 거울상이다. 계정
    생성 뒤에 적재·생성된 콘텐츠가 영원히 반영되지 않고, 계정 생성
    CLI가 Learning Engine에 의존하게 된다.

이 결정으로 **새 테이블은 만들지 않는다**
(`docs/decisions/ADR-010-candidate-materialization.md`).

### 실행 시점과 대상

``` text
POST /api/study/session            세션 생성/resume 직후 1회
POST /api/study/session/{id}/next  선택된 category에 ready candidate가 없을 때
                                   Pool Fallback 0단계로 1회
```

**한 요청에서 최대 1회** 실행한다. `/next` 한 번이 여러 category를 훑어도
그 사이에 materialization은 한 번만 일어난다. 순서의 canonical 정의는 이
문서의 `Pool Fallback`이다.

대상은 **요청을 보낸 인증 사용자 한 명**이다. 전체 사용자를 순회하지
않는다. 한 번의 실행에서 `presentation_role`별로 최대
`candidate_materialization_batch_size`개까지 만든다
(`14_CONFIGURATION.md`). 상한이 없으면 첫 세션 한 번에 seed 전체가
candidate로 복제된다.

같은 조합의 candidate를 중복 생성하지 않는다. 재실행은 idempotent해야
한다(`04_DB_SPEC.md`의 `user_sentence_candidates` 유일성 규칙).

### 공통 필드

``` text
status       ready
created_at   현재 시각
updated_at   현재 시각
targets      user_sentence_candidate_targets에 target item 1~2개.
             그 사용자에게 review_states 행이 없으면 is_new_item = true.
```

`status`를 곧바로 `ready`로 쓰는 이유는 materialization이 이미 검증된
콘텐츠만 대상으로 하기 때문이다. `queued`는 **아직 콘텐츠가 없어
worker가 생성 중인 candidate**를 위한 값이며 Wave 3에서 쓴다. 두 값의
경계를 이렇게 고정한다.

``` text
queued  콘텐츠가 아직 없다. worker가 채운다.
ready   지금 그대로 제시할 수 있다.
```

`expired`는 **MVP에서 쓰지 않는다.** 이 엔진도 그 값을 쓰지 않으며, 특히
stage가 오른 뒤 남은 낮은 stage candidate를 만료시키지 않는다. 쓰는 주체와
시점이 없다는 사실과 그 근거의 canonical 정의는 `04_DB_SPEC.md`의
`user_sentence_candidates`다.

**Ready invariant**(`08_LLM_SPEC.md`): 대상 문장은
`sentences.status = validated`여야 하고, 그 문장의 `is_tappable = true`인
모든 `sentence_items`가 `status = validated`인
`sentence_item_explanations`를 가져야 한다. 하나라도 없으면 candidate를
만들지 않는다.

이 범위는 **target item만이 아니라 그 문장의 모든 tappable item**이며
generation validation이 쓰는 범위와 같다(`08_LLM_SPEC.md`의
`Ready invariant와 같은 범위`). seed loader도 같은 해석으로 적재한다. 세
곳이 다른 해석을 쓰면 생성은 통과했는데 candidate가 될 수 없는 문장이
조용히 쌓인다.

explanation 누락 때문에 문장을 건너뛰었다면 그 문장의 누락된
`sentence_item`마다 `EXPLAIN_ITEM`을 enqueue한다(`09_BACKGROUND_JOBS.md`의
`Enqueue 트리거와 idempotency key`가 canonical). **이번 실행에서 실제로
검사한 문장만** 대상이며 corpus 전체를 훑지 않는다.

### role별 규칙

`new`와 `exploration`은 `user_item_learning_state.is_active_learning_target`
으로 **서로 배타적으로** 갈린다. 겹치면 같은 item이 두 category에서
동시에 뽑혀 Category Mix가 무의미해진다.

``` text
exploration
  target item   Exploration Item 선정 절의 후보 조건·정렬을 그대로 따른다
                (mastery NULL + is_active_learning_target = false + 최근 미노출)
  role          exploration
  review_reason NULL
  context_stage anchor
  sentence      해당 item을 포함한 validated 문장 중 그 사용자에게 아직
                노출되지 않은 것, sentences.id ASC

new
  target item   is_active_learning_target = true 이면서
                invalidated_at IS NULL 인 item_exposures가 아직 0건인 item
                (= 아직 한 번도 target으로 제시되지 않았다.
                 incidental click 승격 경로. 02_LEARNING_POLICY.md)
  role          new
  review_reason NULL
  context_stage anchor
  sentence      아래 `stage → sentence` 표의 `anchor` 행과 같다
                (승격 시점에 기록된 anchor_sentence_id가 있으면 그 문장)

review
  target item   review_states 행이 있고
                invalidated_at IS NULL 인 item_exposures가 1건 이상인 item
                (0건이면 위 `new`가 가져간다 --- 그 item의 첫 제시는 new다)
  role          review
  review_reason 아래 표
  context_stage 아래 표
  sentence      아래 `stage → sentence` 표
```

`new`를 "아직 `review_states` 행이 없는 item"으로 정의하던 서술은
**철회한다.** `07_SRS_SPEC.md`의 `몰랐음 -> Again`은 explicit signal을 즉시
FSRS에 기록하므로 승격시킨 바로 그 self-report가 `review_states` 행을 만들고,
그 정의의 집합은 **항상 공집합**이었다. 그러면 Category Mix의 new 축이 영구히
굶는다. 두 조항 중 FSRS mapping이 더 핵심적이고 `12_TEST_PLAN.md`의 Core E2E
7단계가 그 동작을 검증하므로, 고치는 쪽은 `new`의 정의다.

새 기준은 **"이미 target으로 제시된 적이 있는가"**이고 판정 소스는 이 엔진의
다른 모든 노출 판정과 같은 `item_exposures`다. target이 아닌 item의
self-report는 exposure를 만들지 않으므로(`07_SRS_SPEC.md`의
`target item의 canonical 정의`) 승격 직후의 item은 exposure 0건이고, 첫 `new`
presentation이 닫히면 1건이 되어 그 다음부터 `review`다. 이 조건으로 `new`와
`review`는 배타적이며, `exploration`과는 `is_active_learning_target`으로
갈린다.

문장당 target item 수는 `max_new_items_per_sentence` 이하여야 한다
(`14_CONFIGURATION.md`). 한 문장에 붙일 대상이 상한보다 많으면 **상한까지만
붙이고 나머지 item을 그 문장에 싣지 않는다. 문장 자체를 버리지 않는다.**

-   붙는 순서는 위 role별 대상 item 선정 순서이므로 결정론적이다. 이미
    붙은 target을 유지하고 초과분만 버린다.
-   실리지 못한 item은 같은 실행의 다른 문장이나 다음 실행에서 자기
    candidate를 얻는다. 문장을 버리면 이미 만든 candidate를 되돌려야
    하고, 그 item 때문에 멀쩡한 문장 하나가 통째로 사라진다.
-   `08_LLM_SPEC.md`의 `Deterministic Content Validation` 5번(전체 target
    수. 신규 수는 10번)은 **생성 시점**의 검사다. 이 규칙은 이미 validated인
    문장에 target을 붙이는 **materialization 시점**에 적용된다. 둘은 같은
    config 키를 쓰지만 적용 지점이 다르다.

Cold start에서는 `user_item_learning_state` 행이 없으므로 new와 review
pool이 비고 **exploration만 생긴다.** 이는 Cold Start 절의 "Category
pool이 없으면 available category만 사용한다"와 일치하며, 사용자가 첫
`몰랐음`/`애매함`을 누르는 순간 그 item이 active learning target이 되고
review_states가 생겨 pool이 자라기 시작한다. 어느 pool로 가는지는 그 item이
그 presentation의 target이었는지로 갈린다.

``` text
target item에 self-report      그 presentation이 닫히며 exposure 1건 -> review pool
target이 아닌 item에 self-report  exposure 0건                        -> new pool
```

신규 사용자에게 review 70%를 강제로 만들지 않는다.

### review candidate: reason 판정

review candidate도 **Wave 2의 materialization이 만든다.** Wave 3 job이
아니다. 이것이 없으면 `12_TEST_PLAN.md`의 Core E2E 9~12단계(due 시점
이동 → review 문장 노출 → exposure 누적 → 새 문맥 재노출)와 Regression
Scenario A~D를 Wave 2에서 재현할 수 없다.

**한 materialization 실행 안에서** 한 item에 대해 review candidate를 두 개
이상 만들지 않는다. 아래를 위에서부터 평가해 처음 만족하는 reason 하나로
정한다. 평가 순서는 `Review Reason 선택`의 우선순위와 같다. 이 제약의 범위는
아래 `이 제약의 범위`가 정한다.

``` text
1. context_repair
   a. 해당 item이 **target이었던** presentation 중 가장 최근 explicit `몰랐음`
      event(self_report_unknown | mastery_probe_unknown)가 붙은 것을 찾아
      그 presentation의 context_stage를 S_fail이라 한다
      판정 소스는 그 (presentation, item)의 invalidated_at IS NULL 인
      item_exposures row다 --- 그 row가 없으면 실패로 보지 않는다
   b. user_item_learning_state.context_stage < S_fail  (실패 후 한 단계 내려감)
   c. 그 이후로 현재 stage의 invalidated_at IS NULL 인 item_exposures row가
      아직 없다                                        (되돌린 노출이 아직 안 일어남)

2. fsrs_due
   review_states.next_review_at <= now
   AND (deferred_until IS NULL OR deferred_until <= now)

3. reinforcement
   review_states 행이 있고
   해당 item의 invalidated_at IS NULL 인 item_exposures 건수
     < minimum_meaningful_exposures

위 셋 중 어느 것도 만족하지 않으면 그 item의 review candidate를 만들지 않는다.
```

reason을 하나로 좁히는 이유는 `04_DB_SPEC.md`의 유일성 규칙이
`(user_id, sentence_id, presentation_role, context_stage)`이기 때문이다.
같은 item·같은 stage에 두 reason의 candidate를 만들면 대개 같은 문장을
고르게 되어 두 번째가 충돌한다. **어느 reason을 실제로 보여줄지를
정하는 것은 `Review Reason 선택`이고**, materialization은 그 선택이
작동할 재료를 만들 뿐이다. `reinforcement_min_share_of_review`는 그
선택 단계에서 적용된다.

stage 비교는 `anchor < near_original < varied < new_context` ladder를
쓴다. 조건 1-c와 조건 3을 포함해 **이 엔진의 모든 노출 판정 소스는
`item_exposures`의 `invalidated_at IS NULL` 건수**이며, denormalized
cache인 `review_states.meaningful_exposure_count`를 판정에 쓰지 않는다.
cache를 읽어도 되는 조건은 `07_SRS_SPEC.md`의 `Meaningful Exposure
정의`가 canonical이다. content flag로 무효화된 노출이 cache에 언제
반영되는지는 재계산 시점에 달렸고, 그 시차가 그대로 reinforcement 판정을
흔든다.

`context_repair`는 **새 상태 컬럼 없이** 위 세 조건으로 판정한다. 되돌린
문맥의 노출이 실제로 일어나면 조건 1-c가 자동으로 거짓이 되므로
"repair를 아직 했는가"를 따로 저장할 필요가 없다.

조건 1-a가 `item_exposures`를 거치는 이유는 둘이다.

-   target이 아닌 item을 눌러 `몰랐음`을 고른 경우 그 presentation의
    `context_stage`는 **다른 item을 위해 고른 값**이다. 그것을 S_fail로 쓰면
    최초로 만난 item이 곧바로 `new_context` 실패로 기록된다
    (`07_SRS_SPEC.md`의 `target item의 canonical 정의`).
-   flag/quarantine으로 무효화된 노출에서 나온 negative evidence는 repair를
    유발하지 않아야 한다(`10_ERROR_HANDLING.md`). `invalidated_at IS NULL`
    조건이 그것을 그대로 처리한다.

조건 1-b가 성립하려면 stage가 실제로 내려가야 한다. **그 하강은
`07_SRS_SPEC.md`의 `전이 규칙`이 수행하며 이 문서는 결과만 읽는다.**

#### 이 제약의 범위 (MVP 확정)

"한 item에 review candidate를 두 개 이상 만들지 않는다"가 덮는 범위는 **한
번의 materialization 실행**이다. "그 item에 살아 있는 review candidate가 전부
합쳐 하나"라는 뜻이 아니다.

``` text
보장한다        한 실행에서 item당 review candidate 최대 1개 (reason 하나)
보장하지 않는다  서로 다른 실행이 만든 candidate가 동시에 존재하지 않는 것
```

근거로 든 유일성 규칙(`04_DB_SPEC.md`)이 `status IN ('queued', 'ready')`에만
걸려 있기 때문이다. `shown`이 된 candidate는 그 index 밖이므로, 그 문장이 아직
화면에 열려 있는 동안 다음 실행이 돌면 같은
`(user, sentence, review, stage)` 조합의 두 번째 row가 만들어진다. **이 경로는
실재한다** --- `POST /api/study/session`은 신규와 resume 양쪽에서 위
`실행 시점과 대상`대로 materialization을 1회 실행하므로, 문장이 열린 상태의
새로고침 한 번이 그 상황을 만든다.

**이것은 결함이 아니라 ADR-010이 의도한 것이다.** 그 ADR은
`shown / consumed / quarantined / expired`를 index에서 **일부러** 제외했다 ---
같은 문장을 나중에 다시 candidate로 만들 수 있어야 contextual review가
성립하기 때문이다. 따라서 위 문장을 근거로 index 범위를 `shown`까지 넓히지
않는다. 넓히면 ADR-010이 지키려던 재사용 가능성이 그대로 사라진다.

같은 item에 candidate가 여럿 남았을 때 **무엇을 먼저 보여주는가**는 아래
`Review Ordering`의 `candidate 단위 tie-break`가 정한다.

### review candidate: stage → sentence

``` text
context_stage = user_item_learning_state.context_stage
                (context_repair면 그 값이 이미 한 단계 낮아져 있다)
```

``` text
anchor         user_item_learning_state.anchor_sentence_id
               NULL이면 그 item을 포함한 validated 문장 중 sentences.id ASC
               첫 번째를 고르고 anchor_sentence_id에 기록한다
               기록된 anchor를 더는 쓸 수 없으면 아래 규칙을 따른다
               (지정 규칙 전체의 canonical 정의는 07_SRS_SPEC.md의
                `anchor_sentence_id 지정`이고, 여기 id ASC 선택은 그 2번이다.
                승격 시점에 이미 기록됐으면 그 값을 그대로 쓴다)
near_original  anchor sentence 자신, 또는 parent_sentence_id = anchor 인
               validated 문장
varied         anchor가 아니고 그 사용자에게 아직 노출되지 않은 validated 문장
new_context    varied와 같은 조건
```

**한계:** MVP에는 문장 단위의 "anchor로부터의 거리" 지표가 없다. 따라서
`varied`와 `new_context`의 문장 선택 규칙이 같다. 두 stage의 구분은
문장이 아니라 `user_item_learning_state.context_stage`의 progression
(`07_SRS_SPEC.md`)이 담당한다. 목적에 맞는 문맥을 실제로 **생성**하는
것은 Wave 3의 `GENERATE_REVIEW_CONTEXT`이며, 조건에 맞는 문장이 하나도
없으면 그 stage의 candidate를 만들지 않고 `Pool Fallback`으로 넘어간다.

이때 그 `(item, context_stage)`에 대해 `GENERATE_REVIEW_CONTEXT`를
enqueue한다(payload와 key는 `09_BACKGROUND_JOBS.md`의 표가 canonical).
그 item에 쓸 문장이 **아예 없는** 경우는 이 경로가 아니라 Pool Fallback
3단계의 `GENERATE_SENTENCE_BATCH`가 맡는다. 두 job의 경계는 "문장이
없다"와 "이 stage에 맞는 문장이 없다"이다.

이때 **stage는 그대로 남는다.** 전이는 오직 exposure로만 일어나므로
(`07_SRS_SPEC.md`의 `전이 규칙`) candidate를 만들지 못한 것 자체는 ladder를
움직이지 않고, `Pool Fallback` 2단계가 대신 보여주는 anchor/near-original
reinforcement 노출도 성공하는 한 ladder를 되돌리지 않는다(전이 규칙의
`max`). `new_context`에서 쓸 문장이 떨어진 item은 그 fallback으로 최소 노출을
채우다가, Wave 3이 새 문맥을 공급하면 그대로 `new_context`에서 이어간다.

### anchor 문장을 더는 쓸 수 없을 때

`anchor_sentence_id`가 가리키는 문장이 Ready invariant를 만족하지 않으면
**원인에 따라 다르게 처리한다.** 둘을 같게 다루면 quarantine된 anchor를 가진
item이 `anchor`/`near_original` stage에서 영영 candidate를 얻지 못하고 학습
대상에서 조용히 빠진다.

``` text
sentences.status = quarantined 인 경우
    anchor_sentence_id = NULL 로 되돌리고 위 anchor 규칙으로 재지정한다

그 밖의 이유로 Ready invariant를 만족하지 않는 경우
    재지정하지 않고 그 stage의 candidate를 만들지 않는다
```

quarantine일 때 재지정하는 것이 "몰래 다른 문장으로 바꾸는" 것이 아닌
이유는, flag/quarantine 시점에 **그 문장에서 나온 `item_exposures`가 이미
`invalidated_at`으로 무효화되기 때문이다**(`10_ERROR_HANDLING.md`). 최초
학습 문맥으로서의 기록 자체가 남아 있지 않으므로 보존할 anchor가 없다.

반대로 explanation repair(`EXPLAIN_ITEM`) 대기처럼 **일시적**으로 invariant를
만족하지 못하는 경우에는 재지정하지 않는다. 곧 복구될 문장 때문에 anchor를
바꾸면 같은 item의 학습 문맥이 흔들린다. 이때는 이번 실행에서 그 stage를
건너뛰고 `Pool Fallback`으로 넘어간다.

### Wave 3이 추가하는 것

Wave 3의 worker는 이 절차를 대체하지 않는다. **콘텐츠가 없어서
materialization이 만들 candidate를 못 찾을 때** 새 문장을 생성해
`sentences`를 채우는 것이 worker의 일이다. 생성된 문장은 다음
materialization 실행에서 candidate가 된다. 즉 "누가 candidate를
만드는가"의 답은 Wave 2·3 모두에서 Learning Engine 하나이고, worker는
그 재료를 공급한다.

### 테스트에서의 candidate 구성

integration test와 Regression Scenario A~H는 candidate row를 손으로
INSERT하지 말고 **이 절의 materialization을 실제로 호출해서** Ready
Pool을 만든다. 손으로 넣으면 materialization 규칙이 틀려도 테스트가
통과한다. 선택 함수(Category Mix / Review Reason / Review Ordering)
자체의 unit test는 예외이며 candidate를 직접 구성해도 된다. 검증 대상이
pool 생성이 아니라 pool이 주어졌을 때의 선택이기 때문이다.

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

deficit은 **비교 전에 반올림한다.** `target_ratio * total_presented`는
부동소수점 연산이라 수학적으로 같은 두 deficit이 1e-16만큼 다르게 나온다.
반올림하지 않으면 위 tie-break가 사실상 한 번도 실행되지 않고 category
순서를 부동소수점 오차가 정한다. 반올림 자릿수는 구현 상수이며 학습 정책
값이 아니므로 config에 두지 않는다.

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

위 1\~4는 **item 단위** 순서다. 한 item에 review candidate가 여럿 남아 있을 수
있으므로(위 `이 제약의 범위`) candidate 단위 순서는 아래
`candidate 단위 tie-break`가 이어서 정한다.

세션에서 보여주지 못한 due item은:

-   lapse 처리하지 않는다.
-   실패 처리하지 않는다.
-   그대로 due 상태를 유지한다.

### candidate 단위 tie-break (MVP 확정)

review candidate가 둘 이상 선택 가능할 때의 순서다.

먼저 **"candidate 하나가 item 하나에 속한다"는 전제가 거짓임**을 짚는다. 한
candidate는 target을 `max_new_items_per_sentence`개까지 가지고(위 `role별 규칙`),
그 target들의 `user_item_learning_state.context_stage`는 **서로 다를 수 있다.**
같은 presentation에서 한 target이 explicit `몰랐음`이고 다른 target이 무신호이면
전이 규칙이 target마다 따로 적용되어(`07_SRS_SPEC.md`의 `전이 규칙`) 그 자리에서
갈린다. 우연이 아니라 구조다. 그래서 "candidate의 stage"와 "그 item의 stage"를
비교하려면 **어느 target을 말하는지**를 먼저 정해야 한다.

#### 1\~4를 target이 여럿인 candidate에 적용하는 방법

``` text
usable target      Review Ordering 1번을 만족하는 target.
                   reason이 fsrs_due면 실제로 due인 target만.
candidate의 order key
                   그 candidate의 usable target들의 order key **최소값**
dominant target    그 최소값을 만든 target
                   (order key에 learning_item_id가 들어 있으므로 유일하다)
```

**가장 급한 target이 candidate의 우선순위를 정한다.** candidate는 통째로
제시되므로, 그 안에서 가장 급한 target이 언제 보여야 하는지가 곧 그 candidate가
언제 보여야 하는지다. 최대값이나 평균을 쓰면 급한 target이 덜 급한 동승자 때문에
밀린다.

#### 5\~6

``` text
5. candidate.context_stage == dominant target의
   user_item_learning_state.context_stage 인 candidate를 먼저
6. 그래도 동률이면 stable deterministic tie-break
```

**dominant target으로 판정하는 이유는 5번이 얹히는 자리가 1\~4의 동률이기
때문이다.** 그 동률을 만든 것이 dominant target이므로, 5번이 말하는 "그 item"도
그것이다. 다른 두 해석은 이 문언과 어긋난다.

-   **"아무 target이나 일치하면 통과"로 읽으면 규칙이 무력해진다.** target이
    `{item1: anchor, item2: near_original}`인 낡은 `anchor` candidate는 item1
    때문에 항상 일치로 판정되고, item2가 order key를 지배하는 상황에서도 새
    `near_original` candidate를 candidate id ASC로 이긴다. 이 규칙이 겨냥한 바로
    그 시나리오에서 진다.
-   **"모든 target이 일치해야 통과"로 읽으면 multi-target candidate가 사실상
    배제된다.** 두 target의 ladder가 갈리는 것은 위에서 본 대로 구조적으로
    일어나므로, 그 candidate는 갈린 순간부터 영구히 불리해진다. 배제는 이 규칙이
    하지 않기로 한 것이다(아래).

**배제가 아니라 선호다.** stage가 일치하는 candidate가 하나도 없으면 낮은
stage candidate를 그대로 고른다. 그래서 이 규칙은 `Pool Fallback` 2단계가
의도적으로 허용한 anchor/near-original reinforcement 노출을 막지 않는다 ---
그 단계는 "그런 candidate가 있는가"를 보고, 이 규칙은 "둘 다 있을 때 무엇을
먼저 보는가"만 정한다. 사라지는 것은 "가장 오래된 candidate가 먼저"라는 암묵
순서뿐이다.

규칙이 필요한 이유는 stage가 오른 뒤에도 낮은 stage candidate가 Ready Pool에
남기 때문이다(위 `이 제약의 범위`). 그 candidate가 계속 먼저 뽑히면 minimum
meaningful exposure가 실제 ladder 위치보다 낮은 stage로 기울고, 극단에서는
5회가 거의 같은 anchor 문장으로 채워진다. 그것이 ADR-012가 결함이라 부른
상태다. ladder 자체는 전이 규칙의 `max`가 지키지만(`07_SRS_SPEC.md`),
**무엇을 보여주는가**는 지키지 않는다.

stage **거리**로 정렬하지 않는다(예: "state보다 낮은 것 중 가장 높은 stage").
일치 여부는 `user_item_learning_state` 하나만 읽으면 판정되지만, 거리 정렬은
ladder 위의 우선순위를 새로 정하는 **새 정책**이고 MVP에 그것을 요구하는
조항이 없다.

근거와 버린 대안은 `docs/decisions/ADR-019-stale-review-candidates.md`.

## Probe Pacing

**세션 안에서 probe를 언제 제시하는지의 canonical 정의는 이 절이다.**
probe UI 문구와 대상 우선순위는 `02_LEARNING_POLICY.md`,
budget 수치는 `14_CONFIGURATION.md`를 따른다.

`mastery_probe_target_per_session_min/max`는 세션당 **개수**만 정하고
배치를 정하지 않는다. 상한만 구현하면 세션 앞쪽 네 문장에 probe가
연속으로 붙을 수 있고, 이는 `03_UI_UX_SPEC.md`의 "probe는 세션의 중심
UI가 되어서는 안 된다", `02_LEARNING_POLICY.md`의 "간헐적"과 충돌한다.

`/next`가 presentation을 만들 때 다음을 **모두** 만족하면 그
presentation에 probe를 함께 싣는다. 하나라도 어긋나면 `probe = null`이다.

``` text
1. 이번 세션에서 표시한 probe 수 < mastery_probe_target_per_session_max
2. 간격 조건
     세션에 probe가 아직 없으면
       이번 presentation을 포함해 세션의 presentation 수
         >= probe_min_gap_presentations + 1
     이미 있으면
       마지막 probe 이후 제시된 presentation 수
         >= probe_min_gap_presentations
3. 02_LEARNING_POLICY.md의 `Probe 대상 우선순위`를 만족하고
   cooldown 중이 아닌 후보 item이 이번 presentation의 target 중에 있다
```

결정론적이며 세션 event만으로 재현할 수 있다. 조건 2는 세션의 첫 probe도
`probe_min_gap_presentations`개 뒤로 미루므로 첫 문장부터 probe가 나오지
않는다.

**같은 입력에 같은 답을 주지만 idempotent하지는 않다.** probe를 하나 실으면
`mastery_probe_shown` event가 세션에 남아 다음 호출의 pacing과 제외 집합이
달라진다. 따라서 `열린 presentation 불변식`으로 같은 presentation을 다시
반환하는 경로에서는 **probe를 다시 고르지 않는다.** `05_API_SPEC.md`의
`Mastery Probe`가 정한 `uuid5` 자연키로 기존 event를 조회해 같은 `probe_id`를
반환한다.

### min은 강제하지 않는다

`mastery_probe_target_per_session_min`은 **관측 목표이지 엔진 제약이
아니다.** 후보가 없거나 세션이 짧아 min에 미치지 못해도 그대로 둔다.

-   min을 채우려고 조건 3의 cooldown이나 대상 우선순위를 깨면, 방금
    explicit feedback을 준 item이나 최근 skip한 item을 다시 묻게 된다.
    그렇게 얻은 응답은 evidence로서 가치가 낮고
    `02_LEARNING_POLICY.md`의 `Skip` 규칙과 정면으로 충돌한다.
-   min을 채우려고 조건 2를 깨면 세션 끝에 probe가 몰려
    `03_UI_UX_SPEC.md`의 제약을 어긴다.

따라서 엔진이 강제하는 것은 **max와 간격**뿐이다. min은
`probe_min_gap_presentations`를 조정할 때의 기준값이고, 실사용에서 probe가
너무 드물면 gap을 줄인다. `13_ACCEPTANCE_CRITERIA.md`의 "configured probe
budget과 cooldown을 따른다"가 검증하는 것도 max와 cooldown이다.

연속 skip 시 세션 probe budget을 줄이는 동작은 **MVP에서 구현하지
않는다.** 같은 item을 다시 묻지 않는 것은 `probe_skip_cooldown_days`가
item 단위로 이미 보장하고, 세션 단위 budget 축소는 그 위에 추가 상태를
요구한다.

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
2. 없으면 learning_items.metadata_json.seed_order (정수, seed 적재 순서)
3. 둘 다 없으면 없음으로 취급하고 정렬 맨 뒤
```

두 값은 의미가 다르므로 같은 숫자 공간에서 섞어 비교하지 않는다. 정렬은
다음 tuple을 ASC로 비교한다.

``` text
frequency_key =
    (0, metadata_json.frequency_rank)  frequency_rank가 정수면
    (1, metadata_json.seed_order)      아니고 seed_order가 정수면
    (2, 0)                             둘 다 없으면
```

`frequency_rank`와 `seed_order`는 모두 기존 `learning_items.metadata_json`에
담는다. **`learning_items`에 컬럼을 추가하지 않는다**(`04_DB_SPEC.md`).

### seed_order (seed loader 규약)

`seed_order`는 seed loader가 적재 시점에 채운다.

``` text
값     1부터 1씩 증가하는 정수
순서   seed 파일명 오름차순 -> 파일 내 행 순서
대상   origin = seed 로 적재되는 learning_item 전부
```

-   seed 파일이 `frequency_rank`를 들고 오면 그대로
    `metadata_json.frequency_rank`에 싣는다. 없더라도 **`seed_order`를
    `frequency_rank`로 승격시키지 않는다.** 하나는 언어 빈도이고 다른
    하나는 파일 위치다. 둘을 한 키에 섞으면 명시적 빈도값과 줄 번호가
    같은 척도에서 비교된다.
-   seed는 Git으로 관리되므로 같은 파일 집합은 항상 같은 `seed_order`를
    만든다. 재적재해도 값이 바뀌지 않는다.
-   **`learning_items.id`를 이 자리에 쓰지 않는다.** 쓰면 2단계가 3단계
    tie-break(`learning_item_id ASC`)와 같은 기준이 되어 3단 규칙이 2단으로
    붕괴한다. 게다가 generated item이 사이사이에 id를 받으므로 id 순서는
    "seed 파일 순서"가 아니다.

**한계:** `origin = generated` item에는 frequency 정보가 없다. 따라서
빈도 정렬은 사실상 seed item에만 적용되고, generated item은 같은
difficulty_distance 안에서 seed item 뒤에 놓인 뒤 `learning_item_id`로만
정렬된다. 코퍼스 기반 frequency는 MVP 범위가 아니다.

다만 **MVP에는 `origin = generated` item을 만드는 경로가 없으므로**(worker는
요청에 실어 보낸 item만 annotate한다. `08_LLM_SPEC.md`의
`worker가 만들지 않는 것`) 이 한계가 실제로 발생하지는 않는다. 규칙은 그런
item이 생기는 시점에도 정렬이 결정론적이도록 그대로 남긴다.

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
-   초기 세션은 **review가 아닌 category로** 시작하고, Review pool이
    생기면 configured ratio로 점진적으로 수렴한다. 첫 세션에는
    `user_item_learning_state` 행이 없어 실제로는 **exploration만**
    생긴다. 사용자가 첫 `몰랐음`/`애매함`을 누르면 그 item이 active
    learning target이 되고 `review_states`가 생겨 new/review pool이
    자라기 시작한다. 두 pool 중 어디로 가는지는 그 item이 그 presentation의
    target이었는지로 갈린다(`Candidate Materialization`의 `role별 규칙`).

초기 학습 item 공급을 위해 **작은 version-controlled starter seed
set**을 둔다.

-   초급 사용자의 첫 몇 세션을 시작할 수 있게 하는 것이 목적이다.
-   everyday high-frequency word/grammar/expression 중심.
-   정확한 개수는 제품 명세에 고정하지 않는다.

seed data 요구사항은 `04_DB_SPEC.md`의 Seed Data 절을 따른다. 초기 세션의
exploration 대상 선정은 위 `Exploration Item 선정` 절을 따른다.

## Pool Fallback

선택 대상 category의 Ready candidate가 없으면 다음 순서로 처리한다.
**이 순서가 canonical이며 다른 문서는 여기를 참조한다.**

``` text
0. Candidate Materialization 1회 실행 (LLM 호출 없음)
1. 같은 deficit 순서로 available category를 다시 훑는다
   (0단계가 방금 채웠을 수 있으므로 처음 고른 category부터 다시 본다)
2. 안전한 기존 anchor/near-original reinforcement candidate 사용
3. background replenishment job enqueue
```

0단계가 먼저인 이유는 "Ready candidate가 없다"가 대부분 **콘텐츠가
없다**가 아니라 **아직 이 사용자에게 투영되지 않았다**이기 때문이다.
다른 category로 먼저 내려가면 아직 만들 수 있었던 문장을 두고 Category
Mix가 틀어진다.

0단계는 **요청당 1회**다. 1단계를 훑고도 비어 있다고 해서 0단계로
돌아가지 않는다. 3단계(job enqueue)는 0단계를 돌려도 만들 candidate가
없을 때, 즉 정말로 콘텐츠가 없을 때만 의미가 있다.

3단계가 enqueue하는 job_type은 role과 무관하게 `GENERATE_SENTENCE_BATCH`
하나이고 payload는 `{user_id, presentation_role}`뿐이다. **item 목록을
싣지 않는다** --- idempotency key가 하루 창이라 그날 첫 job의 payload가
그대로 고정되어 실행 시점에는 이미 낡는다. worker가 실행 시점에 대상을
다시 계산한다(`08_LLM_SPEC.md`의 `GENERATE_SENTENCE_BATCH 대상 선정`,
key/payload 표는 `09_BACKGROUND_JOBS.md`).

세션을 LLM 응답 대기로 block하지 않는다. **모든 pool이 비어도 API
request handler에서 provider를 synchronous 호출하지 않는다**
(`08_LLM_SPEC.md`의 LLM 호출 경계).

사용자에게는 짧은 안내만 표시하고 무한 spinner를 보여주지 않는다
(`10_ERROR_HANDLING.md`).
