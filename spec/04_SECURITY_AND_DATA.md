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

### LLM provider 자격증명 (MVP 확정)

``` text
LLM_PROVIDER = openai            기본값 없음. 미설정이면 worker 부팅 실패
LLM_API_KEY  = provider secret   LLM_PROVIDER = openai 일 때 필수
```

-   둘 다 `.env` 계열 환경변수다. 학습 정책이 아니라 배포·secret 설정이므로
    `spec/mvp-01-core/14_CONFIGURATION.md`의 YAML에 두지 않는다(`APP_ENV`와
    같은 취급). 모델명은 이 둘 어디에도 없고 `prompt_versions` 행에서 온다
    (`spec/mvp-01-core/08_LLM_SPEC.md`의 `Provider 선택과 model 출처`).
-   **`LLM_API_KEY`는 worker 프로세스에만 주입한다.** FastAPI 프로세스는
    provider client를 만들지 않으므로(같은 문서의 `LLM 호출 경계`) 키가
    필요 없고, 주지 않는 것이 그 경계를 배포 수준에서 한 번 더 강제한다.
-   **허용값은 실제 provider 이름뿐이고 MVP에는 `openai` 하나다.** mock을
    가리키는 값은 없다 --- 실제 키 없이 generation 경로를 실행하는 수단은
    env 값이 아니라 **worker 진입점에 provider를 주입하는 것**이며 그 mock은
    `backend/tests/`의 test double이다(`spec/mvp-01-core/08_LLM_SPEC.md`의
    `Provider 선택과 model 출처`). 앱 코드에 mock 구현이 없으므로
    production이 mock으로 도는 일은 런타임 검사가 아니라 구조로 불가능하다.
-   **fail-closed 부팅 검사는 두 가지다.** `LLM_PROVIDER`가 없거나 허용값이
    아니면 worker가 부팅에 실패한다. `LLM_PROVIDER = openai`인데
    `LLM_API_KEY`가 없어도 부팅 실패다. 어느 쪽도 조용히 다른 값으로
    승격시키지 않는다 --- 그러면 운영자가 모르는 사이에 유료 호출 경로가
    열린다.
-   **기본값을 두지 않는 이유**는 값을 잊은 환경에서 유료 호출이 먼저
    일어나지 않게 하기 위해서다. 기본값 `openai`는 키가 어쩌다 존재하는
    개발 머신에서 곧바로 호출을 시작시킨다. 값이 없을 때의 결과는 "worker가
    뜨지 않는다"이고 학습 세션은 Ready Pool로 계속 돈다.
-   **환경변수를 읽는 지점은 worker 진입점 하나다.** 진입점이 두 값을 읽어
    `build_provider(name, api_key=...)`로 client를 만들고 worker loop에
    인자로 넘긴다. `app/llm/`은 환경을 읽지 않는다(ADR-015의 G11(a)).
-   PWA bundle과 API 응답에 이 값들을 노출하지 않는다. `/api/health`도
    provider 이름을 반환하지 않는다.

근거와 버린 대안은 `docs/decisions/ADR-016-llm-provider-selection.md`(원안의
`stub` env 값을 폐기한 이유는 그 문서의 `개정` 절).

### 학습 정책 파일 경로 (MVP 확정)

``` text
NC_CONFIG_PATH = 학습 정책 YAML 파일 경로    미설정(빈 값 포함)이면 config/default.yaml
```

-   `.env` 계열 환경변수다. 파일의 **내용**은 학습 정책이고 canonical 정의는
    `spec/mvp-01-core/14_CONFIGURATION.md`이지만, **어느 파일을 읽는가**는
    배포마다 다른 설정이므로 `APP_ENV`와 같은 취급이다.
-   경로는 그 값을 읽는 프로세스가 보는 경로다(컨테이너로 돌리면 컨테이너 안의
    경로). **API와 worker는 같은 파일을 읽는다.** 두 프로세스가 같은 정책 키를
    서로 다른 쪽에서 소비하므로(예: `max_new_items_per_sentence`는 API의
    materialization과 worker의 validation이 함께 쓴다) 파일이 갈리면 두 경로의
    판정이 갈린다.
-   production이 이 변수로 무엇을 가리키는지, 그 파일을 어떻게 만들고
    갱신하는지는 `spec/mvp-01-core/14_CONFIGURATION.md`의
    `production override (MVP 확정)`이 canonical이다.

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

#### 쿠키 속성이 배포 토폴로지에 요구하는 조건

**도메인을 고르기 전에 읽어야 하는 제약이다.** 위 `Session Cookie (MVP 확정)`의
속성은 설정값이 아니므로(같은 절의 `이름과 속성은 설정값이 아니다`) 배포 쪽이
여기에 맞춰야 한다. 네 가지가 따라온다.

-   `SameSite=Strict`는 site가 다른 요청에 cookie를 **싣지 않는다.** fetch에
    `credentials: 'include'`를 붙여도 우회되지 않는다 --- `include`는 same-site
    요청에 cookie를 싣게 하는 것이지 `SameSite` 판정을 바꾸는 것이 아니다.
-   `__Host-` prefix는 `Domain` 속성을 금지하므로 cookie는 **API 호스트
    전용**이다. 형제 subdomain으로 넓힐 수단이 없다.
-   따라서 **frontend origin과 API origin이 same-site(같은 registrable domain)
    여야 하고 둘 다 https여야 한다.** `app.example.com` + `api.example.com`은
    동작한다. frontend를 무료 호스팅의 공용 도메인(`*.workers.dev`,
    `*.pages.dev`, `*.netlify.app` 등)에 두고 API를 별도 도메인에 두는 조합은
    두 origin이 서로 다른 site이므로 **구조적으로 동작하지 않는다.** cookie
    속성을 낮추는 것은 해법이 아니다(같은 절).
-   추가로 frontend origin이 `CORS_ALLOW_ORIGINS`에 없으면 모든 상태변경 요청이
    막힌다. 도메인을 정한 뒤 이 환경변수에 **정확한 origin**을 넣어야 한다
    (wildcard 금지).

실제 도메인 값은 이 명세가 정하지 않는다. 터널·DNS·정적 호스팅 설정은 배포
절차의 몫이며 `infra/`에 도메인을 고정하지 않는다. 위 `로컬 개발`이 같은 제약의
개발 환경 판본이다.

## 데이터 보존

PostgreSQL이 canonical source이다. DB 내부 파일을 직접 편집하지 않는다.

## Backup

정기 pg_dump + rotation + 가능하면 다른 물리 디스크/위치에 최소 1개.
restore 절차도 실제 검증한다.

### 주기와 보관 개수 (MVP 확정)

``` text
주기        하루 1회
보관 개수   최근 7개   (백업 명령의 보관 개수 인자, 기본값 7)
위치        data/backups/   (spec/02_ARCHITECTURE.md)
```

-   **두 값은 운영값이며 학습 정책값이 아니다.** 그래서
    `spec/mvp-01-core/14_CONFIGURATION.md`의 YAML에 두지 않는다. 그 파일은
    API·worker가 전 키를 읽어 검증하는 학습 정책 파일인데, 두 값을 쓰는 것은
    백업 명령뿐이고 API·worker는 쓰지 않는다. 실사용 후 튜닝하는 학습값과 섞이지도
    않는다.
-   **환경변수에도 두지 않는다.** `.env` 계열 값은 API·worker 프로세스가 받는
    설정인데(`APP_ENV`, `AUTH_SESSION_TTL_DAYS`) 두 프로세스가 쓰지 않는 값을 거기
    두면 소비처 없는 설정이 생긴다. 보관 개수는 **백업 명령의 인자**이고 기본값이
    7이다.
-   **주기는 저장소가 가진 값이 아니다.** 백업 명령을 하루 1회 실행하는 것은 호스트
    스케줄러 설정이며, 위 `배포 계층 (운영자 책임)`의 Cloudflare 설정처럼 이
    저장소의 구현물이 아니다. 이 절은 그 설정이 따라야 할 값을 정한다.
-   하루 1회이므로 최악의 경우 **마지막 백업 이후 최대 하루치 기록**을 잃는다.
    사용자 1명 규모에서 받아들인다. 7개는 문제(잘못된 적용, 데이터 훼손)를 며칠
    늦게 알아채도 그 이전 상태가 남아 있는 창이다.
-   보관 단위는 **일이 아니라 개수**다. migration 직전 백업
    (`spec/mvp-01-core/04_DB_SPEC.md`의 `운영 DB에 migration을 적용하는 경로`)도
    같은 명령이 만들므로 한 개로 센다.
-   바꾸려면 이 절을 먼저 고친다.

### rotation 규칙 (MVP 확정)

``` text
순서   dump -> 새 백업 검증 -> rotation(보관 개수를 넘는 가장 오래된 것부터 삭제)
```

-   **오래된 백업은 새 백업의 검증이 끝난 뒤에만 지운다.** 먼저 지우면 dump가
    실패하는 날이 이어지는 동안 옛 백업만 줄어들어 **백업이 0개**가 될 수 있다.
-   새 백업의 검증이 실패하면 rotation을 하지 않고 명령이 non-zero로 끝난다.
    실패한 파일은 보관 개수에 세지 않는다.
-   dump 중인 파일은 검증이 끝나기 전까지 **완성된 백업의 이름으로 보이지 않게**
    쓴다(임시 이름으로 쓰고 검증 뒤 이름을 바꾼다). 중간에 끊긴 파일이 "최근
    백업"으로 세어져 온전한 옛 백업을 밀어내지 않게 하기 위해서다.
-   여기서 말하는 **새 백업 검증**은 파일이 온전하다는 것까지다: 덤프 도구가
    성공으로 끝났고, 파일이 비어 있지 않으며, 복원 도구가 그 파일의 목차를 끝까지
    읽을 수 있다. 복원된 데이터가 원본과 같다는 증명은 아래 `restore 검증`이다.

### restore 검증 (MVP 확정)

**복원 명령이 exit 0으로 끝난 것은 검증이 아니다.** 테이블이 빠지거나 행이 비어도
복원 명령은 성공할 수 있다. restore 검증은 다음 여섯 가지를 **모두** 보여야 한다.

``` text
1. alembic_version   복원 DB와 원본의 값이 같고, 그 값이 migration head다
2. 테이블 내용       catalog에서 나열한 모든 public 테이블의 행 수와 내용 해시가 같다
3. sequence          모든 sequence의 last_value가 같다
4. 제약·index        제약 이름 집합과 index 이름 집합이 같다 (partial unique index 포함)
5. 동작              복원 DB에 붙인 API로 login과 history가 동작한다
6. 음성 대조군       복원본의 1행을 훼손하면 검증이 실패한다
```

-   **테이블 목록을 하드코딩하지 않는다.** 목록을 적어 두면 테이블이 추가된
    날부터 그 테이블은 검증 밖에 있게 되는데 검증은 계속 통과한다. 비교 대상은
    매번 catalog에서 나열한다.
-   4에 partial unique index를 명시하는 이유: `uq_study_presentations_open`,
    `uq_learning_events_evidence` 같은 index가 불변식의 DB 강제 수단인데
    (`spec/mvp-01-core/04_DB_SPEC.md`) 행 내용 비교로는 index가 빠진 것이
    드러나지 않는다.
-   **6이 없으면 1\~4는 아무것도 증명하지 않는다.** 항상 "같다"고 답하는
    검증(같은 DB를 두 번 읽는다, 해시에 행 내용이 들어가지 않는다)도 1\~4를
    통과한다.
-   **원본은 dump 시점부터 비교가 끝날 때까지 쓰기가 없어야 한다.** worker는 job이
    없어도 `worker_heartbeats`를 주기적으로 쓰고 API는 인증 요청에서
    `auth_sessions.last_used_at`을 쓰므로, 살아 있는 원본과 비교하면 2가 거짓으로
    실패한다. API·worker를 멈춘 상태에서 dump하고 비교한다.
-   **5는 1\~4가 끝난 뒤에 한다.** login이 `auth_sessions`에 행을 쓰므로 먼저 하면
    2가 실패한다.
-   복원은 **별도 DB**에 한다. 원본 DB를 덮어써서 검증하지 않는다.
-   `spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md`의 `backup/restore 최소 1회
    검증`이 가리키는 것이 이 여섯 가지다. 테스트 항목은
    `spec/mvp-01-core/12_TEST_PLAN.md`에 있다.

### 백업 파일의 민감도

-   백업에는 `users.password_hash`와 `auth_sessions.token_hash`가 들어 있다.
    password hash가 유출되면 추측 시도는 위 `온라인 무차별 대입 방어`의 2차
    방어(서버 처리량이 시도율의 상한)를 받지 않고 오프라인에서 병렬로 돈다. 남는
    방어는 1차(password 엔트로피)뿐이다.
-   백업 파일은 **권한 0600**(백업을 만든 운영 사용자만 읽기·쓰기)이다. 만든 뒤에
    권한을 줄이는 것이 아니라 만드는 시점부터 0600이어야 한다. 그 사이에 다른
    사용자가 읽을 수 있는 창이 생기지 않게 하기 위해서다.
-   백업은 Git에 넣지 않는다(아래 `Git 제외`, `spec/02_ARCHITECTURE.md`의
    `data/backups`). 다른 물리 디스크/위치의 사본도 같은 파일이므로 같은 권한으로
    다룬다.

## Git 제외

-   `.env`
-   DB volume
-   DB backup
-   실제 secret
-   사용자 개인 export

## Portability

장기적으로 vocabulary.csv, learning_history.json, sentences.json export
지원.
