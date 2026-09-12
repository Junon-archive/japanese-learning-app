# ADR-013 --- target item의 정의와 `new` role의 재정의

Status: Accepted

Decision: 두 정의를 함께 고정한다.

``` text
target item (meaningful exposure 조건 1)
    그 presentation의 user_sentence_candidate_targets row.
    materialization 시점에 고정된다. 화면의 tappable item 전체가 아니다.
    canonical: 07_SRS_SPEC.md의 `target item의 canonical 정의`

new role (candidate materialization)
    is_active_learning_target = true 이면서
    invalidated_at IS NULL 인 item_exposures가 0건인 item
    canonical: 06_LEARNING_ENGINE.md의 `role별 규칙`
```

target이 아닌 item에 대한 explicit evidence는 mastery와 FSRS에 **그대로**
기록하되 exposure를 만들지 않고, `context_stage` 전이와 `context_repair`
판정에도 쓰지 않는다. 대신 그 self-report가 승격을 일으킬 때
`anchor_sentence_id`에 **그 문장**을 기록한다.

`review` role은 `review_states` 행이 있으면서 exposure가 1건 이상인 item으로
좁힌다. 새 테이블·새 컬럼·새 config 키는 없다.

## 문제

**(1) `new` pool이 항상 비었다.** `06_LEARNING_ENGINE.md`는 `new`를
"`is_active_learning_target = true`이면서 아직 `review_states` 행이 없는
item"으로 정의했는데, `07_SRS_SPEC.md`의 `몰랐음 -> Again`을 따르는 구현은
승격시킨 그 self-report에서 곧바로 `review_states`를 만든다. 그 집합은
**공집합**이다. 세션을 끝까지 돌려도 `presentation_role = new` candidate가
0건이었고, Category Mix 세 축 중 하나가 영구히 공급되지 않았다.

**(2) 승격된 incidental item이 그 presentation의 exposure를 받지 못했다.**
`max_new_items_per_sentence`로 잘린 세 번째 item을 눌러 `몰랐음`까지 해도
exposure는 0건이다. exposure 대상이 materialization 시점에 고정된 candidate
target이기 때문이다. `07_SRS_SPEC.md`의 "target item이 포함된 sentence"를
"문장의 모든 item"으로 읽으면 해결되지만, 그 독법은 같은 문서의 "단순히 스쳐
지나간 것을 모두 exposure로 세지 않는다"와 충돌한다.

두 문제는 같은 정의에 걸려 있다. **"target"을 넓히면 (2)는 풀리지만 (1)이
더 나빠진다** --- 승격 즉시 exposure가 생기므로 "아직 제시되지 않은 item"이라는
기준 자체가 쓸 수 없게 된다.

## 결정의 근거

**(A) 충돌하는 두 조항 중 `new`의 정의를 고친다.** `몰랐음 -> Again`은 SRS의
핵심 mapping이고 `12_TEST_PLAN.md`의 Core E2E 7단계가 그 동작을 검증한다.
`new`의 정의는 "이 item이 사용자에게 신규인가"를 표현하려던 것이고, 그 의도는
`review_states` 유무가 아니라 **"아직 target으로 제시된 적이 없는가"**로도
--- 오히려 더 정확하게 --- 표현된다.

**(B) 판정 소스를 `item_exposures`로 통일한다.** 이 엔진의 다른 모든 노출
판정(reinforcement, exploration 후보 조건, context_repair)이 이미
`invalidated_at IS NULL` 건수를 쓴다(`ADR-C-2` 계열 결정, `07_SRS_SPEC.md`).
`new` 판정만 다른 소스를 쓸 이유가 없다.

**(C) target을 좁게 유지하는 것이 exposure의 의미를 지킨다.** exposure는
"엔진이 그 item을 위해 고른 문맥을 몇 번 경험했는가"다. 문장의 모든 item을
세면 tappable이 10개인 문장 하나가 9개 item에 공짜 노출을 준다.

**(D) 잃어버리는 문맥이 없다.** 좁은 정의의 유일한 손실은 "사용자가 가장
진하게 학습한 최초 문맥이 5회 카운트에서 빠진다"였다. 승격 시점에
`anchor_sentence_id`를 그 문장으로 기록하면, 그 item의 첫 `new` presentation이
**같은 문장**을 anchor로 다시 제시한다. 최초 문맥은 정상적으로 1회 계상되고
시점만 한 presentation 뒤로 밀린다. 게다가 이때의 재제시는 그냥 반복이 아니라
"이제 target으로서 설명·probe 대상이 되는" 제시다.

**(E) 두 정의가 서로를 성립시킨다.** target을 좁게 두기 때문에 승격 직후
exposure가 0건이고, 그래서 `new` pool이 비지 않는다. 넓게 두면 `new`를
"candidate target row가 없는 item"으로 정의할 수밖에 없는데, 그 기준은
candidate를 만든 순간 꺼지므로 **제시되지 않은 stale candidate**가 남고 같은
문장이 `new`와 `review`로 두 번 만들어질 수 있다.

## 버린 대안

**(a) `몰랐음 -> Again`을 incidental item에 한해 유예한다.** `new` 정의를
그대로 두는 유일한 길이다. 그러나 사용자가 명시적으로 "모른다"고 말한 증거를
버리게 되고, 그 item의 첫 `new` presentation이 무신호로 끝나면 `review_states`가
영영 생기지 않아 **새로운 굶주림**이 생긴다. `07_SRS_SPEC.md`의 mapping에
예외를 만드는 비용도 크다.

**(b) target을 "문장의 모든 tappable item"으로 넓힌다.** (2)만 보면 자연스럽지만
`07_SRS_SPEC.md`의 "스쳐 지나간 것을 모두 세지 않는다"와 정면 충돌하고, (1)을
악화시킨다((E) 참조).

**(c) target을 "candidate target ∪ explicit evidence를 준 item"으로 넓힌다.**
스쳐 지나간 것은 세지 않으므로 (2)에 대한 합리적인 답이다. 그러나 exposure의
`context_stage`가 **다른 item을 위해 고른 값**이 되어 최초로 만난 item이
곧바로 `new_context` 실패로 기록되고(ADR-012), `new` pool은 다시 빈다.
그 대가로 얻는 것은 "한 presentation 빨리 세어진다"뿐이다((D)).

## 한계

-   `user_sentence_candidate_targets.is_new_item`("review_states 행이 없으면
    true")은 이 결정으로 의미가 좁아진다. 실사용처가 없으므로 이번에는 손대지
    않는다. UI가 이 값을 쓰게 되면 그때 `new` role 정의에 맞춘다.
-   `new` candidate가 제시되지 않은 채 세션이 끝나면 그 item은 exposure 0건인
    채로 남아 다음 세션에서도 `new`다. 의도된 동작이다.
-   승격 시점의 `anchor_sentence_id` 기록으로 anchor 쓰기 지점이 둘이 된다
    (승격 / materialization). 둘 다 **NULL일 때만** 쓰고, quarantine 재지정은
    여전히 `06_LEARNING_ENGINE.md`의 규칙 한 곳이 소유한다.
