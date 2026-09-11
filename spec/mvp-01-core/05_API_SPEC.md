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
-   상태 변경 event POST는 client가 생성한 `client_event_id`(UUID)를
    포함한다. 서버는 `(user_id, client_event_id)` unique로 중복 저장을
    막고, 재전송 시 동일 결과를 반환한다.
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
-   `probe_id`의 발급·저장 방식은 Wave 2에서 확정하지만, 확정 이후에도
    이 표현 규칙을 따른다.

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
POST /api/study/session/{id}/extend    +5분 연장
```

`POST /session`은 idle timeout 이내면 기존 세션을 resume하고, 초과면 새
세션을 만든다(`04_DB_SPEC.md`의 `study_sessions`,
`14_CONFIGURATION.md`의 `study_session_idle_timeout_minutes`).

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
-   event endpoint는 `client_event_id` 기반 idempotency를 가진다.
