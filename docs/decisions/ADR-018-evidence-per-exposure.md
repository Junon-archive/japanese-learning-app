# ADR-018 --- 노출당 explicit evidence 1건

Status: Accepted

Decision: 한 `(study_presentation, learning_item)`에 explicit evidence는 **최대
1건**이며 **서버가 강제한다.** self-report 3종과 probe 응답 3종을 합쳐 세고
`mastery_probe_skipped`는 세지 않는다. 2회차 요청은 **409**이고 event도 부수효과도
기록하지 않는다. 정정은 지원하지 않는다 --- 2회차로 덮어쓰지 않는다. canonical
불변식은 `07_SRS_SPEC.md`의 `노출당 evidence 1건`, HTTP 계약은 `05_API_SPEC.md`의
`노출당 evidence 상한`.

## 문제

Wave 2 구현은 같은 item에 대한 두 번째 self-report를 `client_event_id`만 다르면
**두 번 다 적용했다**(`app/services/interactions.py`의 `self_report()`). mastery
EMA가 두 번 돌고 `review_states.reps`가 두 번 오른다.

명세는 이 경우를 금지하지 않았다. 확인한 것:

-   `07_SRS_SPEC.md`의 `중복 집계 금지`는 **exposure**만 다룬다
    (`같은 study_presentation + 같은 learning_item = 최대 1 exposure`). evidence
    개수는 말하지 않는다.
-   `07_SRS_SPEC.md`의 `No-signal review`와 `전이 규칙`은 둘 다 `(presentation,
    item)`에 evidence가 **존재하는가**를 묻는 존재 판정이다. 그래서 두 번째
    report는 무신호 판정도 `context_stage` 전이도 바꾸지 않는다. **이중 적용되는
    것은 mastery EMA와 FSRS뿐이었다.**
-   `02_LEARNING_POLICY.md`는 `evidence_count`를 "mastery update에 실제 사용된
    explicit evidence 개수"로 정의하므로, 2회 적용하면 2로 세는 것이 문자 그대로
    맞았다.

**출발점은 비대칭이었다.** `05_API_SPEC.md`는 probe에 대해 이미 "같은 `probe_id`에
이미 응답 event가 있으면 새로 기록하지 않고 기존 결과를 반환한다. probe 하나에
응답은 최대 1건이다"를 canonical로 못박고 있었고(실제 판정 키는 `(presentation,
learning_item)`이며 자연키 때문에 현재 같은 결과를 낸다 --- 위 `근거`), 구현 주석은 그 이유를 "같은
probe에 known과 unknown을 연달아 보내 **EMA를 흔드는 경로를 막는다**"로 적고
있었다. self-report는 같은 EMA, 같은 FSRS mapping, 같은 위험인데 그 조항이 없었다.
한쪽만 막혀 있는 것을 정당화할 근거를 찾지 못했다.

원칙 자체는 이미 문서에 있었다. `13_ACCEPTANCE_CRITERIA.md`와
`12_TEST_PLAN.md`가 "**같은 노출이 두 번 평가되지 않는다**"를 쓰고 있었으나, 그
문장이 실제로 강제하던 범위는 `/complete` 이후 도착한 상호작용뿐이었다(ADR-014의
상태 게이트). 열린 presentation 안에서의 이중 평가는 열려 있었다.

## 결정의 두 정제

**단위는 `(presentation, learning_item)`이다.** `sentence_item`이 아니다. 명세의
모든 노출·증거 판정 단위가 `learning_item`이고 evidence가 붙는 대상도
`learning_events.learning_item_id`다. `sentence_item` 단위로 세면 한 문장에 같은
`learning_item`을 가리키는 `sentence_item`이 둘 있을 때 evidence 2건이 통과한다.

**self-report와 probe 응답을 한 공간에서 센다.** 이 경로는 구조적으로 죽은 경로가
아니다 --- probe 후보는 그 presentation의 target item이고 `choose_probe`가 `/next`
응답에 probe를 실어 확정하므로, 사용자가 item X에 `알고 있었음`을 self-report한 뒤
같은 X의 probe에 `몰랐음`을 답하는 순서가 성립한다. probe 응답 1건 제한은 **probe
응답 event만** 보므로 앞선 self-report를 보지 못하고, 따라서 이 경로를 막지 못한다.

세는 집합은 `07_SRS_SPEC.md`의 `No-signal review`가 이미 `신호 있음`으로 열거한 **그
6개 event**다. 새 목록을 만들지 않았다 --- 같은 집합을 두 곳에 적으면 한쪽만
고쳐지는 순간 무신호 판정과 evidence 상한이 서로 다른 것을 세게 된다.
`mastery_probe_skipped`는 제외한다(`02_LEARNING_POLICY.md`의 `Skip`: "skip = mastery
evidence 아님").

## 버린 대안

**(a) 현행 유지 + 프론트에서 버튼 잠금.** 불변식이 클라이언트 신뢰 위에 놓인다.
재시도, 두 번째 탭, 직접 호출로 뚫리고 뚫린 결과가 mastery와 `review_states`에
조용히 남는다. 어떤 테스트도 빨개지지 않는다. 코드 변경이 0이라는 것이 유일한
장점이고, 그 대가로 선언된 원칙("같은 노출이 두 번 평가되지 않는다")과 실제 강제
범위가 계속 어긋난다.

**(b) 2회차로 덮어쓴다(정정).** 사용자 의도에는 가장 맞지만 **MVP 범위 밖이다.**
덮어쓰려면 그 노출 직전의 상태가 필요한데 저장돼 있지 않다.

``` text
EMA    new = old*(1-alpha) + observation*alpha
       역함수에 old가 필요하지만 user_mastery는 현재값만 갖는다
FSRS   Card를 review 전 상태로 복원해야 하지만
       review_states도 현재 상태만 갖는다 (stability/difficulty/state/step/reps/lapses)
```

직전값 컬럼을 만들거나 `learning_events` replay 경로를 만드는 것이 전제 조건이고,
둘 다 새 스키마 또는 새 기능이다. `learning_events`가 immutable raw history라는
설계(`04_DB_SPEC.md`)와도 불편하게 만난다 --- 첫 report event를 남긴 채 그 효과만
지우는 구조가 된다.

**(c) 2회차를 조용히 무시하고 204를 돌려준다.** 거부가 아니라 성공으로 응답하므로
client가 정정이 반영됐다고 오해한다. `probe-response`가 기존 결과를 돌려주는 것과
달라 보이지만 그쪽은 **같은 `probe_id`에 대한 재전송**이라 "당신의 답은 이것"이라는
참인 정보를 돌려준다. 여기서는 사용자가 **다른 답**을 보냈고 그것이 반영되지 않으므로
204는 거짓이다.

**(d) 단위를 `sentence_item`으로 둔다.** 위 `결정의 두 정제` 참조. 한 문장에 같은
`learning_item`을 가리키는 `sentence_item`이 둘이면 뚫린다.

## 근거

-   **강제 수단은 둘이고 둘 다 필요하다.** 애플리케이션 선행 검사가 정상 경로의
    2회차를 event 없이 409로 거부하고, `learning_events`의 partial unique index
    `uq_learning_events_evidence`가 동시 요청을 직렬화한다(`04_DB_SPEC.md`의
    `learning_events`). 선행 검사와 INSERT 사이에 잠금이 없으므로 검사만으로는 서로
    다른 `client_event_id` 2건이 각자 "evidence 없음"을 읽고 둘 다 기록할 수 있다 ---
    이 ADR이 "프론트에서 버튼을 잠그는 것으로는 부족하다"고 말한 것과 **같은 논리를
    한 단계 더 적용한 결과**이며 새 결정이 아니다. 경합에서 진 요청도 같은 409를
    받는다. index만 남기고 검사를 지우면 2회차마다 event가 먼저 기록되려 하므로
    (immutable log에) 남길 이유가 없는 시도가 계속 쌓인다.
-   거부 코드를 409로 한 이유: self-report는 **204라 body가 없다.** probe처럼 "기존
    결과"를 돌려줄 자리가 없으므로 성공 코드로는 "이미 받았다"를 표현할 방법이
    없다. 그리고 상태 충돌이라는 의미가 409에 정확히 맞는다.
-   **재전송 멱등성이 상한보다 우선한다.** 성공한 self-report의 네트워크 재시도가
    자기가 만든 evidence에 걸려 409를 받으면 client가 성공한 요청을 실패로 읽는다.
    `05_API_SPEC.md`의 `공통 규칙`이 "재전송 시 동일 결과를 반환한다"를 canonical로
    두고 있으므로 그쪽이 이긴다.
    **그 우선은 판정 순서가 아니라 제외 조건으로 성립한다.** 상한 검사는 **요청이
    들고 온 `client_event_id`와 다른** event만 센다. 그래서 상한을 먼저 판정해도
    재전송은 걸리지 않고 idempotency 경로로 내려간다. 처음에는 "멱등성을 먼저
    판정한다"로 적었으나 그것으로는 부족하다 --- 제외 조건이 없으면 순서를 뒤집어도
    상한이 방금 만든 자기 행을 센다. 확정된 순서는 `05_API_SPEC.md`의
    `판정 순서`다.
-   같은 이유로 **probe 응답 1건 제한을 지우지 않았다.** 그 제한은 skip을 포함하고
    결과가 기존 응답 200이라 이 ADR의 상한과 겹치되 같지 않다. 재전송 멱등성을
    담당하는 쪽이 그것이다. **판정 키는 두 규칙이 같다**(`(presentation,
    learning_item)`) --- `Mastery Probe`가 `probe_id` 기준으로 서술하지만 그 event의
    자연키가 `(presentation, learning_item)`당 하나이므로 현재 두 표현은 같은 결과를
    낸다. 따라서 두 규칙을 갈라 두는 근거는 키가 아니라 **skip 포함 여부와 결과**다.
-   **`probe_id` 유효성(400)은 상한보다 구조적으로 앞이다.** `/probe-response`는
    판정 키를 그 probe event에서 꺼내므로 event가 유효하지 않으면 상한을 판정할 키가
    없다. 선택이 아니라 순서를 바꿀 방법이 없는 경우다.
-   **409 사유를 구분한다.** 이 409는 다른 세 409와 복구 동작이 다르다. 상태 게이트
    409는 세션 재획득으로 이어지고, `client_event_id` 충돌 409는 **새 UUIDv4로
    재시도하면 성공할 수 있고**, 이것은 "이미 기록했습니다"로 끝나며 **어떤 재시도도
    성공하지 못한다.** 한 문구로 합치면 client가 무한 재시도(충돌로 오해), 불필요한
    세션 재획득(게이트로 오해), 또는 복구 포기(반대 방향의 오해)를 한다. 구분 수단은
    기존 체계 그대로 응답 body의 사유 문구이며 새 코드 체계를 만들지 않았다. 네 사유와
    각각의 client 동작은 `05_API_SPEC.md`의 `409 사유 구분`이 canonical이다.

## 한계

**정정 수단이 없다.** 잘못 누른 `알고 있었음`은 그 노출에 고정되고, 사용자가 그
노출에서 할 수 있는 일은 없다(`/flag`는 콘텐츠 신고이므로 의미가 다르다).

이것을 견딜 만하게 하는 것은 두 오입력의 피해가 대칭이 아니라는 점이다.

``` text
몰랐음 오입력      rating Again -> 다음 노출이 곧 온다 -> 스스로 교정된다
알고 있었음 오입력  rating Good  -> interval이 밀린다   -> 교정되지 않는다
```

뒤쪽도 영구 손실은 아니다. 그 item은 minimum meaningful exposure를 채우기 전까지
`reinforcement`로 계속 돌아오므로(`07_SRS_SPEC.md`의 `Minimum 5 Exposures와 FSRS의
분리`, `12_TEST_PLAN.md`의 Scenario C) 다음 노출에서 다시 답할 기회가 있다. 다만 그
노출 하나의 evidence는 틀린 값으로 남는다.

실사용에서 오입력 빈도가 문제로 드러나면 되돌리는 방향은 (b)이고, 그때는 직전값
저장 또는 replay가 선행 조건이므로 **스키마 결정을 먼저** 해야 한다. 이 ADR을
뒤집는 비용이 그것이다.
