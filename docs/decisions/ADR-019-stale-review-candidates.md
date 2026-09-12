# ADR-019 --- 낡은 review candidate를 어떻게 다루는가

Status: Accepted

Decision: `user_item_learning_state.context_stage`가 오른 뒤에도 Ready Pool에
남아 있는 **낮은 stage의 review candidate를 만료시키지도 배제하지도 않는다.**
같은 item에 candidate가 여럿 선택 가능할 때 **state의 현재 `context_stage`와
일치하는 것을 먼저 고르는 tie-break**만 추가한다.

canonical 정의는 `spec/mvp-01-core/06_LEARNING_ENGINE.md`의 `Review Ordering`
→ `candidate 단위 tie-break`다.

``` text
5. candidate.context_stage == dominant target의
   user_item_learning_state.context_stage 인 candidate를 먼저
6. 그래도 동률이면 stable deterministic tie-break

dominant target = 그 candidate의 usable target 중 order key가 최소인 target
                  (= Review Ordering 1~4의 동률을 만든 그 target)
```

`dominant target`이 필요한 이유는 **한 candidate가 target을 둘까지 가질 수 있고
그 target들의 `context_stage`가 갈릴 수 있기** 때문이다. 같은 presentation에서
한 target이 explicit `몰랐음`이고 다른 target이 무신호이면 전이 규칙이 target마다
따로 적용되어 그 자리에서 갈린다. "아무 target이나 일치하면 통과"로 읽으면 낡은
`anchor` candidate가 동승자 덕분에 항상 일치로 판정되어 이 결정이 무력해지고,
"모든 target이 일치해야 통과"로 읽으면 multi-target candidate가 사실상 배제된다.
5번이 얹히는 자리가 1~4의 동률이므로 그 동률을 만든 target이 판정 대상이다.

따라오는 두 결정:

-   `user_sentence_candidates.status = expired`는 **MVP에서 쓰지 않는다.**
    값과 partial unique index 조건은 남기고 쓰지 않는 것을 명시한다
    (`spec/mvp-01-core/04_DB_SPEC.md`의 `user_sentence_candidates`).
-   `06_LEARNING_ENGINE.md`의 "동시에 두 개 이상의 review candidate를 만들지
    않는다"의 범위는 **한 materialization 실행**이다. 살아 있는 candidate
    전체가 아니다(같은 문서의 `이 제약의 범위`).

**새 컬럼도 새 config 키도 새 테이블도 만들지 않는다.**

## 문제

Wave 4 게이트에서 candidate 수명에 관한 공백 세 건이 드러났다. 셋은 같은
메커니즘의 다른 면이다.

**(1) 중복 candidate가 정상적으로 생긴다.** materialization은 그 시점의
`state.context_stage`로 candidate를 만들고 이미 만들어 둔 candidate를 다시 보지
않는다. 유일성 index는 `status IN ('queued', 'ready')`만 덮으므로 candidate가
`shown`인 동안 materialization이 돌면 같은
`(user, sentence, review, stage)` 조합의 두 번째 행이 만들어진다. 그 경로는
실재한다 --- `POST /api/study/session`은 신규와 resume 양쪽에서 명세대로
materialization을 1회 실행하고, 브라우저는 문장이 열린 상태에서 그 endpoint를
부른다. **문장 도중 새로고침 한 번이 중복 candidate를 만든다.**

**(2) 낡은 쪽이 우선된다.** 같은 item의 두 candidate는 `order_key`가 같고
tie-break가 candidate id ASC이므로 **더 오래된 candidate**가 선택된다. stage가
오른 뒤에도 낮은 stage candidate가 먼저 뽑힌다.

**(3) `expired`에 writer가 없다.** `04_DB_SPEC.md`에 값만 있고 쓰는 주체·시점이
어느 문서에도 없었다. stage가 오른 뒤 하위 stage의 `ready` candidate를 어떻게
할지 규정도 없었다.

(1)과 (2)는 **명세 위반이 아니다.** `07_SRS_SPEC.md`의 `전이 규칙`과 ADR-012의
근거 (4)가 "Ready Pool에 남아 있던 낮은 stage candidate"를 명시적으로 전제하고,
`max`/`min`이 그래서 존재한다. 최소 노출 정의도 "단순 횟수"이지 "서로 다른
문맥"이 아니다(`07_SRS_SPEC.md`의 `Meaningful Exposure 정의`).

그러나 (2)는 ADR-012가 **결함이라 부른 상태** --- "최소 5회 meaningful exposure가
전부 동일한 anchor 문장으로 채워진다" --- 로 증폭하는 방향이다. 낮은 stage
candidate가 쌓일수록 실제 노출이 ladder 위치보다 낮은 stage로 기운다.

## 버린 대안

**(a) stage 상승 시 하위 stage candidate를 `expired`로 만료시킨다.** `expired`에
첫 writer가 생기는 유일한 안이다. 버린 이유는 `Pool Fallback` 2단계가
**의도적으로** anchor/near-original reinforcement를 보여주기 때문이다. 만료
규칙을 두면 그 fallback을 예외로 파야 하고, "언제 만료시키고 언제 예외인가"는
기존 조항의 해석이 아니라 **새 정책**이다. stage가 다시 내려가는 경로
(`context_repair`)가 있으므로 만료한 candidate를 곧 다시 만들게 되는 경우도
생긴다.

**(b) 선택 단계에서 stage 불일치 candidate를 배제한다.** 만료보다 가볍지만
같은 문제를 갖는다. `Pool Fallback` 2단계가 **명시적으로 허용한** 노출을 일반
규칙으로 막게 되고, 그러면 fallback이 쓸 수 있는 candidate를 앞 단계가 먼저
지워 버린 상태가 된다.

**(c) 유일성 index를 `shown`까지 넓혀 (1)을 원천 차단한다.** ADR-010이
`shown / consumed / quarantined / expired`를 **일부러** 제외한 것을 되돌린다.
제외의 이유는 같은 문장을 나중에 다시 candidate로 만들 수 있어야 contextual
review가 성립한다는 것이고, 그것은 지금도 유효하다.

**(d) 아무것도 하지 않는다(현행 유지).** ladder는 되돌지 않고 노출 카운트도
정확하므로 명세 위반은 없다. 그러나 (2)의 기울기를 그대로 둔다. 중복이 쌓이는
입력(문장 도중 새로고침)이 평범한 사용자 동작이므로 실사용에서 반복된다.

## 근거

-   **(2)만 고치면 충분하다.** 문제는 낮은 stage candidate의 *존재*가 아니라
    그것이 *먼저* 뽑히는 것이다. 존재는 ADR-012가 이미 전제하고 `max`로
    처리했다. 존재를 지우는 (a)·(b)는 명세가 허용한 것을 막는 쪽으로 넘어간다.
-   **tie-break는 배제가 아니므로 `Pool Fallback` 2단계와 충돌하지 않는다.**
    2단계는 "그런 candidate가 있는가"를 보고, 이 규칙은 "둘 다 있을 때 무엇을
    먼저 보는가"만 정한다. 일치하는 candidate가 없으면 낮은 stage candidate가
    그대로 선택된다. 사라지는 것은 "가장 오래된 candidate가 먼저"라는 암묵
    순서뿐이고, 그 순서를 요구하는 조항은 어디에도 없다.
-   **`context_repair`와도 정합한다.** repair candidate는 이미 한 단계 내려간
    `state.context_stage`로 만들어지므로 이 tie-break가 선호하는 쪽이 곧 repair
    candidate다. reason 선택이 먼저 일어나므로(`Review Reason 선택`) 서로 다른
    reason이 이 tie-break로 뒤집히지도 않는다.
-   **새 상태가 필요 없다.** 판정에 필요한 것은 `user_item_learning_state`
    한 행이고 그것은 이미 `stage → sentence`가 읽는 값이다.
-   **비용은 라운드 한 번이다.** 일치하는 candidate가 없는 동안은 낮은 stage
    문장이 한 번 지나가고, 그 노출도 `max` 아래에서 ladder를 되돌리지 않으며
    최소 노출 1회로 정상 계상된다.

## 한계

-   stage **거리**로 정렬하지 않는다. `state = new_context`이고 candidate가
    `anchor`와 `varied`뿐이면 둘 중 무엇이 먼저인지는 기존 tie-break가 정하며,
    `varied`가 더 가깝다는 사실은 쓰이지 않는다. 거리 정렬은 ladder 위의
    우선순위를 새로 정하는 새 정책이고 MVP에 그것을 요구하는 조항이 없다.
-   중복 candidate 자체는 계속 생긴다. Ready Pool에 같은 문장의 행이 여러 개
    남는 것을 그대로 허용한다. 회수 경로는 소비(`shown` → `consumed`)뿐이고,
    소비되지 않은 낡은 행은 남는다. 사용자 1명 규모에서 그 누적이 문제가 되는
    수준이 아니라고 판단했다. 문제가 되는 시점이 오면 그때 `expired`가
    유효해지고(수명 정책), 이 ADR을 고친다.
-   `expired`는 값만 있고 쓰이지 않는 상태로 남는다. `queued`와 같은 처지이며
    같은 방식으로 처리했다 --- 지우지 않고, 쓰지 않는다는 것과 언제 유효해지는지를
    `04_DB_SPEC.md`에 적었다.
