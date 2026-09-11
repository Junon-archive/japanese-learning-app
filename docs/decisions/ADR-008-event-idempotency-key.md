# ADR-008 --- learning_events.client_event_id 발급 주체

Status: Accepted

Decision: `learning_events.client_event_id`는 "client가 생성한 UUID"가
아니라 **event의 idempotency key**이고, 발급 주체는 `event_type`마다
고정한다. 서버가 부수적으로 남기는 event는 **고정 namespace를 쓴
UUIDv5**로 서버가 결정론적으로 발급한다. canonical 표는
`spec/mvp-01-core/05_API_SPEC.md`의 `event idempotency key`,
컬럼 의미는 `spec/mvp-01-core/04_DB_SPEC.md`의
`client_event_id 발급 주체`에 있다.

``` text
client_event_id = uuid5(NC_EVENT_NAMESPACE, 자연키 문자열)
```

server 발급: `session_started`, `sentence_viewed`, `sentence_completed`,
`mastery_probe_shown`, `session_finished`.
client 발급: `session_extended`와 사용자 상호작용 event 전부.

## 문제

`04_DB_SPEC.md`는 이 컬럼을 `NOT NULL` + "client 생성 UUID"로 정의했고
`05_API_SPEC.md`는 "상태 변경 event POST는 client가 생성한
`client_event_id`를 포함한다"고 했다. 그런데 위 5개 event는 **client가
POST하는 endpoint가 없다.** `POST /api/study/session`,
`/session/{id}/next`, `/session/{id}/finish`를 처리하면서 서버가 남긴다.
두 문장은 서로 모순이었고 구현할 수 없었다.

## 버린 대안

**(a) 모든 endpoint의 request body에 `client_event_id`를 받는다.**
`/next` 재시도로 presentation이 중복 생성되는 문제까지 같이 풀린다는
이점이 있었다. 버린 이유:

-   `/session`, `/next`, `/finish`는 각각 서버 row(session /
    presentation) 하나에 대응하는 자연키가 이미 있다. client key는 서버가
    이미 아는 정보를 client에게 만들어 오게 하는 것이다.
-   client가 endpoint마다 UUID를 만들고 **재시도 간 보존**해야 한다.
    보존을 빠뜨리면 idempotency가 조용히 사라지고, 그 버그는 네트워크가
    불안정할 때만 드러난다.
-   `/next` 중복 생성의 올바른 해법은 event 수준 idempotency가 아니라
    **세션 불변식**이다. 한 세션에 완료되지 않은 presentation은 최대
    1개이고 `/next`는 그것을 그대로 반환한다
    (`05_API_SPEC.md`의 `열린 presentation 불변식`). 이쪽이 client key
    없이 같은 문제를 풀고, `/complete`를 명시적 단계로 만들어 "Next가
    직전 문장을 암묵적으로 완료시키는가"라는 모호함도 없앤다.

**(b) 컬럼 이름을 `event_idempotency_key` 등으로 바꾼다.** migration과
이미 작성된 model/테스트가 따라 움직이는데 얻는 것은 이름 하나의
정확도뿐이다. 이름은 유지하고 의미를 명세에 고정한다.

## 근거

-   UUIDv5는 입력이 같으면 결과가 같으므로 재시도 안전성이 저장소 없이
    보장된다. `(user_id, client_event_id)` unique가 중복을 막는다.
-   자연키에 **시각이나 순번을 넣지 않는다.** 넣으면 재시도마다 값이
    달라져 idempotency가 사라진다.
-   `session_extended`만 client 발급인 이유는 `+5분`이 한 세션에서 여러
    번 정당하게 일어나는 유일한 server-side event이고, 서버에는 "재시도"와
    "두 번째 연장"을 구분할 자연키가 없기 때문이다. `":{순번}"`을 쓰면
    재시도가 순번을 올려 중복 연장이 된다.

## 한계

`NC_EVENT_NAMESPACE`는 코드에 고정한 상수이며 설정값이 아니다. 바꾸면
과거 event의 idempotency key를 재계산할 수 없다. 자연키 문자열 형식도
같은 이유로 사후 변경이 비싸다.
