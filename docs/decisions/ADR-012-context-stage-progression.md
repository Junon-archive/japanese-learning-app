# ADR-012 --- context_stage 전이 규칙

Status: Accepted

Decision: `user_item_learning_state.context_stage`의 전이는
**presentation을 닫는 시점에 meaningful exposure와 같은 트랜잭션에서**
일어난다. canonical 정의는 `spec/mvp-01-core/07_SRS_SPEC.md`의
`Context Progression` → `전이 규칙`이다.

``` text
대상    그 presentation에서 exposure가 기록된 item (= candidate target item)
S_shown 그 presentation의 context_stage
S_cur   user_item_learning_state.context_stage

explicit `몰랐음`(self_report_unknown | mastery_probe_unknown)이 있으면
        S_cur <- min(S_cur, one_step_down(S_shown))   # 바닥 anchor
아니면  S_cur <- max(S_cur, one_step_up(S_shown))     # 천장 new_context
```

`07_SRS_SPEC.md`의 `New-context Failure`가 말하는 "한 단계 쉬운 context"는
**stage 하강**을 뜻한다. 같은 stage 안에서 다른 문장을 고르는 것이 아니다.

**새 컬럼도 새 config 키도 만들지 않는다.** "config로 조정 가능하다"던 v0.2
서술은 철회한다.

## 문제

Wave 2 검증에서 `context_stage`가 **행 생성 시 `anchor` 대입 외에는 어디서도
바뀌지 않는다**는 사실이 드러났다. 같은 item에 미노출 validated 문장 6개를
두고 8라운드를 돌려도 stage는 계속 `anchor`, 제시 문장은 계속 같은 한
문장이었다.

결과:

-   최소 5회 meaningful exposure가 **전부 동일한 anchor 문장**으로 채워진다.
    `01_PRODUCT_PRINCIPLES.md` #6, `02_LEARNING_POLICY.md`의 `Exposure`,
    `07_SRS_SPEC.md`가 모두 요구하는 contextual repetition이 성립하지 않는다.
-   `06_LEARNING_ENGINE.md`의 `near_original` / `varied` / `new_context`
    분기가 프로덕션에서 한 번도 실행되지 않는다. Wave 3 생성기를 붙여도
    호출되지 않는다.
-   `context_repair`의 조건 b(`context_stage < S_fail`)가 영원히 거짓이라
    reason 우선순위 1번이 도달 불가능하다.

구현자가 이 전이를 만들지 않은 것은 지시를 따른 결과다. `07_SRS_SPEC.md`의
progression 표는 stage마다 `또는`을 달고 있었고 **누가 언제 바꾸는지**가
없었다. 즉 "기본 정책"이라는 문장은 있었지만 실행 가능한 규칙이 아니었다.

## 결정의 근거

**(1) "또는"은 실패 여부였다.** 표를 그대로 두고 실패 없는 경로를 따라가면
`anchor → near_original → varied → new_context → new_context`가 되어
`任せる` 예시와 정확히 일치한다. `Exposure 2 -> anchor 또는 near_original`은
"첫 문맥에서 실패했으면 같은 anchor를 한 번 더, 아니면 다음 칸"으로 읽힌다.
따라서 이 규칙은 표를 대체하는 새 정책이 아니라 표의 결정론적 해석이다.

**(2) 단위는 signal이 아니라 exposure다.** 표의 좌변이 `Exposure N`이므로
무신호 노출도 ladder를 올린다. 내리는 것은 `07_SRS_SPEC.md`가 실패라고 부르는
explicit `몰랐음` 하나뿐이다. 규칙이 두 갈래를 넘지 않게 유지했다.

**(3) 시점은 exposure 확정 시점이어야 한다.** 노출 횟수를 세는 자리와 ladder를
움직이는 자리가 다르면 두 값이 어긋난다. 같은 트랜잭션·같은 idempotency
guard(`completed_at`)를 공유하므로 재시도가 ladder를 두 번 밀지 않고,
quarantined content는 exposure를 만들지 않으므로 ladder도 움직이지 않는다.

**(4) `max` / `min`이 필요하다.** Ready Pool에는 stage가 낮은 candidate가
남아 있을 수 있고, `Pool Fallback` 2단계는 의도적으로 anchor reinforcement를
보여준다. 이때 `S_shown + 1`을 그대로 대입하면 `new_context`까지 간 item이
anchor 노출 한 번에 `near_original`로 내려간다. 반대로 실패는 **실제로 본
문맥**을 기준으로 내려가야 하므로 `min(S_cur, down(S_shown))`이다.

**(5) 전이는 candidate target에만 적용한다.** 다른 item을 위해 고른 문맥의
stage가 이 item의 ladder를 움직이면 progression이 자기 노출 이력과 무관해진다
(`ADR-013`).

## 버린 대안

**(a) stage를 저장하지 않고 exposure 수에서 매번 계산한다.**
`stage = ladder[min(n, 3)]`. 전이 코드가 없어지지만 **하강을 표현할 수 없다.**
`context_repair`가 영원히 도달 불가능한 채로 남고, `07_SRS_SPEC.md`의
`New-context Failure`가 사문이 된다.

**(b) `exposures_per_context_stage` 같은 임계값 config 키를 만든다.**
`07_SRS_SPEC.md`의 "config로 조정 가능하다"를 문자 그대로 실현하는 안이다.
그러려면 *현재 stage에서 몇 번 노출했는가*를 알아야 하는데, 하강이 있는 이상
`item_exposures`의 stage별 건수로는 복원되지 않는다(되돌아온 stage의 옛 노출이
그대로 다시 세어져 즉시 재승급한다). 직전 stage 변경 시각이나 stage별 카운터를
저장할 **새 컬럼**이 필요하고, 이는 MVP 제약을 넘는다. 4단 ladder에 키 4개를
만드는 안은 조정 여지보다 검증 부담이 크다.

**(c) `애매함`을 별도 분기(hold)로 둔다.** 세 번째 갈래가 생기고,
`02_LEARNING_POLICY.md`가 `애매함`을 "중간 evidence"로만 규정한 상태에서
"중간이면 제자리"라는 새 정책을 발명하게 된다. 필요성이 실사용에서 드러나면
그때 이 ADR을 고친다.

## 한계

-   사용자가 매번 `몰랐음`을 누르면 stage는 `anchor`에 머물고 같은 문장이
    반복된다. 이는 전이 규칙의 부재가 아니라 증거에 따른 결과이며, 한 번이라도
    다른 응답이 나오면 즉시 ladder를 오른다. anchor보다 쉬운 문맥은 MVP에 없다.
-   `varied`와 `new_context`의 문장 선택 규칙은 여전히 같다
    (`06_LEARNING_ENGINE.md`의 `한계`). 두 stage의 구분은 ladder 위치로만
    존재하며, 실제로 다른 문맥을 **생성**하는 것은 Wave 3이다.
-   `애매함`이 ladder를 올리므로, 애매한 채로 5회를 채우는 경로가 존재한다.
    그 경우의 보정은 mastery(EMA)와 probe 우선순위가 담당한다.
