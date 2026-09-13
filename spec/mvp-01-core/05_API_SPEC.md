# API Specification

기능 경계: - Auth: login/logout/me - Session:
create/resume/next/finish/extend - Sentence: payload, translation event,
item explanation - Events: click/self-report/probe/flag - History:
recent sessions/basic summary

Browser는 OpenAI secret을 받지 않는다. normal tap은 live LLM에 의존하지
않는다. 필요한 event endpoint는 idempotency를 고려한다.

**Public Demo는 API를 사용하지 않는다.** demo endpoint를 만들지 않으며
익명 요청을 받는 학습 API도 두지 않는다
(`spec/04_SECURITY_AND_DATA.md`의 Public Demo 구조). 모든 학습 API는
인증된 private user 전용이다. MVP-02에서 API를 쓰지 않는 화면은 **선택 홈, Public Demo, 가나 학습**
셋이다. 가나 학습 endpoint, 후리가나 설정 endpoint, 방문자 진도 endpoint를 만들지 않는다.
`GET /api/auth/me`는 계약이 그대로이고 부르는 시점만 바뀌었다 --- 상단바 `로그인`을 누를 때만
부른다(`03_UI_UX_SPEC.md`의 `상단바`).

audio 관련 endpoint와 event는 MVP에 없다(`00_SCOPE.md`).

## 공통 규칙

-   모든 학습 API는 인증 필요. 미인증 요청은 401.
-   익명 접근 허용 목록은 아래 `익명 접근 허용 목록`이 canonical이다.
-   요청/응답의 timestamp는 UTC ISO-8601.
-   모든 `learning_events` row는 `client_event_id`(UUID) idempotency key를
    가진다. 서버는 `(user_id, client_event_id)` unique로 중복 저장을 막고,
    재전송 시 동일 결과를 반환한다. **발급 주체는 event_type마다 고정이며
    아래 `event idempotency key`가 canonical이다.**
-   모든 학습 API handler는 **외부 provider를 호출하지 않는다**
    (`08_LLM_SPEC.md`).
-   응답에 실리는 id는 DB 정수 PK를 **JSON number(정수)** 로 그대로
    낸다. 아래 `ID 표현`이 canonical이다.

### 익명 접근 허용 목록

유효한 auth session cookie 없이 호출할 수 있는 endpoint는 **정확히 다음
둘**이다.

``` text
GET  /api/health        상태 점검. 사용자 데이터와 설정값을 반환하지 않는다.
POST /api/auth/login    인증을 생성하는 endpoint이므로 호출 시점에 세션이 없다.
```

그 밖의 **모든** endpoint는 유효한 auth session cookie를 요구하고, 없거나
만료·폐기됐으면 401을 반환한다. `POST /api/auth/logout`과
`GET /api/auth/me`도 여기에 포함된다(로그아웃은 파기할 세션이 있어야
의미가 있으므로 미인증 호출은 401이다).

`POST /api/auth/login`은 "인증이 필요 없는" endpoint가 아니라 **인증을
만드는** endpoint다. 그래서 인증 요구 규칙의 예외가 아니라 그 규칙이
성립하기 위한 진입점이다.

**학습 데이터를 읽거나 쓰는 endpoint 중 익명 접근이 가능한 것은 하나도
없다.** `GET /api/health`는 학습 데이터를 다루지 않고,
`POST /api/auth/login`은 인증에 성공해야만 학습 데이터 경로가 열린다.

이 목록에 endpoint를 추가하려면 **이 절을 먼저 고친다.** 여기에 없는
경로가 익명 접근을 허용하면 명세 위반이다(**fail-closed**).

FastAPI 자동 문서 경로(`/docs`, `/redoc`, `/openapi.json`,
`/docs/oauth2-redirect`)는 이 목록과 별개이며 `APP_ENV`로 제어한다
(`spec/04_SECURITY_AND_DATA.md`).

### ID 표현

API가 노출하는 id는 DB 정수 PK이며 **JSON number(정수)** 로 낸다. 문자열로
감싸지 않는다.

``` text
정수   user_id, presentation_id, sentence_id, sentence_item_id,
       learning_item_id, session_id, probe_id 등 모든 DB PK 참조
문자열 client_event_id (client가 생성하는 UUID) 만 예외
```

-   문자열로 감싸면 backend·frontend 양쪽에 변환 지점이 생기고, 같은
    값이 `"1"`과 `1`로 갈리는 버그를 만든다. 근거와 한계는
    `docs/decisions/ADR-005-api-id-representation.md`.
-   `probe_id`는 `mastery_probe_shown` learning_event의 정수 id다
    (아래 `Mastery Probe`, `04_DB_SPEC.md`의 `probe 상태를 어디에 두는가`).
    다른 PK와 같은 표현 규칙을 따른다.

### event idempotency key

**`learning_events.client_event_id`의 발급 주체 표는 여기가 canonical이다.**
컬럼 의미는 `04_DB_SPEC.md`의 `client_event_id 발급 주체`를 따른다.

v0.2의 "상태 변경 event POST는 client가 생성한 `client_event_id`를
포함한다"는 규칙은 `session_started`, `sentence_viewed`,
`sentence_completed`, `mastery_probe_shown`, `session_finished`에
적용할 수 없었다. **client가 이 event들을 POST하지 않기 때문이다.** 서버가
요청을 처리하면서 부수적으로 남긴다. 그래서 규칙을 둘로 나눈다.

``` text
event_type                 발급    출처 / 자연키
-------------------------  ------  ---------------------------------------------
session_started            server  "session_started:{study_session_id}"
sentence_viewed            server  "sentence_viewed:{study_presentation_id}"
sentence_completed         server  "sentence_completed:{study_presentation_id}"
mastery_probe_shown        server  "mastery_probe_shown:{study_presentation_id}:{learning_item_id}"
session_finished           server  "session_finished:{study_session_id}"

session_extended           client  POST /session/{id}/extend      body
item_clicked               client  POST .../click                 body
explanation_revealed       client  POST .../explanation-revealed  body
translation_revealed       client  POST .../translation/reveal    body
self_report_known          client  POST .../self-report           body
self_report_uncertain      client  POST .../self-report           body
self_report_unknown        client  POST .../self-report           body
mastery_probe_known        client  POST .../probe-response        body
mastery_probe_uncertain    client  POST .../probe-response        body
mastery_probe_unknown      client  POST .../probe-response        body
mastery_probe_skipped      client  POST .../probe-response        body
content_flagged            client  POST .../flag                  body
```

server 발급은 **고정 namespace UUID를 쓴 UUIDv5**다.

``` text
client_event_id = uuid5(NC_EVENT_NAMESPACE, 자연키 문자열)
```

`NC_EVENT_NAMESPACE`는 코드에 고정한 UUID 상수다. 설정값이 아니다. 바꾸면
과거 event의 idempotency key를 재계산할 수 없다.

-   자연키에 시각이나 순번을 넣지 않는다. 그러면 재시도마다 값이 달라져
    idempotency가 사라진다.
-   server 발급 event는 그래서 **재시도해도 두 번 기록되지 않는다.**
    unique 충돌이 나면 기존 row를 그대로 두고 성공으로 처리한다.
-   `session_extended`만 client 발급인 이유: `+5분`은 한 세션에서 여러 번
    정당하게 일어나고, 서버에는 재시도와 두 번째 연장을 구분할 자연키가
    없다. `"...:{순번}"`을 쓰면 재시도가 순번을 하나 더 올려 중복 연장이
    된다. 이 event만 client가 key를 들고 와야 한다.

`POST /api/study/session`, `/next`, `/finish`의 request body에는
`client_event_id`를 **받지 않는다.** 셋 다 서버 row(session /
presentation) 하나에 대응하는 자연키가 있어 server 발급으로 충분하고,
body를 늘리면 client가 endpoint마다 UUID를 만들어 재시도 간 보존해야
한다. `/next` 재시도로 presentation이 중복 생성되는 문제는 client key가
아니라 아래 `열린 presentation 불변식`으로 막는다. 근거는
`docs/decisions/ADR-008-event-idempotency-key.md`.

### 키 공간 분리 (server = v5, client = v4)

두 발급 주체는 **같은 `(user_id, client_event_id)` unique 공간**을 쓴다.
server 자연키 형식은 위 표에 공개돼 있으므로, 아무 제약이 없으면 client가
서버가 나중에 쓸 키를 **먼저 점유**할 수 있다. 그러면 서버 경로가 영구히
막힌다: `session_finished:{sid}`를 점유하면 `/finish`가 계속 409이고, idle
timeout 만료도 같은 키를 쓰므로 `POST /api/study/session`까지 막혀 세션이
끝나지도 새로 생기지도 않는다. DB를 직접 고치지 않으면 복구되지 않는다.

그래서 **두 키 공간을 UUID version으로 분리한다.**

``` text
server 발급   uuid5(NC_EVENT_NAMESPACE, 자연키)   -> 항상 version 5
client 발급   반드시 UUIDv4 (random)              -> version 4
```

-   서버는 request body의 `client_event_id`가 **UUIDv4가 아니면 거부한다.**
    body 검증 실패이므로 응답은 **422**이고, event는 기록되지 않는다. 검증은
    `client_event_id`를 받는 요청 schema **한 곳**에서 한다 --- endpoint마다
    붙이면 하나를 빠뜨린 곳이 그대로 구멍이 된다.
-   `uuid5` 결과는 version nibble이 항상 5이므로 client가 보낼 수 있는 값과
    **구조적으로 겹치지 않는다.** 점유는 시도 자체가 성립하지 않는다.
    namespace를 숨기거나 하나 더 두는 방식과 달리, 상수를 알아내도 우회할 수
    없다.
-   browser의 `crypto.randomUUID()`가 v4를 낸다. client 비용은 없다.
-   그럼에도 **server 발급 경로**가 다른 `event_type`의 기존 행을 만나면 그것은
    client 잘못이 아니라 **서버 불변식 위반**이다. 409가 아니라 **500**으로
    응답하고 로그를 남긴다. 409는 "당신이 보낸 key가 이미 다른 event에 쓰였다"는
    뜻인데 이 경로에는 client가 보낸 key가 없다.
-   **client 발급 키끼리**의 충돌(한 UUID를 두 endpoint에 재사용)은 그대로
    **409**다. client가 새 UUID로 재시도하면 복구되므로 영구 상태가 아니다.

근거와 버린 대안은 `docs/decisions/ADR-008-event-idempotency-key.md`의
`후속 결정 --- 키 공간 분리`.

## Authentication

``` text
POST /api/auth/login      {login_id, password} -> set-cookie, {user}
POST /api/auth/logout     -> 204
GET  /api/auth/me         -> {user_id, login_id, timezone, starting_level}
```

`POST /api/auth/login`의 실패 응답은 사유와 무관하게 **동일한 401**이다.
없는 `login_id`, 틀린 password, 비활성 계정을 구분하지 않는다.

-   MVP는 시도 횟수 제한·계정 잠금·실패 지연을 두지 않으므로 이 endpoint는
    **429를 반환하지 않는다.** 방어 구성과 버린 대안은
    `spec/04_SECURITY_AND_DATA.md`의
    `온라인 무차별 대입 방어 (MVP 확정)`가 canonical이다.
-   password 요구사항은 **계정 생성 경로에서만** 검증한다. login은
    검증하지 않는다(같은 문서의 `Password 요구사항 (MVP 확정)`).

## Study Session

``` text
GET  /api/study/session            현재 열린 session 조회 (없으면 null)
POST /api/study/session            create 또는 resume
POST /api/study/session/{id}/next      다음 presentation 반환
POST /api/study/session/{id}/finish    세션 종료
POST /api/study/session/{id}/extend    extra_session_minutes 만큼 연장
                                       body: {client_event_id}
```

`/extend`만 body에 `client_event_id`를 받는다. 이유는 위
`event idempotency key`에 있다.

연장 폭은 `14_CONFIGURATION.md`의 `extra_session_minutes`이고 **호출 전에는 어떤
응답에도 실리지 않는다.** 호출 후 늘어난 총량은 응답의 `extended_minutes`로
확인한다. 그래서 연장 버튼 문구에는 분 수를 적지 않는다(`03_UI_UX_SPEC.md`의
`Session End`).

`POST /session`은 idle timeout 이내면 기존 세션을 resume하고, 초과면 새
세션을 만든다(`04_DB_SPEC.md`의 `study_sessions`,
`14_CONFIGURATION.md`의 `study_session_idle_timeout_minutes`).

`POST /session`은 세션을 만들거나 resume한 직후
`06_LEARNING_ENGINE.md`의 `Candidate Materialization`을 **요청 사용자
한 명분** 실행한다. seed만 적재된 신규 사용자의 Ready Pool이 이 시점에
채워지므로 첫 세션을 시작할 수 있다.

### 열린 presentation 불변식

``` text
한 study_session에 completed_at IS NULL 인 study_presentation은
최대 1개다.
```

`POST /session/{id}/next`는 그 세션에 완료되지 않은 presentation이 이미
있으면 **새로 만들지 않고 그것을 그대로 반환한다.** 따라서 네트워크
재시도나 모바일 더블탭으로 presentation이 중복 생성되지 않고, candidate가
헛되이 소비되지 않으며 Category Mix 집계도 왜곡되지 않는다.

-   다음 문장으로 넘어가려면 client가 **먼저
    `POST /presentations/{pid}/complete`를 호출**한다. `/next`가 직전
    문장을 암묵적으로 완료시키지 않는다. 그렇게 하면 `/next` 재시도가
    다시 새 presentation을 만들게 되어 이 불변식이 깨진다.
-   `POST /session/{id}/finish`는 아직 열려 있는 presentation이 있으면
    그것을 완료 처리하고 `sentence_completed`를 남긴다. 이 event의
    idempotency key는 presentation id 기반 server 발급이므로 동시에 도착한
    `/complete`와 중복 기록되지 않는다.
-   `/next`가 선택한 category에 ready candidate가 없으면 `Pool Fallback`
    0단계로 materialization을 **요청당 1회** 실행하고, 그 뒤 같은 deficit
    순서로 category를 다시 훑는다. 순서의 canonical 정의는
    `06_LEARNING_ENGINE.md`의 `Pool Fallback`이다.

### 세션·presentation 상태 게이트

**닫힌 session과 이미 완료된 presentation에서 무엇이 허용되는지는 여기가
canonical이다.** study endpoint 12개가 이 표 하나를 따른다.

``` text
endpoint                             session.ended_at IS NOT NULL   presentation.completed_at IS NOT NULL
-----------------------------------  -----------------------------  -------------------------------------
GET  /session                        해당 없음 (열린 것만 반환)      -
POST /session                        해당 없음 (resume 또는 신규)    -
POST /session/{id}/next              409                            -
POST /session/{id}/extend            409                            -
POST /session/{id}/finish            200 (같은 session, event 추가 없음)  -
POST /presentations/{pid}/complete   409 (*)                        200 (기존 결과 그대로)
click / explanation-revealed /
translation/reveal / self-report /
probe-response                       409                            409
POST /presentations/{pid}/flag       허용 (**)                      허용 (**)
```

`(*)` `/complete`는 **presentation이 아직 열려 있는데 session이 닫혀 있을
때만** 409다. 이미 완료된 presentation이면 session 상태와 무관하게 200을
돌려준다 --- 성공한 `/complete`의 네트워크 재시도가 그 사이 도착한 `/finish`
때문에 실패로 보이면 안 된다.

`(**)` `/flag`만 상태와 무관하게 허용한다. flag는 evidence를 **만드는** 것이
아니라 **되돌리는** endpoint다. `10_ERROR_HANDLING.md`의 `Content Flag 동작`은
"이미 생성된 `item_exposures`는 `invalidated_at`을 설정"하라고 요구하는데,
exposure는 presentation을 닫을 때 생기므로 그 조항이 참이 되는 순간은 **완료
이후**뿐이다. flag까지 막으면 canonical 조항 하나가 도달 불가능해진다. 대신
**닫힌 session의 flag는 `last_activity_at`을 갱신하지 않는다** --- 끝난 세션의
길이를 바꾸지 않는다. (MVP UI는 현재 문장에서만 flag를 제공한다. 지난 문장을
신고하는 화면은 Future다.)

판정 순서는 **소유권(404) -> 상태 게이트(409) -> 그 밖의 검증(`probe_id`
400 등)** 이다. 남의 presentation은 상태와 무관하게 404다.

거부하는 이유:

-   **같은 노출이 두 번 다르게 평가되는 것을 막는다.** presentation을 닫을 때
    exposure 확정과 무신호 처리(`deferred_until`)가 끝난다
    (`07_SRS_SPEC.md`의 `No-signal review`). 그 뒤에 도착한 self-report나
    probe 응답은 이미 내려진 판정 위에 explicit evidence를 덧붙이고, 끝난
    세션에 새 mastery/`review_states` 행까지 만든다.
-   닫힌 session의 상호작용은 그 session의 `last_activity_at`을 계속 밀어
    세션 길이와 `active_seconds`를 오염시킨다.
-   **idle timeout 때문에 사용자가 화면을 보는 도중 409를 받는 일은 없다.**
    모든 상호작용이 `last_activity_at`을 갱신하고, 만료는
    `POST /api/study/session`이 도착할 때 그 시점에만 적용된다. 409를 받는
    화면은 이미 다른 경로로(직접 종료 / 다른 탭에서 새 세션 시작) 끝난
    session의 화면이다.

idle timeout으로 닫힌 session에 남은 **미완료 presentation은 영원히 미완료로
남는다.** 이 게이트가 `/complete`를 막고 `/finish`는 이미 그 session을 닫았기
때문이다. 의도한 결과다 --- 부재를 완료로 추론해 exposure를 만들지 않는다
(불변식 #2). `열린 presentation 불변식`은 session 하나 안의 규칙이므로 닫힌
session에 남은 행은 그것을 깨지 않는다.

client 동작: 409를 받으면 그 화면의 상호작용을 멈추고 `POST /api/study/session`
으로 현재 session을 다시 얻은 뒤 `/next`로 진행한다. **거부된 상호작용을
재전송하지 않는다** --- 그 노출의 평가는 이미 끝났다. 버린 대안은
`docs/decisions/ADR-014-closed-session-interaction-gate.md`.

### 노출당 evidence 상한

불변식 자체는 `07_SRS_SPEC.md`의 `노출당 evidence 1건`이 canonical이다. 이 절은 그
불변식의 **HTTP 계약**만 정한다.

``` text
POST /presentations/{pid}/self-report      그 (presentation, learning_item)에
POST /presentations/{pid}/probe-response    이미 evidence가 있으면 409
```

-   판정 대상은 `learning_item_id`다. body가 `sentence_item_id`를 받는 것과 무관하게
    서버가 그것을 `learning_item_id`로 바꾼 뒤 센다. `probe-response`는 body에 item을
    받지 않고 probe event에서 가져온다(아래 `Mastery Probe`).
-   409이면 **event를 기록하지 않고 mastery·FSRS·`context_stage`도 건드리지 않는다.**
-   `mastery_probe_skipped`는 evidence가 아니므로 이 상한에 걸리지 않는다. probe를
    skip한 뒤 같은 item에 self-report를 하는 것은 허용된다.

#### 판정 순서

``` text
1. 소유권                                            404
2. 세션·presentation 상태 게이트                     409 (위 절)
3. probe event 유효성          (probe-response 만)   400
4. 이미 응답한 probe           (probe-response 만)   기존 결과 200 (멱등)
5. 그 (presentation, learning_item)에 **다른
   client_event_id의** evidence가 이미 있다          409
6. 같은 client_event_id의 event가 이미 있다          재전송이므로 기존 결과 (204 / 200)
7. 그 client_event_id가 다른 event_type에
   이미 쓰였다                                       409
```

`/self-report`는 3과 4를 거치지 않는다. 나머지 단계는 두 endpoint가 같다.

**3이 5보다 앞인 것은 선택이 아니라 구조다.** `/probe-response`는 body에
`learning_item_id`를 받지 않고 **조회한 probe event에서 꺼낸다**(아래
`Mastery Probe`). 그 event가 유효하지 않으면 5의 판정 키 자체가 없으므로 순서를
바꿀 방법이 없다. 즉 잘못된 `probe_id`는 상한보다 먼저 400이다.

**5가 6보다 앞인데도 재전송 멱등성은 깨지지 않는다.** 5는 **요청이 들고 온
`client_event_id`와 다른** event만 센다. 그래서 성공한 요청의 재전송은 자기가 만든
evidence에 걸리지 않고 6으로 내려가 기존 결과를 받는다. 위 `공통 규칙`의 "재전송 시
동일 결과를 반환한다"를 보장하는 것은 순서가 아니라 **이 제외 조건**이다 --- 제외
조건이 없으면 5를 6 뒤로 옮겨도 부족하다(그때는 5가 방금 만든 자기 행을 센다).

**5가 7보다 앞이다.** 두 409가 동시에 성립할 때 client가 먼저 받는 것은 evidence
상한이고 그것이 더 유용하다 --- 상한은 "재시도하지 말라"는 종결 답이고 key 충돌은
"새 UUID로 재시도하라"다. 순서를 뒤집으면 client가 새 UUID로 재시도한 뒤 결국 상한
409를 받으므로 왕복이 한 번 늘 뿐 결과가 같다.

`/probe-response`의 기존 제한 --- "같은 `probe_id`에 이미 응답 event가 있으면 새로
기록하지 않고 기존 결과를 반환한다"(아래 `Mastery Probe`) --- 은 **그대로 둔다.** 두
규칙은 겹치되 같지 않다.

``` text
                     판정 키                        skip    결과
-------------------  ------------------------------  ------  --------------------
probe 응답 1건 제한  (presentation, learning_item)   포함    기존 응답 200 (멱등)
이 절의 상한         (presentation, learning_item)   제외    409
```

**판정 키가 같다.** `Mastery Probe`가 그 제한을 `probe_id` 기준으로 서술하지만
**실제 판정 키는 `(presentation, learning_item)`이다.** 지금은 두 표현이 같은 결과를
낸다 --- `mastery_probe_shown`의 자연키가
`"mastery_probe_shown:{pid}:{learning_item_id}"`이므로(위 `event idempotency key`) 한
presentation의 한 item에 probe event는 **하나뿐이고**, `probe_id` 하나와 그 쌍 하나가
일대일이다. 자연키가 바뀌어 한 쌍에 probe가 둘 생길 수 있게 되면 **두 표현은 갈라진다**
--- `probe_id` 기준이면 두 번째 probe에 답할 수 있고 쌍 기준이면 막힌다. 문서와 코드가
문자 그대로는 다르지만 그 차이가 현재 도달 불가능한 사례이며, 같은 성격의 선례는
`08_LLM_SPEC.md`의 `target 수 상한의 출처와 검사 10의 지위`다.

**그래서 두 규칙을 갈라 두는 근거는 판정 키가 아니라 `skip`과 결과다.** probe 제한은
`mastery_probe_skipped`를 포함하고 성공 응답(기존 결과 200)을 내므로 **재전송
멱등성**을 담당한다. 이 절의 상한은 skip을 제외하고 409를 내므로 **이중 평가**를
막는다. 상한이 probe 제한을 포함한다고 해서 지우면 안 된다 --- 지우면 성공한 probe
응답의 재시도가 200이 아니라 409가 되고, skip한 probe에 두 번째 skip이 들어온다.

#### 409 사유 구분

**client가 네 가지 409를 구분할 수 있어야 한다.** 복구 동작이 다르기 때문이다.
구분 수단은 응답 body의 사유 문구이며 **새 체계를 만들지 않는다** --- 기존 409들이
이미 서로 다른 문구를 쓰고 있고, 그 문구가 사유 코드다.

``` text
사유                             판정   client 동작
-------------------------------  -----  ---------------------------------------------
session이 이미 종료됨            2      POST /api/study/session 으로 session 재획득
presentation이 이미 완료됨       2        -> /next (위 `세션·presentation 상태 게이트`)
이 노출에 이미 evidence가 있음   5      재시도하지 않는다. "이미 기록했습니다"로 끝낸다
client_event_id가 다른 event에   7      같은 요청을 **새 UUIDv4로** 재시도
  이미 쓰임
```

복구 동작이 **세 종류**이고, 그것이 네 사유를 갈라 두는 이유다.

-   **앞의 둘: 화면 상태가 서버와 어긋났다.** 그 화면의 상호작용을 멈추고 session을
    다시 얻은 뒤 `/next`로 진행한다. **거부된 상호작용을 재전송하지 않는다**(위
    상태 게이트 절).
-   **세 번째: 서버가 이미 사용자의 답을 받아 두었다.** 요청 내용이 옳고 상태도 옳은데
    그 노출의 평가가 끝난 것이므로 **어떤 재시도도 성공하지 못하고 해서도 안 된다.**
    세션을 다시 얻어도 달라지지 않는다.
-   **네 번째: 요청 자체는 유효하고 key만 잘못됐다.** 같은 요청을 새 UUIDv4로 보내면
    **성공할 수 있다** --- 이 점이 세 번째와 정반대다. 영구 상태가 아니다(위
    `키 공간 분리`).

넷을 한 문구로 합치면 client가 무한 재시도 루프(세 번째를 네 번째로 오해), 불필요한
세션 재획득(세 번째를 앞의 둘로 오해), 또는 복구 포기(네 번째를 세 번째로 오해)를
하게 된다.

사유 문구는 서로 달라야 하고 **내부 사정을 담지 않는다**(어느 event가 언제 기록됐는지,
어떤 key가 무엇에 점유돼 있는지는 응답에 넣지 않는다).

### 진행 상태의 갱신과 세션 종료 판정

**client가 진행률과 "세션 종료 도달"을 무엇으로 계산하고 언제 다시 읽는지의
canonical 정의는 이 절이다.**

`active_seconds` / `target_minutes` / `extended_minutes`는 session payload를
내는 응답, 즉 `GET /session`, `POST /session`, `/finish`, `/extend`에만 있다.
`/next`와 `/complete` 응답에는 **없다** --- 둘은 presentation 계약이고, 같은
값을 두 계약에서 내면 어느 쪽이 최신인지가 응답 도착 순서에 달리게 된다.

진행 표시:

``` text
분모 = (target_minutes + extended_minutes) * 60   (초)
분자 = active_seconds
```

세션 종료 도달 판정:

``` text
도달 = active_seconds >= (target_minutes + extended_minutes) * 60
```

-   **서버에 "목표 도달" 플래그를 두지 않는다.** 판정에 쓰이는 값이 전부 서버가
    내려준 것이므로 client가 파생해도 정책값 하드코딩이 아니다. 플래그를 두면 같은
    사실의 표현이 둘이 되고, 둘이 어긋나는 순간 어느 쪽이 맞는지 판정할 근거가
    없다. `default_session_minutes`와 `extra_session_minutes`를 frontend가 읽는
    것은 이와 다른 이야기이며 **금지한다** --- 그것은 정책값 하드코딩이다.
-   도달은 **세션의 종료가 아니다.** session을 닫는 것은 `/finish` 하나뿐이다.
    도달은 `오늘 학습 완료 / 더 학습하기`를 띄우는 시점일 뿐이고
    (`03_UI_UX_SPEC.md`의 `Session End`), 도달 뒤에도 `/next`와 상호작용은 그대로
    허용된다. 서버는 도달을 이유로 아무것도 거부하지 않는다.

갱신 수단:

``` text
client는 POST /presentations/{pid}/complete 직후
GET /api/study/session 을 한 번 다시 호출해 session payload를 갱신한다.
갱신 단위는 문장이다.
```

-   **주기적 폴링을 하지 않는다.** 특히 상호작용 endpoint를 진행률 갱신 목적으로
    주기 호출해서는 안 된다. 상태를 바꾸는 모든 경로가 `last_activity_at`을
    옮기므로(위 `세션·presentation 상태 게이트`), 그런 호출은
    `active_time_idle_gap_seconds` 이하의 간격을 계속 만들어 **자리를 비운 시간을
    학습 시간으로 누적시킨다.** 이 오염은 화면에 드러나지 않는다 --- 진행바는
    오히려 매끄럽게 움직이고, 틀어지는 것은 `active_seconds`의 의미뿐이다.
-   `GET /api/study/session`이 이 용도로 안전한 이유는 **그것이 `touch()`를 하지
    않기 때문이다.** 이 endpoint는 조회이므로 `last_activity_at`도
    `active_seconds`도 옮기지 않고 idle timeout도 적용하지 않는다. 진행 표시가 이
    성질에 의존하므로 **여기에 상태 변경을 추가하지 않는다.**
-   따라서 `GET /session`이 돌려주는 `active_seconds`는 마지막 상태 변경 시점의
    값이다. 문장을 읽는 동안에는 진행바가 멈춰 있고 `/complete` 뒤에 한 칸
    움직인다. 이것은 결함이 아니라 `active_seconds`의 정의 그대로다.

## Sentence Presentation Payload

`POST /session/{id}/next`의 최소 응답:

``` json
{
  "presentation_id": 4821,
  "sentence_id": 1907,
  "japanese": "今日は研究室に行くつもりだったけど、なんとなく気が乗らなくて家にいた。",
  "render_segments": [
    {"text": "今日は", "sentence_item_id": null,
     "ruby": [{"text": "今日", "reading": "きょう"}, {"text": "は", "reading": null}]},
    {"text": "なんとなく", "sentence_item_id": 5511, "ruby": []},
    {"text": "気が乗らなくて", "sentence_item_id": 5512,
     "ruby": [{"text": "気", "reading": "き"}, {"text": "が", "reading": null},
              {"text": "乗", "reading": "の"}, {"text": "らなくて", "reading": null}]},
    {"text": "家にいた。", "sentence_item_id": null,
     "ruby": [{"text": "家", "reading": "いえ"}, {"text": "にいた。", "reading": null}]}
  ],
  "presentation_role": "review",
  "review_reason": "fsrs_due",
  "context_stage": "near_original",
  "translation_revealed": false,
  "tappable_items": [
    {"sentence_item_id": 5511, "learning_item_id": 771},
    {"sentence_item_id": 5512, "learning_item_id": 772}
  ],
  "probe": null
}
```

-   `render_segments`는 서버가 code point offset을 이미 적용해 만든
    렌더링용 목록이다. **Frontend가 JavaScript UTF-16 index를 직접
    계산하게 만들지 않는다**(`04_DB_SPEC.md`의 `sentence_item_spans`).
-   **번역은 reveal 전 응답에 포함하지 않는다.** reveal API 호출 후
    반환하여 `translation_revealed` event가 의미 있게 남도록 한다.
-   `probe`가 non-null이면 해당 presentation에 probe를 함께 표시한다.
-   `ruby`는 MVP-02에서 더한 후리가나 표시 조각이다(아래 `render_segments[].ruby`).

### `render_segments[].ruby` (MVP-02 확정)

각 segment에 후리가나 표시 조각 `ruby`를 싣는다. 출처는 `sentences.ruby_json`이다
(`04_DB_SPEC.md`의 `ruby_json`). 결정 배경은 ADR-021이다.

``` json
"render_segments": [
  {"text": "この仕事、田中さんに", "sentence_item_id": null,
   "ruby": [{"text": "この", "reading": null}, {"text": "仕事", "reading": "しごと"},
            {"text": "、", "reading": null},   {"text": "田中", "reading": "たなか"},
            {"text": "さんに", "reading": null}]},
  {"text": "任せ", "sentence_item_id": 5511,
   "ruby": [{"text": "任", "reading": "まか"}, {"text": "せ", "reading": null}]},
  {"text": "てもいい", "sentence_item_id": 5512, "ruby": []},
  {"text": "？", "sentence_item_id": null, "ruby": []}
]
```

``` text
RubyPart          {text: string, reading: string | null}
RenderSegment     {text, sentence_item_id, ruby: RubyPart[]}

R1  ruby는 [] 이거나, parts의 text를 이으면 segment.text와 같다
R2  segment 안에 ruby span이 하나도 없으면 []. 있으면 segment 전체를 덮는 parts
R3  part.text는 비어 있지 않다. reading이 null인 인접 part는 하나로 합친다 (정규형)
R4  reading은 비어 있지 않은 히라가나 문자열이다
R5  ruby_json이 NULL이면 모든 segment의 ruby = []
R6  표시 시점에 저장값을 다시 검증한다. 다음 중 하나라도 어기면 모든 segment의 ruby = [] 이고
    로그 ruby.invalid_stored를 남긴다. 500을 내지 않는다
      - spans가 배열이고 각 원소가 [정수, 정수, 문자열] 모양이다 (아니면 저장값 무효)
      - 모든 span이 원문 codepoint 범위 안이고 start < end
      - start 오름차순이고 서로 겹치지 않는다
      - 어떤 span도 is_tappable span의 경계를 넘지 않는다 (안에 있거나 완전히 밖)
      - reading이 비어 있지 않고 히라가나 코드포인트(U+3041..U+3096, ゝ ゞ ー)만으로 되어 있다
R7  후리가나 토글 상태와 무관하게 항상 싣는다
```

-   **서버가 자른다**(`app/render.py`). 좌표 `[start, end, reading]`을 payload에 싣지 않는다. frontend가
    code point를 UTF-16 index로 바꾸지 않는다는 위 규칙이 ruby에도 그대로 적용된다.
-   **`null`을 쓰지 않는다.** 한자 없음, 생략, 미계산, 저장값 무효는 모두 `[]`이고 frontend는 넷을 구분하지
    않는다. 네 경우의 화면 동작이 "그 segment는 글자만 그린다" 하나다.
-   **R2의 `[]`는 "달 것이 없다"만 뜻한다.** `[{"text": "てもいい", "reading": null}]`로 보내지 않는다.
    정규형이 하나여야 demo fixture와 API 출력의 일치 테스트가 결정적이다.
-   **R6이 500이 아닌 이유:** 표시 보조가 학습을 막지 않는다. tappable span 오류(`RenderSpanError`)는
    여전히 500이다 --- 그것은 탭 대상 자체가 틀린 것이다.
-   **R7:** 토글은 브라우저 localStorage에만 있고 서버로 가지 않는다. 서버는 토글을 모르므로 조건부로 실을
    수 없고, 조건부로 싣게 하려면 토글을 요청에 실어야 해서 불변식 16을 어긴다.
-   **API 요청 경로는 분석기를 import하지 않는다.** 저장된 값을 자르기만 한다(불변식 15,
    `spec/02_ARCHITECTURE.md`).
-   ruby는 **학습 신호가 아니다.** 싣는다고 event·exposure·evidence가 생기지 않는다
    (`02_LEARNING_POLICY.md`의 `학습 신호가 아닌 것 (MVP-02)`).
-   probe의 `expression`과 Explanation 응답(`canonical_form`, `reading`, `example_sentence`)에는 ruby가 없다.
    표시 범위는 학습 문장뿐이다(`03_UI_UX_SPEC.md`의 `Translation/Furigana`).

``` json
"probe": {
  "probe_id": 318,
  "learning_item_id": 773,
  "prompt": "이 표현을 알고 계세요?",
  "expression": "気が乗らない",
  "options": ["known", "uncertain", "unknown", "skip"]
}
```

### Mastery Probe

probe를 **언제** 싣는지는 `06_LEARNING_ENGINE.md`의 `Probe Pacing`이
canonical이다.

``` text
probe_id = 이 probe를 낸 mastery_probe_shown learning_event의 id (정수)
```

전용 probe 테이블은 만들지 않는다(`04_DB_SPEC.md`의
`probe 상태를 어디에 두는가`, ADR-009). probe를 실을 때 서버는
`mastery_probe_shown` event를 먼저 기록하고 그 id를 응답에 싣는다. 그
event의 idempotency key는
`uuid5(NC_EVENT_NAMESPACE, "mastery_probe_shown:{pid}:{learning_item_id}")`
이므로, 같은 presentation을 `열린 presentation 불변식`으로 다시 받아도
probe event와 `probe_id`가 **같은 값으로 유지된다.**

`POST /api/study/presentations/{pid}/probe-response`는 `probe_id`로
event를 조회해 다음을 모두 확인하고, 하나라도 어긋나면 **400**이다.

``` text
event_type            = mastery_probe_shown
user_id               = 요청 사용자
study_presentation_id = {pid}
```

-   응답 event(`mastery_probe_known | uncertain | unknown | skipped`)의
    `learning_item_id`는 **조회한 probe event의 값을 그대로 쓴다.**
    client가 보낸 값을 신뢰하지 않는다. 그래서 body에 별도
    `learning_item_id`를 받지 않는다.
-   같은 `probe_id`에 이미 응답 event가 있으면 새로 기록하지 않고 기존
    결과를 반환한다. probe 하나에 응답은 최대 1건이다. **실제 판정 키는
    `(presentation, learning_item)`이며** 위 자연키 때문에 지금은 두 표현이 같은
    결과를 낸다. 그 사실과 갈라지는 조건은 위 `판정 순서`에 있다.

## Interaction

``` text
POST /api/study/presentations/{pid}/items/{sentence_item_id}/click
     -> item_clicked 기록, precomputed explanation 반환
POST /api/study/presentations/{pid}/items/{sentence_item_id}/explanation-revealed
     -> explanation_revealed 기록
POST /api/study/presentations/{pid}/translation/reveal
     -> translation_revealed 기록, korean_translation 반환
POST /api/study/presentations/{pid}/self-report
     {sentence_item_id, value: known|uncertain|unknown}
POST /api/study/presentations/{pid}/probe-response
     {probe_id, value: known|uncertain|unknown|skip}
POST /api/study/presentations/{pid}/flag
     {reason: unnatural|wrong|too_easy|too_hard|other, note?}
POST /api/study/presentations/{pid}/complete
     -> sentence_completed 기록, meaningful exposure 확정
```

위 7개 endpoint는 전부 `세션·presentation 상태 게이트`를 먼저 통과한다.
닫힌 session이나 이미 완료된 presentation이면 409이고, `/complete`만 예외
규칙을 가진다.

`/self-report`와 `/probe-response`는 게이트를 통과한 뒤 `노출당 evidence 상한`을
한 번 더 통과한다. 그 노출에 이미 evidence가 있으면 409이며, 이 409는 게이트의
409와 **사유가 다르다**(같은 절의 `409 사유 구분`).

`/complete`는 `Next`를 누를 때 client가 **명시적으로** 호출한다
(`열린 presentation 불변식`). idempotency key는 presentation id 기반
server 발급이므로 body에 `client_event_id`를 받지 않고, 재호출해도
`sentence_completed`와 `item_exposures`가 중복 생성되지 않는다
(`item_exposures`의 `(study_presentation_id, learning_item_id)` unique).

Explanation 응답은 **precomputed DB data**(`sentence_item_explanations`)를
그대로 반환한다.

``` json
{
  "sentence_item_id": 5512,
  "learning_item_id": 772,
  "canonical_form": "気が乗らない",
  "reading": "きがのらなくて",
  "item_type": "expression",
  "core_meaning": "내키지 않다 / 할 마음이 나지 않다",
  "meaning_in_context": "연구실에 갈 생각이었지만 마음이 내키지 않았다",
  "nuance": "해야 할 이유는 있어도 의욕이 따라주지 않을 때 쓰는 일상 표현",
  "example_sentence": "今日はあまり出かける気が乗らない。",
  "example_translation": "오늘은 별로 나가고 싶지 않다."
}
```

`reading`은 **문장 속 표면형의 읽기**다(위 예시에서 span `気が乗らなくて`의 읽기). 기본형 `canonical_form`의
읽기가 아니다(`04_DB_SPEC.md`의 `sentence_item_explanations`).

해당 item에 explanation이 없으면 그 문장은 애초에 Ready가 아니다
(`08_LLM_SPEC.md`의 Ready invariant). 즉 이 endpoint는 **live LLM fallback을 하지
않는다.**

**Explanation의 `reading`과 문장 ruby의 관계(MVP-02).**

``` text
Explanation reading   sentence_item_explanations.reading. /click 응답에만 있다
                      item_clicked·explanation_revealed의 대상. MVP-02에서 바뀌지 않았다
문장 ruby             sentences.ruby_json에서 온 render_segments[].ruby
                      문장 전체 한자의 표시 보조. presentation 응답에 항상 있다. event를 만들지 않는다
```

-   ruby 계산은 tappable item의 span에 `explanation.reading`을 먼저 쓴다(ADR-021의 교정 계층 1). 그래서
    후리가나를 켜면 tappable 표현의 읽기가 탭하기 전에 보일 수 있고, 그 값은 대개 이 응답의 `reading`과
    같다. 어떤 정책도 "읽기를 보았는가"를 입력으로 쓰지 않으므로 `item_clicked`와
    `explanation_revealed`의 의미는 그대로다.
-   두 값이 어긋나도 이 응답의 `reading`을 고치지 않는다(`11_OBSERVABILITY.md`의
    `MVP-02 추가: 후리가나 계산 결과`).

### `explanation_revealed`를 언제 보내는가

**두 event의 시점 구분은 여기가 canonical이다.**

``` text
item_clicked           사용자가 tappable span을 탭한 직후 (설명을 요청했다)
explanation_revealed   떠나지 않은 학습 화면의 DOM에 설명 내용이 삽입된 직후 (설명이 표시됐다)
```

두 event를 모두 두는 이유는 **탭했지만 설명이 표시되지 않은 경우를 구분할 수 있게
하기 위해서다.** click 응답이 실패하거나(Ready invariant 위반의 500, 상태 게이트의
409, 네트워크 단절) 사용자가 응답 도착 전에 화면을 떠나면 `item_clicked`만 남는다.
하나로 합치면 그 구간이 관측되지 않고, "tap 즉시 표시"(`03_UI_UX_SPEC.md`)가
실제로 지켜지는지 확인할 수단이 사라진다.

-   `explanation_revealed`는 **표시된 뒤에** 보낸다. 탭과 동시에 보내면 두 event가
    항상 1:1이 되어 뒤엣것이 앞엣것의 복사본이 되고, 위의 구분이 불가능해진다.
-   **화면을 떠났으면 보내지 않는다(MVP-02).** `/click` 응답을 기다리는 동안 사용자가 화면을 떠나(상단바 앱
    이름, 뒤로 가기 등) 그 화면의 `signal`이 abort됐으면, 늦게 온 응답으로 설명을 그리지 않고
    `explanation_revealed`도 보내지 않는다. 위 "응답 도착 전에 화면을 떠나면 `item_clicked`만 남는다"가 그대로
    성립한다.
-   **"표시됐다"는 떠나지 않은 학습 화면의 DOM에 설명 내용이 삽입된 시점이다(MVP-02).** 설명 시트의 올라오는
    애니메이션이 끝나기를 기다리지 않는다. 끝을 기다리면 애니메이션이 끊기거나 종료 이벤트가 오지 않는
    환경(reduced-motion, 테스트)에서 event가 사라져, 같은 설명이 환경에 따라 기록되거나 안 되는 상태가
    된다(ADR-022, `03_UI_UX_SPEC.md`의 `설명 시트`).
-   같은 item의 패널을 접었다 다시 펴도 **한 presentation에서 1회만** 보낸다. client
    발급 key는 UUIDv4이므로 매번 보내면 그때마다 새 event가 쌓이고, raw history가
    학습 신호가 아니라 UI 조작 횟수를 세게 된다.
-   **설명 시트 재열기(MVP-02):** 시트를 닫고 같은 표현을 다시 탭해도 `item_clicked`와 `explanation_revealed`는
    **presentation + item당 1회**다. 두 번째 탭부터는 이미 받은 설명을 다시 보여주고 `/click`을 다시 부르지
    않으며 `explanation-revealed`도 보내지 않는다. 첫 `/click`이 실패해 설명을 받지 못한 경우의 다시 탭은
    재열기가 아니라 첫 요청의 재시도다. **presentation + item당 1회는 한 화면 mount 안에서의 보장이다.**
    새로고침이나 학습 기록 왕복 뒤 같은 presentation으로 돌아오면 다시 남을 수 있다(MVP-01부터의 동작이고 둘 다
    auxiliary signal이다).
-   둘 다 auxiliary signal이며 mastery도 FSRS rating도 만들지 않는다
    (`02_LEARNING_POLICY.md`의 `Auxiliary signal`, `07_SRS_SPEC.md`의
    `No-signal review`). 보내지 않아도 학습 진행은 막히지 않는다.

## History

``` text
GET /api/history/sessions        최근 session 요약 목록
GET /api/history/items           기본 learned/reviewed item summary
```

`00_SCOPE.md`가 `기본 history`를 In Scope로 두므로 두 endpoint의 응답 계약을 여기서
확정한다. 둘 다 **읽기 전용이다** --- 행을 만들지 않고, event를 남기지 않으며,
`last_activity_at`과 `active_seconds`를 건드리지 않는다.

-   둘 다 인증이 필요하다. 위 `익명 접근 허용 목록`에 없으므로 미인증 요청은 401이다.
-   응답은 **요청 사용자의 행만** 담는다. 대상 사용자를 지정하는 파라미터를 받지
    않는다 --- 받지 않으면 권한 검사를 빠뜨릴 자리 자체가 없다.
-   **새 테이블·새 컬럼·새 config 키를 만들지 않는다.** 아래 모든 필드가 기존
    컬럼에서 파생된다.

읽기 전용이라는 것의 귀결 하나를 적어 둔다. **진행 중인 session 행의
`active_seconds`는 마지막 학습 요청 시점의 값이고 history 조회로는 움직이지
않는다.** history는 `touch()`를 부르지 않기 때문이다 --- 부르면 기록을 들여다보는
행위가 학습 시간을 만들어낸다. 화면이 그 session을 `진행 중`으로 표시하므로
(`03_UI_UX_SPEC.md`의 `History`) 오해 소지는 작다.

**"학습 시간이 멈춰 보인다"를 이유로 여기에 상태 변경을 추가하지 않는다.** 그것은
고칠 버그가 아니라 `active_seconds`의 정의 그대로이며, `touch()`를 넣는 것이 실제
버그다. 위 `진행 상태의 갱신과 세션 종료 판정`이 `GET /api/study/session`에 대해
같은 문장을 두고 있다 --- 두 곳은 **한 규칙이다: 조회는 학습 시간을 만들지 않는다.**

### 개수 상한

``` text
history 응답 1건의 최대 행 수 = 50 (두 endpoint 공통, 고정)
```

**pagination·기간 필터·정렬 옵션을 두지 않는다.** `기본 history`는 "최근에 무엇을
했는가"를 보여주는 화면이고, cursor나 필터를 붙이는 순간 정렬 키·경계 처리·빈 페이지
같은 계약이 따라 붙는다. 상한을 넘으면 **오래된 것부터 잘린다.**

50은 학습 정책값이 아니라 **응답 계약 상수**이므로 `14_CONFIGURATION.md`에 두지
않는다. probe 문구나 flag note 길이 상한과 같은 취급이다 --- 실사용 관찰로 조정할
학습 파라미터가 아니고, 바꾸면 화면 계약이 바뀐다.

#### truncated

**잘렸다는 사실은 응답이 알린다.** 두 응답 모두 목록과 나란히 `truncated`를 싣는다.

``` text
truncated  bool   상한을 넘는 행이 존재해서 목록이 잘렸으면 true
```

이 필드가 없으면 명세가 이행 불가능한 것을 요구한다. **client가 가진 단서는
`len(rows) == 50`뿐이고 그것은 "정확히 50건인 사용자"와 구분되지 않는다.** 그
추정으로 문구를 띄우면 경계에서 거짓을 말한다 --- 잘리지 않았는데 화면이 잘렸다고
적는다.

판정 방법:

``` text
상한 + 1 건을 조회한다. 51번째 행이 있으면 truncated = true 이고
응답에는 앞의 50건만 담는다. 없으면 truncated = false 다.
```

-   **`COUNT(*)`를 추가하지 않는다.** 전체 개수는 화면이 쓰지 않는데, 행이 많은
    사용자는 조회마다 전수 카운트를 치른다. 한 행을 더 읽는 것으로 필요한 사실이
    전부 나온다.
-   **총 개수(`total`)를 응답에 넣지 않는다.** 화면이 요구하지 않고, 노출하면
    "몇 페이지인지 계산할 수 있다"는 이유로 pagination을 만들라는 압력이 된다. 위에서
    pagination을 금지한 것과 같은 결정이다.
-   `truncated`는 잘렸는지만 말하고 **몇 건이 잘렸는지는 말하지 않는다.** 그것을
    말하려면 `COUNT(*)`가 필요하다.

### GET /api/history/sessions

``` json
{
  "sessions": [
    {
      "session_id": 812,
      "started_at": "2026-09-12T09:02:11Z",
      "ended_at": "2026-09-12T09:15:40Z",
      "active_seconds": 703,
      "target_minutes": 12,
      "extended_minutes": 5,
      "completed_sentence_count": 9
    }
  ],
  "truncated": false
}
```

기존 컬럼에서의 파생:

``` text
session_id / started_at / ended_at / active_seconds
target_minutes / extended_minutes    study_sessions의 같은 이름 컬럼 그대로
completed_sentence_count             그 session의 study_presentations 중
                                     completed_at IS NOT NULL 인 행 수
```

-   정렬은 `started_at DESC, session_id DESC`다. 두 번째 키가 없으면 같은 시각의 두
    행 순서가 실행마다 달라져 화면이 흔들린다.
-   **아직 열려 있는 session도 목록에 포함한다.** 그때 `ended_at`은 `null`이다.
    빼면 오늘 진행 중인 세션이 기록에서 사라진다.
-   `completed_at IS NULL`인 presentation을 세지 않는 이유: idle timeout으로 닫힌
    session에는 영원히 미완료로 남는 행이 있고(위 `세션·presentation 상태 게이트`),
    그것을 세면 **보지 않고 떠난 문장이 학습 기록이 된다.** 이는 "부재를 완료로
    추론하지 않는다"와 같은 규칙이다.
-   `policy_snapshot_json`과 `summary_json`을 응답에 싣지 않는다. 전자는 설정값
    묶음이고(사용자에게 정책값을 노출하지 않는다), 후자는 MVP에 채우는 경로가 없다
    (`04_DB_SPEC.md`).

### GET /api/history/items

``` json
{
  "items": [
    {
      "learning_item_id": 772,
      "lemma": "気が乗らない",
      "item_type": "expression",
      "comprehension_mastery": 0.32,
      "exposure_count": 3,
      "next_review_at": "2026-09-14T09:00:00Z"
    }
  ],
  "truncated": false
}
```

기존 컬럼에서의 파생:

``` text
목록 대상              그 사용자의 user_item_learning_state 행
learning_item_id       user_item_learning_state.learning_item_id
lemma / item_type      learning_items.lemma / learning_items.type
comprehension_mastery  user_mastery.comprehension_mastery (행이 없으면 null)
exposure_count         invalidated_at IS NULL 인 item_exposures 행 수
next_review_at         review_states.next_review_at (행이 없으면 null)
```

-   목록 대상을 `user_item_learning_state`로 잡는 이유: 이 행은 그 item이 **target으로
    제시되었을 때**(exposure 기록, 무신호 처리) 또는 **explicit evidence를 받았을
    때**(승격, probe 응답) 생긴다. 그래서 눌러만 보고 지나간 item은 들어오지 않고
    사용자가 실제로 학습·복습한 item만 남는다. "learned" 플래그 컬럼을 새로 만들
    필요가 없다.
-   `exposure_count`는 cache(`review_states.meaningful_exposure_count`)가 아니라
    canonical source인 `item_exposures`를 센다(`07_SRS_SPEC.md`의
    `Meaningful Exposure 정의`). history는 학습 결정에 영향을 주지 않는 표시이므로
    cache를 읽어도 그 절의 규칙 위반은 아니지만, flag 직후 cache 재계산이 어긋난
    창에서 무효화된 노출이 그대로 보인다.
-   `listening_mastery`를 싣지 않는다. MVP에서 항상 NULL이므로 화면에 뜻이 없고,
    0으로 보일 위험만 있다(`00_SCOPE.md`).
-   `comprehension_mastery`가 `null`이면 **"아직 evidence 없음"**이다. 0으로 바꿔
    내리지 않는다(`02_LEARNING_POLICY.md`).
-   정렬은 `user_item_learning_state.updated_at DESC, learning_item_id DESC`다.
    최근에 움직인 item이 위로 온다.
-   통계·차트·기간 선택·item별 상세 화면은 MVP 밖이다(`00_SCOPE.md`의
    `advanced analytics`). 이 응답에 집계 필드를 더하지 않는다.

## Operational

``` text
GET /api/health                  FastAPI/DB/worker heartbeat 상태
```

인증 없이 호출할 수 있다(위 `익명 접근 허용 목록`). 대신 **사용자
데이터와 설정값을 노출하지 않는다.**

health는 의존성 상태와 무관하게 **항상 HTTP 200**을 반환하고, 판정은
body의 `status`로 표현한다. 모니터링이 "앱이 응답은 한다"와 "의존성이
성하다"를 구분할 수 있어야 하기 때문이다.

``` json
{
  "status": "ok",
  "checked_at": "2026-09-11T09:00:00Z",
  "version": "0.1.0",
  "components": {
    "api": {"status": "ok"},
    "database": {"status": "ok", "latency_ms": 3},
    "worker": {"status": "unknown", "last_heartbeat_at": null}
  }
}
```

``` text
status                      ok | degraded
checked_at                  UTC ISO-8601
version                     애플리케이션 버전 문자열
components.api.status       ok
components.database.status  ok | down | unknown     + latency_ms nullable
components.worker.status    unknown | ok | stale    + last_heartbeat_at nullable
```

-   `database.unknown`은 DSN이 설정되지 않아 확인하지 않았다는 뜻이다.
    `down`은 확인했고 실패했다는 뜻이다.
-   `status = degraded`는 component 중 하나 이상이 `down` 또는
    `stale`일 때다. `unknown`은 그 자체로 `degraded`가 아니다.
-   **DB 오류 원문, DSN, credential, host/port를 응답에 넣지 않는다**
    (`spec/04_SECURITY_AND_DATA.md`). 상세는 서버 로그로만 남긴다.
-   `version`에 빌드 환경 변수나 설정값을 덧붙이지 않는다.

**worker heartbeat의 저장 위치는 Wave 3에서 확정했다.**
`worker_heartbeats` 테이블의 `last_heartbeat_at` **최대값 하나**를 읽는다
(`04_DB_SPEC.md`, `09_BACKGROUND_JOBS.md`의 `Worker Heartbeat`,
ADR-015).

``` text
행이 없다                                                -> unknown
now - last_heartbeat_at <= jobs.heartbeat_stale_seconds  -> ok
그 밖                                                     -> stale
```

-   `unknown`은 worker가 한 번도 heartbeat를 쓴 적이 없다는 뜻이다(예:
    worker를 아직 띄우지 않은 개발 환경). 위 규칙대로 그 자체로는
    `degraded`가 아니고, `stale`은 `degraded`다.
-   임계값은 `14_CONFIGURATION.md`의 `jobs.heartbeat_stale_seconds`다.
    **응답에 임계값이나 worker 이름, provider 이름을 넣지 않는다**(이
    endpoint는 설정값을 노출하지 않는다).
-   DB를 확인할 수 없으면 `database`가 `down | unknown`이고 worker도
    `unknown`이다. worker 상태를 위해 별도 연결을 만들지 않는다.

## API Principles

-   Browser never receives OpenAI secret.
-   Normal item tap should not depend on live LLM response.
-   API response schema를 명확히 정의하고 frontend와 backend 사이의
    implicit state를 최소화한다.
-   모든 event는 `client_event_id` 기반 idempotency를 가진다. 발급 주체는
    event_type마다 고정이며 위 `event idempotency key`가 canonical이다.
