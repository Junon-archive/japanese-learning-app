# ADR-009 --- probe_id의 발급·저장 위치

Status: Accepted

Decision: `05_API_SPEC.md`의 `probe.probe_id`는 해당 probe를 낸
**`mastery_probe_shown` learning_event의 정수 id**다. 전용 probe
테이블을 만들지 않는다. canonical 정의는
`spec/mvp-01-core/05_API_SPEC.md`의 `Mastery Probe`와
`spec/mvp-01-core/04_DB_SPEC.md`의 `probe 상태를 어디에 두는가`.

이 결정은 ADR-008과 함께 내려야 한다. 성립의 전제가
`mastery_probe_shown`의 `client_event_id`를 서버가
`uuid5(ns, "mastery_probe_shown:{presentation_id}:{learning_item_id}")`로
결정론적으로 발급한다는 것이기 때문이다.

## 버린 대안

**(2) 새 테이블 `mastery_probes`**
`(id, user_id, study_presentation_id, learning_item_id, shown_at,
responded_at, response)` + `unique(presentation_id, learning_item_id)`.
"event log를 상태 저장소로 쓰지 않는다"는 이점이 있었다. 버린 이유:

-   probe가 실제로 필요로 하는 **상태는 이미 전용 컬럼에 있다.**
    `user_item_learning_state.last_probe_at`,
    `user_item_learning_state.probe_skip_count`가 cooldown과 skip 집계를
    담당한다(`04_DB_SPEC.md`). event log에서 읽는 것은 "이 `probe_id`가
    유효한가, 어떤 item에 대한 것인가"라는 **조회**이지 상태가 아니다.
-   따라서 새 테이블의 모든 컬럼이 파생값이다. `shown_at` /
    `responded_at` / `response`는 `learning_events`가 이미 가지고 있고,
    `unique(presentation_id, learning_item_id)`는 위 UUIDv5 자연키와 같은
    내용을 두 번 표현한다.
-   20번째 테이블 + migration + `04_DB_SPEC.md` 개정 비용을 파생값에
    지불하게 된다. MVP 범위를 넓히지 않는다는 제약에 어긋난다.

**(3) `probe_id = study_presentation_id`**
저장 비용 0이지만 URL이 이미 `{pid}`를 들고 있어 body의 `probe_id`가
중복 정보가 되고, `probe_id → learning_item_id` 해석이 결국 (1)과 같은
event 조회를 요구한다. 즉 (1)의 조회는 그대로 남으면서 "probe_id"라는
필드만 의미를 잃는다.

## 근거

-   ADR-005(정수 id)를 그대로 만족한다.
-   `열린 presentation 불변식` 때문에 같은 presentation을 다시 받아도
    probe event의 자연키가 같고, 따라서 `probe_id`도 **같은 값으로
    유지된다.** client가 응답을 재전송해도 대상이 흔들리지 않는다.
-   응답 event의 `learning_item_id`를 client가 보낸 값이 아니라 조회한
    probe event의 값으로 쓰므로, body에 `learning_item_id`를 받지 않아도
    되고 위조된 대상에 evidence를 붙일 수 없다.

## 한계

probe 응답 여부를 알려면 `learning_events`를 한 번 더 조회해야 한다
(같은 `study_presentation_id` + `learning_item_id`의 응답 event 존재
여부). 사용자 1명 규모에서 문제가 되지 않으며, `learning_events`에는
`(user_id, created_at)` index가 있다. probe 분석 쿼리가 실제로 무거워지면
그때 이 ADR을 먼저 고치고 테이블을 추가한다.
