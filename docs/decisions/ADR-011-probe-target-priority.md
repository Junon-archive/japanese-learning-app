# ADR-011 --- Probe 대상 우선순위를 2단으로 확정

Status: Accepted

Decision: `02_LEARNING_POLICY.md`의 `Probe 대상 우선순위`를 **2단**으로
확정한다. canonical 정의는 그 절이다.

``` text
1. explicit evidence가 아직 없는 item
   (user_mastery 행 없음 또는 comprehension_mastery IS NULL)
   -> 같은 순위 안에서 passive_no_signal_count >= passive_exposures_before_probe
      인 item을 먼저 묻는다
2. 오래 probe하지 않은 uncertain item
```

v0.2의 2번("passive exposure가 반복됐지만 explicit evidence가 없는
item")은 **1번 내부의 정렬 기준**으로 내리고, 3번("서로 충돌하는 evidence가
있는 item")은 **MVP에서 제외**한다. 새 컬럼도 새 config 키도 만들지 않는다.

## 문제

Wave 2 구현에서 v0.2의 2번이 **도달 불가능**하다는 사실이 드러났다.

-   `user_mastery` 행은 explicit evidence를 기록할 때만 만들어진다
    (`02_LEARNING_POLICY.md`의 `Mastery를 실제로 변경하는 explicit
    evidence`).
-   그 시점에 `evidence_count = 1`이고 `comprehension_mastery`가
    non-NULL이 된다.
-   따라서 "explicit evidence가 없다"는 상태는 언제나 `mastery NULL`
    이거나 행 자체가 없다는 뜻이고, **항상 1번에 먼저 걸린다.** 2번은
    1번의 부분집합이다.

3번은 정의가 어디에도 없었다. 어떤 evidence 조합이 "충돌"인지 정하는
규칙이 없으면 구현이 정의를 발명하게 되고, 그 정의가 사실상 정책이 된다.

## 버린 대안

**(a) `user_item_learning_state` / `user_mastery` 행 생성 시점을 첫
exposure로 앞당긴다.** 2번을 독립 순위로 살릴 수 있는 유일한 길이지만,
mastery 행 생성 시점이 바뀌면 "NULL = 아직 evidence 없음"의 의미가 두 겹이
되고(행 없음 / 행 있고 NULL) `evidence_count`, exploration 후보 조건
(`user_mastery` 행이 없거나 `comprehension_mastery IS NULL`), probe 판정이
모두 따라 움직인다. 얻는 것은 **동일한 순서**다 --- 1번 내부 정렬로 두면
같은 결과가 나온다. 되돌리기 비싼 스키마 의미 변경을 순서 표현 때문에
치를 이유가 없다.

**(b) 2번을 그냥 삭제한다.** "반복해서 스쳐 지나갔는데 한 번도 말하지 않은
item"이라는 신호가 사라지고 `passive_exposures_before_probe` config가 쓰는
곳을 잃는다. `user_item_learning_state.passive_no_signal_count`도 소비처가
없어진다.

**(c) 3번의 정의를 지금 만든다.** 예: 최근 explicit evidence 2건이 서로
반대 방향(`known` ↔ `unknown`)이면 충돌. 기존 데이터로 판정은 가능하지만
MVP에서 이득이 없다. EMA(`mastery_ema_alpha = 0.4`) 아래에서 known과
unknown이 섞인 item의 mastery는 가운데로 수렴하므로 2번(uncertain)이 이미
그 item을 잡는다. 즉 새 event 역추적 쿼리와 새 정책 문장을 추가하고 얻는
것이 거의 없다.

## 근거

-   순위 목록이 **실행 가능한 것만** 담게 된다. 도달 불가능한 순위는
    구현자에게 "내가 뭘 놓쳤나"를 묻게 만들고, 실제로 Wave 2에서 그렇게
    되었다.
-   `passive_exposures_before_probe`와 `passive_no_signal_count`의 소비처가
    유지된다.
-   `uncertain`의 기준을 `02_LEARNING_POLICY.md`가 이미 고정한 세
    observation 값(0.0 / 0.4 / 0.8) 중 최근접으로 정의하므로 **새 tuning
    숫자가 생기지 않는다.**

## 한계

-   evidence 충돌은 MVP에서 uncertain 밴드에 섞여 들어간다. 충돌 item을
    따로 다뤄야 한다는 것이 실사용에서 드러나면 이 ADR을 먼저 고치고
    정의를 추가한다. 그때도 새 컬럼 없이 `learning_events`로 판정 가능하다.
-   probe 우선순위 IntEnum의 값은 이 목록과 함께 2단으로 줄어든다. 값에
    구멍을 남겨 "명세 공백"을 표시하던 구현은 갱신이 필요하다.
