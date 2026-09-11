# Security and Data

## Modes

-   Anonymous: Public Demo only, private mastery/history 접근 금지, paid
    LLM call 금지.
-   Authenticated: 실제 학습 시스템.

## Public Demo 구조 (MVP 확정)

Public Demo는 **완전한 static frontend fixture**다.

``` text
backend API 호출 없음
PostgreSQL write 없음
anonymous user row 없음
generation job 없음
provider client 없음
private user data 접근 가능 경로 없음
```

Demo interaction state는 browser memory/session 수준에서만 유지한다.
따라서 `sessions.mode = demo`, demo user, demo DB state 같은 설계는
사용하지 않는다.

이 구조로 다음이 성립한다.

``` text
Paid LLM call      = structurally impossible
Private DB access  = structurally impossible
```

## Security

-   단순하고 안전한 개인 로그인. password 평문 저장 금지.
-   cookie 기반 session 인증. 규격은 아래 `Session Cookie (MVP 확정)`이
    canonical이다.
-   OpenAI key와 DB credential은 server-side secret.
-   PWA bundle에 secret 금지.
-   FastAPI는 Tunnel로 공개, PostgreSQL은 외부 직접 노출 금지.
-   FastAPI 자동 문서 경로(`/docs`, `/redoc`, `/openapi.json`,
    `/docs/oauth2-redirect`)는 **기본 비활성**이다. Tunnel 너머 누구나
    private API 표면 전체(경로, 파라미터명, enum, 스키마)를 익명으로
    가져갈 수 있게 두지 않는다.

### 배포 환경 구분

환경 구분은 `APP_ENV` 환경변수로 한다. 학습 정책 값이 아니라 **배포
설정**이므로 `14_CONFIGURATION.md`의 YAML이 아니라 `.env` 계열에 둔다.

``` text
APP_ENV = local | development | production
기본값  = local
```

-   자동 문서 경로는 `APP_ENV = development`일 때만 연다. 값이 다르거나
    변수가 없으면 닫는다(**fail-closed**).
-   `APP_ENV`는 **배포 표면 제어에만** 쓴다. 학습 기능·정책·데이터 동작을
    환경에 따라 분기시키지 않는다.
-   인증 없이 열리는 API endpoint 목록은
    `spec/mvp-01-core/05_API_SPEC.md`의 공통 규칙이 canonical이다.

## Authentication (MVP 확정)

이 앱은 SaaS가 아니다.

-   public signup 없음.
-   private real user 한 명.
-   계정은 seed/admin CLI 또는 초기 setup 절차로 생성한다.
-   password는 **Argon2id 등 안전한 password hash**로 저장한다.
    최소 길이 등 password 요구사항은 아래
    `Password 요구사항 (MVP 확정)`이 canonical이다.
-   auth session은 `auth_sessions` 테이블에 저장한다(학습 세션
    `study_sessions`와 이름을 구분한다).
-   opaque random session token의 **hash만** DB에 저장한다.
-   session cookie의 이름·속성·수명은 아래
    `Session Cookie (MVP 확정)`이 canonical이다.

### Password 요구사항 (MVP 확정)

``` text
최소 길이     16 code point
검증 지점     계정을 만드는 경로 (현재 scripts/create_user.py)
검증 안 함    POST /api/auth/login
```

-   **복잡도 규칙(대문자/숫자/기호 혼용)을 두지 않는다.** 기계로 강제하는
    것은 길이 하한 하나다. 혼용 규칙은 `P@ssw0rd!` 같은 예측 가능한
    변형을 유도할 뿐 추측 비용을 올리지 못한다.
-   **금지어 목록과 유출 password 조회를 두지 않는다.** 목록은 wordlist
    의존성을, 유출 조회는 외부 네트워크 호출을 새로 만든다. 계정이 하나뿐인
    앱에서 비용이 이익보다 크다.
-   **최대 길이를 정하지 않는다.** Argon2id 비용은 password 길이에 거의
    비례하지 않으므로 상한이 막아주는 것이 없다.
-   password는 **password manager가 생성한 난수 또는 diceware 4단어
    이상**으로 만든다. 길이 하한은 이 관행을 강제하지 못하고 사람이 손으로
    고른 짧은 password만 차단한다. 나머지는 운영 규칙이며 계정 생성 CLI의
    도움말에 적는다.
-   **`POST /api/auth/login`은 이 정책을 검증하지 않는다.** 하한 미만
    password는 DB에 존재할 수 없으므로 검증할 것이 없고, login에서 길이를
    먼저 보면 실패 응답 시간이 갈려 추측 대상에 힌트를 준다.
-   하한을 16으로 잡은 이유는 **실사용자가 1명이고 계정 생성이 CLI
    1회**이기 때문이다. public signup의 UX 비용이 없으므로 일반적인
    하한(8)보다 높게 잡아도 치르는 비용이 없다.

#### 이 값은 설정값이 아니다

최소 길이는 `spec/mvp-01-core/14_CONFIGURATION.md`의 학습 정책 YAML에도
`.env`에도 두지 않는다. **코드에 고정한다.**

-   실사용 후 튜닝하는 학습 정책값이 아니다.
-   환경변수로 두면 "보안 하한을 낮추는 스위치"가 생긴다. `Secure`를 끄는
    플래그를 만들지 않기로 한 것과 같은 이유다(ADR-004).
-   바꾸려면 이 절을 먼저 고친다.

### 온라인 무차별 대입 방어 (MVP 확정)

MVP는 **애플리케이션 레벨 시도 횟수 제한·계정 잠금·실패 지연을 두지
않는다.** 방어는 다음이 전부다.

``` text
1차   password 엔트로피 하한 (위 Password 요구사항)
2차   Argon2id 검증 비용 --- 서버 처리량 자체가 시도율의 상한
선택  배포 계층(Cloudflare) rate limit --- 운영자가 직접 설정한다
```

전제 조건은 다음과 같다. 계정 1개, public signup 없음, `login_id`는 추측
가능, API는 Tunnel로 인터넷에 공개.

#### 왜 password 쪽을 고치는가

``` text
Argon2id 검증 비용   요청당 약 39ms (측정값, argon2-cffi 기본 파라미터)
단일 스레드 시도율   약 25/초 = 약 2.2e6/일
```

-   시도율은 이미 이 수준으로 묶여 있다. 여기서 부족한 것은 **속도 제한이
    아니라 탐색 공간**이다. 약한 password는 이 속도로도 뚫리고, password
    manager 난수 16자는 이 속도로 전수 탐색이 불가능하다.
-   rate limit은 약한 password의 수명을 늘릴 뿐 강한 password에 더해주는
    것이 없다. 그래서 MVP는 password 쪽을 고정한다. 비용은 계정 생성 때
    한 번이고 새로 생기는 상태가 없다.
-   Argon2id 파라미터를 이 문서에 명세값으로 못박지 않는다. 위 수치는
    라이브러리 기본값에서 측정한 **근거**이지 요구사항이 아니다.

#### 버린 대안과 그 이유

-   **계정 잠금(lockout)**: 계정이 하나라서 잠금은 곧 주인에 대한 DoS다.
    공격자가 일부러 틀리기만 하면 정당한 사용자가 잠긴다. 잠금 해제 경로를
    만들면 그 경로가 새로운 공격 표면이 된다.
-   **DB 기반 실패 카운터**: 새 테이블/컬럼 + migration + 정리 작업이
    필요하고, 인증되지 않은 요청마다 write 경로가 열려 공격자가 DB 쓰기를
    유발할 수 있게 된다. `users`와 `auth_sessions` 어느 쪽에도 실패
    카운터·잠금 시각 컬럼을 **두지 않는다**
    (`spec/mvp-01-core/04_DB_SPEC.md`).
-   **in-process 메모리 카운터**: worker 프로세스 수에 따라 실제 한도가
    달라지고 재시작하면 사라진다. 정확한 값을 보장하지 못하는 상태를 인증
    경로에 새로 만들지 않는다.
-   **Redis 기반 rate limit**: MVP는 Redis를 쓰지 않는다(ADR-001). 이
    기능 하나를 위해 인프라 구성요소를 늘리지 않는다.

#### Origin 검증은 이 방어가 아니다

`state-changing request`의 strict Origin 검증(아래 `배포 도메인 가정`)은
**브라우저가 규칙을 강제할 때만** 효력이 있다. curl 같은 비브라우저
클라이언트는 `Origin` 헤더를 임의로 붙일 수 있으므로 무차별 대입을 막지
못한다. CSRF 방어와 무차별 대입 방어를 같은 것으로 읽지 않는다.

#### 배포 계층 (운영자 책임)

-   Cloudflare Tunnel 앞단에서 `POST /api/auth/login`에 rate limiting을
    거는 것을 권장한다.
-   **이 설정은 이 저장소의 구현물이 아니다.** 외부 서비스 설정이므로
    명세·코드·테스트로 강제할 수단이 없고, 이 명세는 그것이 켜져 있다고
    **가정하지 않는다.**
-   **설정하지 않으면 `POST /api/auth/login`은 초당 수십 회의 추측 시도를
    그대로 받는다.** 그 상태에서 남는 방어는 위 1차·2차뿐이다. 이 사실을
    숨기지 않고 여기 적는다. 그래서 1차 방어를 운영자 설정에 의존하지 않는
    password 하한으로 둔 것이다.
-   로그인 실패 시도 로그와 알림은 MVP에 두지 않는다. 위 시도율에서 실패마다
    한 줄을 남기면 로그 자체가 디스크 압박이 된다
    (`spec/mvp-01-core/11_OBSERVABILITY.md`).

#### 다시 열어야 하는 조건

다음 중 하나라도 성립하면 이 결정을 다시 검토한다.

``` text
사용자가 2명 이상이 된다
public signup이 생긴다
password 하한을 낮춘다
로그인 실패 관측 수단이 생긴다 (Future)
```

결정 배경은 `docs/decisions/ADR-006-online-brute-force-defense.md`.

#### 수용된 위험 --- login endpoint의 메모리 비용

`POST /api/auth/login`은 익명 요청마다 Argon2id 메모리를 잡는다. 기본
파라미터가 `m=65536`(요청당 64MiB)이고 FastAPI 기본 threadpool이 40이면
동시 로그인 요청만으로 약 2.5GB를 요구할 수 있다. **MVP는 이 위험을
방어하지 않고 받아들인다.**

-   무차별 대입이 아니라 **자원 고갈(가용성)** 문제다. 사용자가 1명인 개인
    앱에서 실제 피해는 "잠시 학습을 못 한다"이며 데이터·인증 표면은 그대로다.
-   세마포어나 동시 실행 제한은 지금 **단일 사용처를 위한 인프라**다. 넣지
    않는다.
-   **Argon2 파라미터를 낮춰서 대응하지 않는다.** password hash 강도는 위
    1차·2차 방어의 한 축이다. 가용성을 이유로 그것을 깎으면 방어 방향이
    거꾸로 간다.
-   완화가 필요해지면 자연스러운 계층은 **배포 계층**이다(Tunnel 앞단의 동시
    연결·요청률 제한). 애플리케이션 동시성 제한은 그다음이다.
-   다시 검토하는 조건: 사용자가 2명 이상이 된다 / public signup이 생긴다 /
    이 경로를 통한 자원 고갈이 실제로 관측된다 / 서버 메모리가 동시 요청을
    감당하지 못한다.

### Session Cookie (MVP 확정)

``` text
이름      __Host-nc_session
속성      HttpOnly; Secure; SameSite=Strict; Path=/
Domain    지정하지 않는다 (host-only)
Max-Age   AUTH_SESSION_TTL_DAYS 일 (환경변수, 기본 30)
```

-   cookie 값은 opaque random token이고 DB에는 hash만 남는다(위).
-   **만료 판정의 canonical source는 `auth_sessions.expires_at`이다.**
    cookie `Max-Age`는 같은 값으로 맞추지만 브라우저 힌트일 뿐이다.
    서버는 매 요청에서 `expires_at`과 `revoked_at`을 확인하며, cookie가
    남아 있어도 DB session이 만료·폐기 상태면 401이다.
-   MVP는 **absolute expiry만** 쓴다. `auth_sessions.last_used_at`은
    기록하되 만료를 연장하지 않는다(sliding session 없음). 사용자가 한
    명이고 재로그인 비용이 낮으므로 갱신 로직을 두지 않는다.

#### 수명 값을 어디에 두는가

`AUTH_SESSION_TTL_DAYS`는 **`.env` 계열 환경변수**이고
`spec/mvp-01-core/14_CONFIGURATION.md`의 YAML이 아니다. 양의 정수이며
기본값은 30이다.

-   `14_CONFIGURATION.md`는 **학습 정책** 파일이다. 로더가 전 키를 읽고
    category 비율 합까지 검증한다. session 수명은 학습 정책이 아니라
    배포·보안 설정이므로 그 파일의 책임 범위 밖이다.
-   같은 이유로 이미 `APP_ENV`를 환경변수로 뒀다(위 `배포 환경 구분`).
    같은 성격의 값을 두 곳에 나눠 두지 않는다.
-   정책 YAML에 두면 "실사용 후 튜닝하는 학습값"과 "바꾸면 보안 표면이
    바뀌는 값"이 한 파일에 섞인다.

#### 이름과 속성은 설정값이 아니다

이름, `SameSite`, `Secure`, `Domain`은 **환경별 스위치를 두지 않는다.**
코드에 고정한다.

-   `Secure`는 **항상 켠다.** 끄는 플래그를 만들지 않는다. Chrome과
    Firefox는 `http://localhost`를 secure context로 취급해 `Secure`
    cookie를 저장하고 전송하므로 로컬 개발 때문에 끌 이유가 없다.
    `APP_ENV`는 **배포 표면 제어 전용**이라 보안 하향 플래그로 쓰면 위
    `배포 환경 구분`의 규칙과 충돌한다.
-   `SameSite=Strict`. 배포는 `jp.example.com` ↔ `api.jp.example.com`으로
    **동일 site**(같은 registrable domain)이므로 앱 자신이 보내는
    fetch에는 Strict에서도 cookie가 실린다. 반면 외부 site가 유발한
    요청에는 실리지 않아 CSRF 표면이 가장 좁다. `SameSite=None`은 쓰지
    않는다.
-   `Domain`을 **지정하지 않는다.** 지정하면 cookie가 frontend 정적
    호스트를 포함한 형제 subdomain 전체에 전송되어 노출 표면이 넓어진다.
    host-only가 좁다.
-   `__Host-` prefix는 위 세 결정(`Secure`, `Path=/`, `Domain` 미지정)을
    **브라우저가 강제**하게 만들고, 형제 subdomain이 같은 이름의 cookie를
    덮어써 세션을 바꿔치기하는 것을 막는다. 그래서 이름에 붙인다. 이
    prefix를 쓰는 한 세 속성은 어길 수 없다.

#### 로컬 개발

frontend와 API를 **같은 host 이름**으로 띄운다. `localhost:5173` ↔
`localhost:8000`은 port가 달라도 same-site이므로 `SameSite=Strict`
cookie가 전송된다. `127.0.0.1`과 `localhost`를 섞으면 서로 다른 site로
취급되어 cookie가 전송되지 않는다. 이 문제의 해법은 host 이름을 맞추는
것이지 cookie 속성을 낮추는 것이 아니다.

결정 배경은 `docs/decisions/ADR-004-session-cookie.md`.

### 배포 도메인 가정

``` text
frontend: jp.example.com
api:      api.jp.example.com
```

처럼 **동일 registrable domain** 아래에서 운영한다.

-   Frontend fetch는 `credentials: include`를 사용한다.
-   API CORS는 명시된 frontend origin만 허용한다. **wildcard 금지.**
-   state-changing request는 SameSite cookie policy, strict Origin
    검증, 필요한 CSRF 방어를 적용한다.

## 데이터 보존

PostgreSQL이 canonical source이다. DB 내부 파일을 직접 편집하지 않는다.

## Backup

정기 pg_dump + rotation + 가능하면 다른 물리 디스크/위치에 최소 1개.
restore 절차도 실제 검증한다.

## Git 제외

-   `.env`
-   DB volume
-   DB backup
-   실제 secret
-   사용자 개인 export

## Portability

장기적으로 vocabulary.csv, learning_history.json, sentences.json export
지원.
