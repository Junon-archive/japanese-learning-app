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
인증된 private user 전용이다.

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
POST /api/study/session/{id}/extend    +5분 연장  body: {client_event_id}
```

`/extend`만 body에 `client_event_id`를 받는다. 이유는 위
`event idempotency key`에 있다.

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

## Sentence Presentation Payload

`POST /session/{id}/next`의 최소 응답:

``` json
{
  "presentation_id": 4821,
  "sentence_id": 1907,
  "japanese": "今日は研究室に行くつもりだったけど、なんとなく気が乗らなくて家にいた。",
  "render_segments": [
    {"text": "今日は", "sentence_item_id": null},
    {"text": "なんとなく", "sentence_item_id": 5511},
    {"text": "気が乗らなくて", "sentence_item_id": 5512},
    {"text": "家にいた。", "sentence_item_id": null}
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
    결과를 반환한다. probe 하나에 응답은 최대 1건이다.

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
  "reading": "き が のらない",
  "item_type": "expression",
  "core_meaning": "내키지 않다 / 할 마음이 나지 않다",
  "meaning_in_context": "연구실에 갈 생각이었지만 마음이 내키지 않았다",
  "nuance": "해야 할 이유는 있어도 의욕이 따라주지 않을 때 쓰는 일상 표현",
  "example_sentence": "今日はあまり出かける気が乗らない。",
  "example_translation": "오늘은 별로 나가고 싶지 않다."
}
```

해당 item에 explanation이 없으면 그 문장은 애초에 Ready가 아니다
(`08_LLM_SPEC.md`의 Ready invariant). 즉 이 endpoint는 **live LLM fallback을 하지
않는다.**

## History

``` text
GET /api/history/sessions        최근 session 요약 목록
GET /api/history/items           기본 learned/reviewed item summary
```

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

**미결:** worker heartbeat를 어디에 저장하는지는 `04_DB_SPEC.md`에 아직
없다. 저장 방식은 **Wave 3(job queue 구현) 시점에 확정한다.** 그 전까지
`components.worker.status`는 `unknown`을 반환하며, 이를 위해 테이블이나
컬럼을 미리 만들지 않는다.

## API Principles

-   Browser never receives OpenAI secret.
-   Normal item tap should not depend on live LLM response.
-   API response schema를 명확히 정의하고 frontend와 backend 사이의
    implicit state를 최소화한다.
-   모든 event는 `client_event_id` 기반 idempotency를 가진다. 발급 주체는
    event_type마다 고정이며 위 `event idempotency key`가 canonical이다.
