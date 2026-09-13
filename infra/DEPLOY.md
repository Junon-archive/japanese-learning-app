# 운영 배포 가이드

이 문서 하나로 **빈 상태에서 운영 배포까지** 따라 할 수 있게 쓴다. 설계 근거는
`docs/decisions/ADR-020-production-topology.md`에 있고, 여기서는 "무엇을 어떤 순서로
치고 무엇을 확인하는가"만 적는다.

``` text
휴대폰/브라우저 ── https://<FRONTEND_HOST> ── Cloudflare Workers Static Assets (화면)
               └─ https://<API_HOST> ─────── 기존 cloudflared 터널 (이 호스트의 systemd)
                                                └─ http://127.0.0.1:8000  backend 컨테이너
                                                   worker 컨테이너 (OpenAI 호출은 여기서만)
                                                   postgres 컨테이너 ── 127.0.0.1:5432
운영 명령 (migration, 백업, 계정, seed, prompt) ── 이 호스트에서 uv run ──┘
```

**규칙 세 가지를 처음부터 끝까지 지킨다.**

1.  **각 단계의 확인이 통과하기 전에 다음 단계로 가지 않는다.**
2.  **대상 DB를 눈으로 확인한다.** 이 머신은 운영 호스트이자 개발 머신이다(2.3절).
3.  **compose 명령에는 서비스 이름을 항상 적는다.** 이름 없는 `up -d`, `down`은 쓰지 않는다.
    같은 이유로 `make db-up` / `make db-down`도 운영에서 쓰지 않는다.

compose 구성은 이 머신에서 운영과 분리된 project로 실제로 띄워 검증했다(ADR-020 결정 9, 19개 항목
통과). "검증되지 않았다"고 적힌 절차와 "확인 필요"로 적힌 외부 서비스(Cloudflare, OpenAI 대시보드,
wrangler) 동작만 확인하지 않은 것이다.

---

## 0. 값 채우기 표와 도메인 제약

### 0.1 값 채우기 표

문서의 `<...>`를 아래 값으로 바꿔 읽는다. **이 값들을 저장소의 어떤 파일에도 적지 않는다.**
실제 값이 놓이는 곳은 `.env`(Git 제외), `~/.cloudflared/config.yml`(저장소 밖), Cloudflare
대시보드, 빌드 셸의 환경변수뿐이다.

| 자리표시자 | 뜻 | 예시 형태 (실제 값 아님) | 내 값 (종이·password manager에만) |
|---|---|---|---|
| `<ZONE>` | Cloudflare에 올린 사용자 도메인 | `example.com` | |
| `<FRONTEND_HOST>` | 화면용 1단계 서브도메인 | `app.example.com` | |
| `<API_HOST>` | API용 1단계 서브도메인 | `api.example.com` | |
| `<TUNNEL_NAME>` | 기존 터널 이름(또는 UUID) | `~/.cloudflared/config.yml`의 `tunnel:` 값 | |
| `<TUNNEL_SERVICE>` | 기존 터널을 돌리는 systemd 서비스 이름 | `systemctl list-units --type=service \| grep -i cloudflared` | |
| `<WORKER_NAME>` | Cloudflare Workers 이름 | `nihongo-context` | |
| `<LOGIN_ID>` | 앱 로그인 id | 영소문자·숫자·`._+@-`, 3\~64자 | |
| `<POSTGRES_USER>` | DB 사용자 이름 | `nihongo` | |
| `<POSTGRES_DB>` | DB 이름 | `nihongo` | |

아래는 이 호스트에서 정해지는 값이다. secret이 아니다.

| 자리표시자 | 값 |
|---|---|
| `<REPO>` | 이 저장소의 절대경로 (`cd`한 뒤 `pwd`) |
| `<PG_BIN>` | `<REPO>/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin` (pg_dump 16.2, ADR-020 결정 2) |
| `<UV>` | `command -v uv`의 절대경로 (cron용) |
| `<WRANGLER_VERSION>` | 배포 때 고정할 wrangler 버전 (6절) |
| `<COMPAT_DATE>` | Workers compatibility date, `YYYY-MM-DD` (6절) |
| `<PREV_COMMIT>` | 업데이트 직전에 운영 중이던 커밋. `git pull` 전에 `git rev-parse --short HEAD`로 적어 둔다 (17절) |
| `<BACKEND_IMAGE>` | `C images backend`의 REPOSITORY 열 (17절) |
| `<WORKER_IMAGE>` | `C images worker`의 REPOSITORY 열 (17절) |
| `<SAFETY_BACKUP_DIR>` | 10.2에서 출력된 `safety backup dir:` 값 (`data/backups/pre-restore/<UTC>`) |
| `<PRE_MVP02_BACKUP_DIR>` | 17.4에서 출력된 `pre-mvp02 backup dir:` 값 (`data/backups/pre-mvp02/<UTC>`) |

secret은 표에 적지 않는다: `<POSTGRES_PASSWORD>`, `<OPENAI_API_KEY>`, 앱 로그인 password.

### 0.2 도메인 제약 (도메인을 고르기 전에 읽는다)

세션 cookie는 `__Host-nc_session; HttpOnly; Secure; SameSite=Strict`이고 코드에 고정되어
있다(`spec/04_SECURITY_AND_DATA.md`의 `쿠키 속성이 배포 토폴로지에 요구하는 조건`). 그래서
배포가 여기에 맞춰야 한다.

1.  **same-site.** `<FRONTEND_HOST>`와 `<API_HOST>`는 같은 `<ZONE>` 아래여야 한다.
    `SameSite=Strict` cookie는 site가 다른 요청에 실리지 않는다.
2.  **1단계 서브도메인.** Cloudflare Universal SSL 인증서는 `<ZONE>`과 `*.<ZONE>`만 덮는다.
    `app.<ZONE>`은 되고 `app.x.<ZONE>`은 인증서가 없어 https가 실패한다.
3.  **둘 다 https.** `Secure` cookie이고, iOS Safari는 https 주소에서만 로그인이 된다.

**`*.workers.dev` 주소로는 로그인이 안 된다.** 그 주소는 `<ZONE>`과 다른 site라서 cookie가
실리지 않고 `CORS_ALLOW_ORIGINS`에도 없다. 화면은 뜨지만 로그인은 구조적으로 불가능하다.
그래서 6절에서 `workers.dev` 주소를 끈다.

---

## 1. 사전 확인

### 1.1 도구

``` sh
docker --version
docker version --format '{{.Server.Version}}'   # Docker Engine 28 이상이어야 한다
docker compose version        # Compose v5.5.1
id -nG | tr ' ' '\n' | grep -x docker    # "docker"가 나와야 한다. 안 나오면 재로그인
systemctl is-enabled docker containerd   # 둘 다 enabled
uv --version
node --version
npm --version
cloudflared --version
systemctl is-active <TUNNEL_SERVICE>   # active
command -v openssl            # password 생성에 쓴다
```

이 문서를 쓸 때 이 머신의 값: uv 0.12.13, node v22.23.0, npm 10.9.8, cloudflared 2026.6.1.

-   **Docker Engine은 28 이상인지 확인한다.** 이 배포는 DB와 API port를 `127.0.0.1`에만 publish하는 것에
    기댄다. 낮으면 Docker를 올린 뒤 진행한다.
-   **`docker` 그룹은 root와 같은 권한이다.** 그룹 사용자는 `docker inspect`로 컨테이너 환경의
    `LLM_API_KEY`와 `POSTGRES_PASSWORD`를 읽을 수 있고, 호스트 파일을 mount해 읽고 쓸 수 있다. 이 머신에서
    `docker` 그룹에는 운영자 본인만 둔다(`getent group docker`).

### 1.2 Cloudflare

대시보드에서 확인한다(메뉴 위치는 Cloudflare가 바꿀 수 있다).

-   `<ZONE>`의 상태가 **Active**다.
-   SSL/TLS → Edge Certificates의 Universal certificate hosts에 **`*.<ZONE>`**이 있다.
-   DNS → Records에 **`<FRONTEND_HOST>`와 `<API_HOST>` 이름의 레코드가 없다.** 두 이름은
    각각 Workers Custom Domain(6절)과 `cloudflared tunnel route dns`(5절)가 만든다. 이미
    있으면 두 명령이 실패한다. wildcard 레코드(`*`)가 있다면 그것도 적어 둔다.

``` sh
getent hosts <FRONTEND_HOST>; echo "exit=$?"   # 출력 없이 exit=2 가 기대값
getent hosts <API_HOST>;      echo "exit=$?"
```

---

## 2. `.env`와 운영 셸

### 2.1 `.env` 만들기

`.env`는 **컨테이너**가 받는 값이다. 저장소 루트에 둔다.

``` sh
cd <REPO>
cp .env.example .env
chmod 600 .env
git check-ignore -v .env      # ".gitignore:...:.env  .env" 가 나와야 한다 (Git 제외)
openssl rand -hex 24          # <POSTGRES_PASSWORD> 로 쓴다
```

**`<POSTGRES_PASSWORD>`는 영숫자 난수로 만든다.** 위 `openssl rand -hex 24`는 `0-9a-f` 48자를
만든다. password manager를 쓴다면 기호를 끄고 영문·숫자만으로 32자 이상을 생성한다.

-   **`$`는 조용히 사라진다.** compose가 `.env`의 `$`를 변수로 해석한다. `ab$cd#ef@gh`는
    `ab#ef@gh`가 되고 경고만 날 뿐 기동은 계속된다. DB는 **사용자가 모르는 password로 초기화**되고
    `~/.pgpass`의 password로는 붙지 못한다. 초기화 뒤에는 `.env`를 고쳐도 되돌아가지 않는다(아래 표).
-   `DATABASE_URL`은 URL이라 `@ # / :`를 퍼센트 인코딩해야 하고, `~/.pgpass`는 `:`와 `\`를 escape해야
    한다. 영숫자만 쓰면 둘 다 필요 없다.

편집기로 `.env`를 열어 아래처럼 채운다. 주석은 그대로 둬도 된다.

``` sh
APP_ENV=production
DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/<POSTGRES_DB>
CORS_ALLOW_ORIGINS=https://<FRONTEND_HOST>
AUTH_SESSION_TTL_DAYS=30
NC_CONFIG_PATH=/etc/nihongo-context/config.yaml
LLM_PROVIDER=openai
LLM_API_KEY=<OPENAI_API_KEY>
POSTGRES_DB=<POSTGRES_DB>
POSTGRES_USER=<POSTGRES_USER>
POSTGRES_PASSWORD=<POSTGRES_PASSWORD>
```

| 항목 | 값 | 이유 |
|---|---|---|
| `APP_ENV` | `production` | `/docs`, `/redoc`, `/openapi.json`이 닫힌다(`development`에서만 열린다). |
| `DATABASE_URL` | host가 **`postgres`** | 컨테이너 안에서 쓰는 DSN이다. `postgres`는 compose 서비스 이름이다. 호스트 셸의 DSN(2.2)과 다르다. |
| `CORS_ALLOW_ORIGINS` | `https://<FRONTEND_HOST>` | **정확한 origin 하나.** 끝에 `/`를 붙이지 않는다. path도 wildcard(`*`)도 안 된다. 형식이 틀리면 backend가 기동하지 못하고, 값이 달라도 로그인 요청이 403이 된다. |
| `AUTH_SESSION_TTL_DAYS` | `30` | 로그인 유지 일수. **비워 두지 않는다** --- compose가 빈 문자열을 넘기면 정수 검증에서 기동이 실패한다. |
| `NC_CONFIG_PATH` | `/etc/nihongo-context/config.yaml` | 사용량 한도가 켜진 정책 파일(3절). compose가 이 경로를 호스트와 컨테이너에 **같은 절대경로**로 read-only mount 한다. 비어 있으면 compose가 아무것도 띄우지 않는다. |
| `LLM_PROVIDER` | `openai` | 기본값이 없다. 없으면 worker가 기동을 거부한다. |
| `LLM_API_KEY` | OpenAI 키 | worker 컨테이너에만 전달된다(backend는 받지 않는다). 이 앱 전용 키를 만들어 쓰기를 권한다. |
| `POSTGRES_*` | 위 표의 값 | postgres 컨테이너가 **처음 초기화할 때만** 이 값으로 사용자와 DB를 만든다. 초기화 뒤에 `.env`의 password를 바꿔도 DB의 password는 바뀌지 않는다. |

`.env`를 **셸에 `source`하지 않는다.** 컨테이너용 DSN과 password가 셸 환경으로 들어온다.

### 2.2 `~/.pgpass` (호스트 운영 명령용 password)

호스트에서 도는 운영 명령(migration, 백업, 계정, seed, prompt)은 DSN에 password를 넣지 않고
libpq가 `~/.pgpass`를 읽게 한다(ADR-020 결정 1). DSN이 crontab·셸 history·화면에 남아도 되게
하려는 것이다.

``` sh
touch ~/.pgpass && chmod 600 ~/.pgpass
editor ~/.pgpass
```

한 줄을 추가한다(데이터베이스 필드 `*`는 restore 검증이 별도 DB에 붙기 때문이다).

``` text
127.0.0.1:5432:*:<POSTGRES_USER>:<POSTGRES_PASSWORD>
```

`ls -l ~/.pgpass`가 `-rw-------`여야 한다. 권한이 넓으면 libpq가 파일을 무시한다.

### 2.3 운영 셸 (운영 명령을 칠 때마다)

**운영 작업은 새 터미널을 열어서 하고, 끝나면 닫는다.** 그 터미널에서 먼저 아래 블록을 붙여 넣는다.

``` sh
cd <REPO>
export APP_ENV=production DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB> NC_CONFIG_PATH=/etc/nihongo-context/config.yaml
PG_BIN="$PWD/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin"
C() { env -i HOME="$HOME" PATH="$PATH" docker compose --env-file .env -f infra/docker-compose.yml "$@"; }
prod_db() { [ "$APP_ENV" = production ] && [ "$DATABASE_URL" = "postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>" ] || { echo "STOP: DATABASE_URL이 운영 DSN이 아니다. 아무것도 실행하지 않았다." >&2; return 1; }; }
```

-   **`APP_ENV=production`과 DSN을 같은 `export` 줄에 둔다.** 개발용 `make db-reset`은
    호출한 셸의 `APP_ENV`가 `production`이면 거부한다. 둘을 따로 설정하면 거부가 빠진 채 운영
    DSN이 쓰일 수 있다.
-   `NC_CONFIG_PATH`는 `make create-user`가 읽는다(기본 timezone). `.env`와 같은 값이다.
-   **`C`는 compose를 부르는 함수다. 이후 모든 compose 명령은 `C ...`로 친다.** `env -i`로
    셸 환경을 비우고 부르는 이유: compose는 **셸의 환경변수를 `.env`보다 우선**해서 compose
    파일에 채운다. 이 셸에는 호스트용 `DATABASE_URL`(`127.0.0.1`)이 export 되어 있으므로
    그냥 `docker compose up`을 치면 **컨테이너가 호스트 DSN을 받아** DB에 붙지 못한다. 실검증에서
    재현했다: 호스트 DSN을 export한 셸에서 띄운 backend가 `127.0.0.1` DSN을 받아 health의
    database가 `down`이 되었다.
-   **`prod_db`는 되돌릴 수 없는 체인(10.2 복원, 12.1 초기화)의 맨 앞에 두는 확인이다.** 셸이 운영 셸이
    아니면(개발 DSN이 남았다, `APP_ENV`가 다르다) `STOP: ...`을 출력하고 실패해서 뒤의 명령이 하나도
    실행되지 않는다. 함수를 정의하지 않은 터미널에서는 `prod_db: command not found`로 역시 멈춘다. DSN
    문자열은 위 `export` 줄과 글자 그대로 같게 채운다.

**운영 셸 확인** --- 넷 다 통과해야 한다.

``` sh
prod_db && echo ok                 # ok
printf '%s\n' "$DATABASE_URL"      # ...@127.0.0.1:5432/<POSTGRES_DB> 여야 한다
"$PG_BIN/pg_dump" --version        # pg_dump (PostgreSQL) 16.2
C config | grep -c '@postgres:5432/'    # 3  (x-app-env, backend, worker)
```

마지막 명령은 compose가 컨테이너에 넘길 DSN의 host를 센다. `config` 출력에는 secret이 있으므로
`grep -c` 없이 화면에 띄우지 않는다. `0`이면 `.env`의 `DATABASE_URL`을 다시 본다.

#### 엉뚱한 DB에 성공하는 위험

이 머신에는 개발용 PostgreSQL(pgserver, `data/pgdata/`)도 있다. 셸에 개발 DB의 DSN이 남아
있으면 migration·백업·계정 생성이 **오류 없이 개발 DB에 적용된다.** 운영 DB에는 아무 일도
일어나지 않았는데 명령은 성공으로 끝난다.

-   `make db-migrate`, `make db-backup`, `make db-restore-check`는 작업 전에 대상 DB를
    출력한다. **그 줄을 읽고 나서 다음 출력으로 넘어간다.**

    ``` text
    target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>     ← 운영
    target: host=<REPO>/data/pgdata port=(default) database=... ← 개발 DB. Ctrl-C로 멈추고 셸을 다시 연다
    ```

-   `make create-user`, `make seed`, `make prompts`는 대상을 출력하지 않는다. **직전에
    `printf '%s\n' "$DATABASE_URL"`로 확인한다.**

---

## 3. 사용량 한도 파일 (`/etc/nihongo-context/config.yaml`)

OpenAI 호출량의 하루 상한이다. repo의 `config/default.yaml`은 두 한도가 `null`(꺼짐)이고,
운영은 **전체 사본**을 만들어 두 줄만 바꾼다. 로더가 누락 키와 모르는 키를 모두 거부하므로 두
키만 담은 파일로는 기동하지 못한다(`spec/mvp-01-core/14_CONFIGURATION.md`의
`production override`).

### 3.1 만들기 (첫날: 30 요청 / 60000 token)

``` sh
cd <REPO>
sudo install -d -m 0755 /etc/nihongo-context
sudo install -m 0644 config/default.yaml /etc/nihongo-context/config.yaml
sudo sed -i \
  -e 's/^  daily_request_limit: null$/  daily_request_limit: 30/' \
  -e 's/^  daily_token_limit: null$/  daily_token_limit: 60000/' \
  /etc/nihongo-context/config.yaml
```

`sed` 대신 `sudoedit /etc/nihongo-context/config.yaml`로 두 줄을 고쳐도 된다.

**확인 --- 정확히 두 줄만 달라야 한다.**

``` sh
diff config/default.yaml /etc/nihongo-context/config.yaml
```

기대 출력(줄 번호는 `default.yaml` 버전에 따라 다르다):

``` text
82,83c82,83
<   daily_request_limit: null
<   daily_token_limit: null
---
>   daily_request_limit: 30
>   daily_token_limit: 60000
```

``` sh
ls -l /etc/nihongo-context/config.yaml     # -rw-r--r-- root root
# 0644가 필요하다. backend·worker 컨테이너는 root가 아니라 uid 10001로 돌며 "그 밖의 사용자" 권한으로 읽는다
NC_CONFIG_PATH=/etc/nihongo-context/config.yaml uv run python -c 'import sys; sys.path.insert(0, "backend"); from app.config import get_config; c = get_config().llm; print(c.daily_request_limit, c.daily_token_limit)'
# 30 60000   ← 로더가 파일을 받아들이고 두 값이 정수로 읽힌다
```

아무 줄도 안 나오면 `sed`가 매치하지 못한 것이다(두 한도가 여전히 null). 네 줄 말고 다른 차이가
나오면 파일을 지우고 3.1을 처음부터 다시 한다.

### 3.2 한도 올리기 (이상 없으면: 100 / 200000)

8절의 AI 동작 확인이 통과한 뒤에 한다.

``` sh
sudo sed -i \
  -e 's/^  daily_request_limit: 30$/  daily_request_limit: 100/' \
  -e 's/^  daily_token_limit: 60000$/  daily_token_limit: 200000/' \
  /etc/nihongo-context/config.yaml
diff config/default.yaml /etc/nihongo-context/config.yaml     # 두 줄만, 값은 100 / 200000
C restart worker
C exec worker sh -c 'grep daily_ "$NC_CONFIG_PATH"'        # 컨테이너가 보는 값이 100 / 200000
```

-   **파일을 고친 뒤 재시작하기 전까지 컨테이너는 옛 내용을 본다.** `sed -i`는 파일을 새로 만들고,
    실행 중인 컨테이너의 단일 파일 mount는 옛 파일을 계속 가리킨다(실검증: 호스트 100, 컨테이너 30).
-   **`C restart worker`로 충분하다.** 재시작하면 mount가 새 파일을 다시 잡고(실검증: 컨테이너 100),
    앱은 config를 기동할 때만 읽으므로 어차피 재시작이 필요하다. 이 문서는 정책 파일 변경에 `restart`
    하나만 쓴다(`--force-recreate`도 동작하지만 컨테이너를 새로 만들 이유가 없다).

### 3.3 경고

-   **값을 바꾸면 worker를 재시작한다(`C restart worker`).** config는 프로세스가 시작할 때 한 번만
    읽는다. 한도는 worker만 쓰므로 worker만 재시작하면 된다. 한도 외의 차이 때문에 파일을 다시
    만들었다면(11절) backend와 worker를 둘 다 재시작한다.
-   **한도는 한국시간 오전 9시에 리셋된다.** 하루 경계가 UTC다. 한도에 걸리면 자정이 아니라
    다음 오전 9시에 생성이 다시 돈다. 그동안에도 학습 세션은 이미 만들어진 문장(Ready Pool)으로
    계속된다.
-   **0이나 음수를 넣지 않는다.** 한도를 끄는 값이 아니라 **생성을 영구히 멈추는** 값이다(날짜가
    바뀌어도 풀리지 않는다). 끄는 값은 `null`이다. 운영에서는 끄지 않는다.
-   **두 키를 모두 설정한다.** 하나만 두면 나머지는 꺼진 한도다.
-   **worker 기동 로그에 `cost.guard_disabled`가 없어야 한다.** 실제 키로 도는데 한도가 하나라도
    `null`이면 worker가 기동할 때 이 경고를 남긴다(4.6에서 확인한다).
-   `daily_token_limit`은 그날 token 수를 모르는 호출이 하나라도 있으면 도달한 것으로 본다
    (fail-closed). 로그의 `jobs_with_unknown_tokens`가 0이 아니면 이 경우다.

### 3.4 한도에 걸렸는지 확인하는 방법

**화면에도 `/api/health`에도 나오지 않는다.** worker 로그에만 남는다.

``` sh
C logs --since 24h worker 2>&1 | grep 'cost.ceiling_reached'
```

``` text
... WARNING app.jobs cost.ceiling_reached provider_calls=30 input_tokens=... output_tokens=... jobs_with_unknown_tokens=0
```

한도에 머무는 동안 한 번만 찍힌다. 오늘 사용량을 DB에서 직접 보려면 8.2의 세 번째 SQL을 쓴다.

---

## 4. 첫 기동

**각 단계의 확인이 통과하기 전에 다음 단계로 가지 않는다.** 모든 명령은 2.3의 운영 셸에서 친다.

### 4.1 DB 기동

먼저 compose 파일이 DB 파일을 **`data/postgres/` 바로 아래가 아니라 하위 디렉터리**에 두는지 본다.

``` sh
grep -n 'PGDATA: /var/lib/postgresql/data/pgdata' infra/docker-compose.yml   # 한 줄이 나와야 한다
```

안 나오면 **띄우지 않는다.** 옛 구성이다. `data/postgres/`에는 Git이 추적하는 `.gitkeep`이 있어서,
그 디렉터리를 그대로 DB 디렉터리로 쓰면 postgres 초기화가 "비어 있지 않다"로 실패하고 재시작을
반복한다. 그 과정에서 디렉터리 소유자까지 바뀐다(14절). `git pull`로 최신 코드를 받는다.

``` sh
C up -d postgres
C ps postgres                  # STATUS가 Up. Restarting이면 멈추고 14절
C logs postgres 2>&1 | tail -5 # "database system is ready to accept connections"
ss -ltn 'sport = :5432'
ls -ld data/postgres data/postgres/pgdata
```

-   `ss` 출력의 Local Address가 **`127.0.0.1:5432`뿐**이어야 한다. `0.0.0.0:5432`나 `[::]:5432`가
    보이면 멈춘다(DB가 네트워크에 열려 있다).
-   `data/postgres/`는 여전히 내 소유다. 새로 생긴 `data/postgres/pgdata/`는 컨테이너의 postgres
    사용자(uid 999) 소유 `drwx------`라서 호스트 사용자는 안을 볼 수 없다. 정상이다. Git에서도
    제외된다.

### 4.2 migration

``` sh
make db-migrate ARGS="--pg-bin $PG_BIN"
```

-   첫 줄 `target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>`를 **읽는다.** 다르면 Ctrl-C.
-   빈 DB라서 `pending migrations: (empty database) -> <head>`가 나오고, 빈 DB 백업을 하나
    만든 뒤(`backup verified: ...`) `alembic upgrade head: done`으로 끝난다.

확인 --- 한 번 더 실행하면 아무것도 하지 않아야 한다.

``` sh
make db-migrate ARGS="--pg-bin $PG_BIN"
# target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
# already at head (<head>); nothing to do, no backup taken
```

### 4.3 계정

``` sh
printf '%s\n' "$DATABASE_URL"          # 127.0.0.1:5432/<POSTGRES_DB> 확인
make create-user ARGS="--login-id <LOGIN_ID>"
```

`Password:`와 `Password (again):` 프롬프트에 password를 입력한다.

-   **16자 이상.** 짧으면 거부된다. password manager가 만든 난수(또는 diceware 4단어 이상)를 쓴다.
    로그인 시도 횟수 제한이 없으므로(15절) 이 password가 1차 방어선이다.
-   password를 명령 인자로 넘기는 방법은 없다(셸 history와 `ps`에 남기 때문이다).

확인: `created user 1 (<LOGIN_ID>)`.

### 4.4 seed

``` sh
printf '%s\n' "$DATABASE_URL"
make seed
```

확인: `loaded seed from <REPO>/seed: <N> items, ... sentences, ... spans, ... explanations`.
`<N>`은 `seed/items.yaml`의 item 수와 같다.

**seed는 추가 적재가 되지 않는다.** 이미 seed를 적재한 DB에 다른 seed를 넣으려면 12절 절차로 DB를
**한 번 초기화하고 다시 적재한다.** 그때 계정과 학습 기록은 모두 사라진다.

### 4.5 prompt 등록 --- worker보다 반드시 먼저

``` sh
printf '%s\n' "$DATABASE_URL"
make prompts ARGS="--provider openai --model gpt-4o-mini"
```

확인: 세 줄이 나온다.

``` text
created and activated GENERATE_SENTENCE_BATCH <version> provider=openai model=gpt-4o-mini
created and activated EXPLAIN_ITEM <version> provider=openai model=gpt-4o-mini
created and activated GENERATE_REVIEW_CONTEXT <version> provider=openai model=gpt-4o-mini
```

DB에서도 active 3행을 본다.

``` sh
C exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT task_type, version, provider, model FROM prompt_versions WHERE active ORDER BY task_type;
SQL
```

**이 단계 없이 worker를 띄우면** worker가 `no active prompt_versions row for task_type: ...`로
기동을 거부하고 compose의 재시작 정책 때문에 재시작을 반복한다.

### 4.6 OpenAI 키 확인 → worker 기동

**먼저 `.env`의 키가 유효한지 직접 확인한다.** worker는 키를 기동 때 검사하지 않는다. 틀린 키로도
worker는 재시작 없이 뜨고 health의 worker는 `ok`이며, 정상 worker는 기동 로그를 한 줄도 남기지
않는다. 첫 세션은 seed 문장만으로 돌아 한동안 생성 job이 없으므로, **키 오타는 첫 생성 job이
retry를 거쳐 `failed`로 끝날 때에야** 드러난다(8.2). 그래서 기동 전에 확인한다.

모델 목록 조회(`GET /v1/models`)는 과금되지 않는다. 아래 명령은 **`.env`에 적힌 값 그대로**를
확인하고, 키를 명령줄 인자·셸 history·화면에 남기지 않는다(`printf`는 셸 내장이라 프로세스 인자에
보이지 않고, curl은 헤더를 stdin에서 읽는다).

``` sh
K="$(sed -n 's/^LLM_API_KEY=//p' .env)"
printf 'Authorization: Bearer %s\n' "$K" \
  | curl -s -o /dev/null -w '%{http_code}\n' -H @- https://api.openai.com/v1/models
unset K
```

-   `200` → 유효하다. 다음으로 간다.
-   `401` → 키 오류다. `.env`의 `LLM_API_KEY` 줄(앞뒤 공백, 따옴표, 잘린 복사)을 고치고 다시 확인한다.
-   그 밖의 코드 → `-o /dev/null`을 빼고 다시 실행해 본문의 오류 메시지를 읽는다.
-   키를 `.env`가 아니라 password manager에서 붙여 넣어 확인하려면 첫 줄 대신
    `read -rs K && echo`를 쓴다(입력이 화면과 history에 남지 않는다).

이것은 운영자가 직접 실행하는 명령이다. 앱은 API 요청 처리 중에 OpenAI를 호출하지 않는다.

이어서 worker를 띄운다.

``` sh
C build backend worker          # 처음에는 이미지를 받느라 몇 분 걸린다
C up -d --no-deps worker
sleep 40
C ps worker                     # STATUS가 "Up ..."이어야 한다. "Restarting"이면 14절
C logs worker 2>&1 | grep -c 'cost.guard_disabled'    # 0 이어야 한다
C logs worker 2>&1 | tail -20   # Traceback이 없어야 한다
```

`cost.guard_disabled`가 1 이상이면 한도가 꺼져 있다. `C stop worker`로 멈추고 3.1의 `diff`와
`.env`의 `NC_CONFIG_PATH`를 다시 본다.

### 4.7 backend 기동

``` sh
C up -d --no-deps backend
sleep 5
C ps backend
curl -s http://127.0.0.1:8000/api/health; echo
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs            # 404
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/openapi.json    # 404
```

health 기대값 --- `"database":{"status":"ok",...}`과 `"worker":{"status":"ok",...}`.

-   `worker`가 `unknown`이면 worker의 생존 신호가 아직 없다(worker가 떠 있지 않거나 막 떴다).
    30초 뒤 다시 본다.
-   `stale`이면 worker가 2분 넘게 신호를 쓰지 않았다. `C ps worker`와 로그를 본다.
-   `/docs`가 200이면 `.env`의 `APP_ENV`가 `production`이 아니다.

---

## 5. 터널 (API 공개)

**`infra/cloudflared/README.md`를 따라 한다.** 기존 터널 설정에 규칙 한 줄을 더하고,
DNS를 연결하고, 검증한 뒤 재시작한다. 재시작하면 같은 터널을 쓰는 다른 서비스가 있다면 잠깐 끊긴다.

확인(휴대폰 LTE 등 외부 네트워크에서도 한 번):

``` sh
curl -s -o /dev/null -w '%{http_code}\n' https://<API_HOST>/api/health    # 200
curl -s -o /dev/null -w '%{http_code}\n' https://<API_HOST>/docs          # 404
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<API_HOST>/api/auth/login \
  -H 'Origin: https://<FRONTEND_HOST>' -H 'Content-Type: application/json' -d '{}'   # 422
```

마지막 명령은 password 없이 `CORS_ALLOW_ORIGINS`를 확인한다. `422`(본문이 비었다)는 origin이
통과했다는 뜻이다. `403`이면 `.env`의 `CORS_ALLOW_ORIGINS`가 `https://<FRONTEND_HOST>`와 글자
그대로 같지 않다.

---

## 6. 프론트 배포 (Workers Static Assets)

### 6.1 준비 (처음 한 번)

-   **wrangler 버전을 하나 고른다.** `npm view wrangler version`이 최신 버전을 보여준다. 그 값을
    `<WRANGLER_VERSION>`으로 적어 두고 매번 같은 버전을 쓴다. wrangler는 `package.json`에 넣지
    않는다(ADR-020 결정 5).
-   **`<COMPAT_DATE>`**: 첫 배포하는 날짜(`YYYY-MM-DD`)를 한 번 정해 계속 쓴다.
-   **flag 확인 (확인 필요):** 고른 버전에서 `--name`, `--assets`, `--compatibility-date`가
    있는지 본다. wrangler 4.131.1에서는 셋 다 있었고, 설정 파일 없이
    `deploy --dry-run --name ... --assets ./dist --compatibility-date ...`가 파일을 만들지 않고
    끝나는 것을 확인했다. **다른 버전은 확인하지 않았다.**

    ``` sh
    cd <REPO>/frontend && npx --yes wrangler@<WRANGLER_VERSION> deploy --help
    ```

-   **로그인 (확인 필요):** `npx --yes wrangler@<WRANGLER_VERSION> login`은 브라우저 OAuth를
    연다. 이 머신에 브라우저가 없거나 계정이 여러 개일 때의 절차(`CLOUDFLARE_API_TOKEN`,
    `CLOUDFLARE_ACCOUNT_ID`)는 wrangler 문서로 확인한다.

### 6.2 빌드 → 산출물 확인 → 배포 (하나의 `&&` 체인)

``` sh
cd <REPO>/frontend \
  && npm ci \
  && VITE_API_BASE_URL=https://<API_HOST> npm run build \
  && grep -rqF 'https://<API_HOST>' dist \
  && ! grep -rqF 'localhost:8000' dist \
  && npx --yes wrangler@<WRANGLER_VERSION> deploy --name <WORKER_NAME> --assets ./dist \
       --compatibility-date <COMPAT_DATE>
```

-   **두 grep이 배포의 일부다.** `frontend/src/env.ts`는 `VITE_API_BASE_URL`이 없으면 **아무 경고
    없이** `http://localhost:8000`을 번들에 넣는다. 그 번들이 배포되면 휴대폰이 자기 자신의
    localhost로 요청을 보내고 화면에는 "네트워크 실패"만 보인다. 산출물에 API 주소가 **있고**
    localhost가 **없을** 때만 deploy가 실행된다(이 저장소에서 두 경우 모두 빌드해 grep 결과를
    확인했다).
-   `VITE_API_BASE_URL` 끝에 `/`를 붙이지 않는다. 요청 경로가 `/api/...`로 시작해서 `//api/...`가 된다.
-   `VITE_API_BASE_URL`은 **이 명령의 환경변수로만** 준다. `frontend/.env.production` 같은 파일을
    만들지 않는다. 만들면 같은 머신의 개발 빌드에도 운영 주소가 들어간다.
-   체인이 중간에 멈추면(아무 메시지 없이 끝나면) grep 단계에서 걸린 것이다. `echo $?`가 0이 아니다.

### 6.3 Custom Domain 연결과 `workers.dev` 끄기 (대시보드, 처음 한 번)

메뉴 이름과 위치는 Cloudflare가 바꿀 수 있다(확인 필요).

1.  Workers & Pages → `<WORKER_NAME>` → Settings → Domains & Routes → Add → **Custom domain**
    → `<FRONTEND_HOST>`. DNS 레코드와 인증서는 Cloudflare가 만든다.
2.  같은 화면에서 **`workers.dev`를 끈다(Disable).** **Preview URLs도 끈다.**
3.  **첫 배포 뒤 다시 배포했을 때 `workers.dev`가 다시 켜지는지 확인한다 (확인 필요).** 설정
    파일 없는 `wrangler deploy`가 매번 다시 켜는지는 wrangler 버전에 달려 있고 확인하지 않았다.
    다시 켜진다면 ADR-020 결정 5의 전환 조건대로 `frontend/wrangler.jsonc`에
    `workers_dev: false`와 `preview_urls: false`만 두는 변경을 따로 한다(도메인은 적지 않는다).

확인:

``` sh
curl -s -o /dev/null -w '%{http_code}\n' https://<FRONTEND_HOST>/     # 200
```

---

## 7. 실기 확인 (휴대폰)

휴대폰 브라우저로 `https://<FRONTEND_HOST>`를 연다. 순서대로 확인한다.

1.  **선택 홈** --- 상단바에 앱 이름과 `로그인`, 그 아래 카드 두 개(`표현 학습 체험해 보기`,
    `글자부터 배우기`)가 나온다.
2.  **로그인** --- 상단바 `로그인`을 누르면 로그인 화면이 나온다. `<LOGIN_ID>`와 password. 학습
    화면으로 넘어간다.
3.  **세션 시작·진행** --- 문장이 나오고, 단어를 누르면 설명이 아래에서 올라오고, 번역 보기를 누르면
    문장 아래에 번역이 펼쳐진다. 몇 문장 진행한다.
4.  **세션 종료** --- 종료 화면이 나온다.
5.  **새로고침** --- 선택 홈이 나온다(정상이다). 상단바 `로그인`을 누르면 로그인 화면 없이 곧바로 학습
    화면이다. 로그인 상태가 유지된 것이다.
6.  **history** --- 상단바 `학습 기록`. 방금 한 세션과 본 item이 보인다.
7.  **demo·가나** --- 상단바 `로그아웃`을 누르면 선택 홈으로 돌아온다. `표현 학습 체험해 보기`로 들어가
    로그인 없이 동작하는지, 앱 이름을 누르면 선택 홈인지 본다. `글자부터 배우기`도 같은 방식으로 본다.

알아 둘 것:

-   **iOS Safari는 https 주소에서만 로그인된다.** `http://`나 IP 주소로는 안 된다.
-   **홈 화면에 추가한 PWA는 Safari와 cookie 저장소가 따로다.** Safari에서 로그인했어도 홈 화면
    앱 안에서 **다시 로그인**해야 한다.
-   로그인 직후 401로 로그인 화면에 돌아오면 14절의 "로그인 직후 401".

---

## 8. AI 동작 확인 (첫날)

gpt-4o-mini가 이 앱의 structured output 스키마와 맞는지는 **검증되지 않았다.** 맞지 않으면 첫
job들이 retry로 attempt를 쓰고(job당 최대 3회) `failed`로 끝난다. 그래도 학습 세션은 이미 있는
문장으로 계속된다. 첫날 한도(30 / 60000)가 이 확인 기간의 비용 상한이다.

### 8.1 job이 생기게 하기

생성 job은 학습 세션이 진행되면서 준비된 문장이 부족할 때 만들어진다. 7절처럼 세션을 진행한다.
job이 0건이면 아직 생성이 필요하지 않은 것이다. seed 문장이 소진될 만큼 더 진행한다.

### 8.2 DB에서 보기

``` sh
C exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
-- 1. 상태별 개수
SELECT status, count(*) FROM generation_jobs GROUP BY status ORDER BY status;

-- 2. 최근 job 20건
SELECT id, job_type, status, retry_count, max_attempts,
       left(last_error, 120)                  AS last_error,
       result_ref->'usage'->>'provider_calls' AS calls,
       result_ref->'usage'->>'input_tokens'   AS input_tokens,
       result_ref->'usage'->>'output_tokens'  AS output_tokens,
       created_at, finished_at
FROM generation_jobs
ORDER BY id DESC
LIMIT 20;

-- 3. 오늘(UTC) 사용량. worker의 한도 판정과 같은 기준이다
SELECT coalesce(sum((result_ref->'usage'->>'provider_calls')::bigint), 0) AS provider_calls,
       coalesce(sum((result_ref->'usage'->>'input_tokens')::bigint), 0)
     + coalesce(sum((result_ref->'usage'->>'output_tokens')::bigint), 0)  AS tokens_known,
       count(*) FILTER (WHERE result_ref->'usage'->>'input_tokens' IS NULL
                           OR result_ref->'usage'->>'output_tokens' IS NULL) AS jobs_with_unknown_tokens
FROM generation_jobs
WHERE (result_ref->'usage'->>'last_call_at')::timestamptz >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
SQL
```

읽는 법:

| status | 뜻 |
|---|---|
| `queued` / `running` | 대기 중 / 처리 중 |
| `retry` | 실패했고 다시 시도할 예정. `last_error`의 앞부분이 예외 타입이다 |
| `completed` | 생성 성공. 이것이 한 건이라도 있으면 파이프라인이 동작한다 |
| `failed` | attempt를 다 썼다 |
| `dead_letter` | 다시 시도해도 소용없는 실패(예: prompt 행 문제) |

-   **`completed`가 있고 `failed`가 없다** → 3.2로 한도를 올린다.
-   **키 오류는 여기서 처음 드러난다.** worker는 틀린 키로도 정상처럼 뜨고 health도 `ok`다(4.6).
    위 두 번째 SQL에서 `last_error`가 `provider call failed: ProviderCallError: provider call failed: Error code: 401`
    형태인 job이 있으면 키 문제다(provider 오류는 retry로 처리되어 attempt를 다 쓰면 `failed`가 된다).
    4.6의 키 확인 명령을 다시 실행하고, `.env`를 고친 뒤 `C up -d --no-deps worker`로 다시 만든다.
-   **전부 `retry`/`failed`이고 `last_error`가 같은 종류** → 모델 호환성이나 키 문제일 가능성이
    크다. 한도를 올리지 않는다. 모델을 바꾸려면 `make prompts ARGS="--provider openai --model <다른 모델>"`
    (worker는 job을 실행할 때 active 행을 읽는다).
-   `tokens_known`이 `input_tokens`가 없는 job 때문에 하한일 수 있다. 그래서 세 번째 열을 함께 본다.

### 8.3 로그에서 보기

``` sh
C logs --since 1h worker 2>&1 | grep -E 'job\.(claimed|completed|failed)|provider\.call|cost\.'
```

로그와 `last_error`에는 prompt 원문, 응답 원문, API 키가 남지 않는다.

---

## 9. 백업

백업 파일에는 password hash가 들어 있다. 파일은 만들어지는 순간부터 `0600`이고 Git에서 제외된다
(`data/backups/`).

### 9.1 수동 1회

``` sh
make db-backup ARGS="--pg-bin $PG_BIN"
```

-   `target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>`를 읽는다.
-   `pg_dump client: pg_dump (PostgreSQL) 16.2`와 `server version: 16.x`가 나온다. 클라이언트가
    서버보다 minor가 낮아도 된다(실검증: 16.2로 16.15 서버를 백업하고 restore 검증까지 통과했다).
-   `backup verified: ...` → `backup written: <REPO>/data/backups/backup-<UTC시각>.dump`로 끝난다.
-   가장 최근 7개(`backup-*.dump`)만 남기고 오래된 것부터 지운다(`rotated out: ...`). migration
    직전 백업과 수동 백업도 한 개로 센다.

``` sh
ls -l data/backups/        # -rw------- 파일들
```

-   **`*.partial`이 보이면 중단된 백업의 조각이다.** 백업이 강제 종료(SIGKILL, 메모리 부족 등)되면
    `backup-<UTC>.dump.partial`이 남는다. password hash가 든 0600 파일이고 rotation이 세지 않아 **저절로
    지워지지 않는다.** 백업이 돌고 있지 않을 때(04:17 cron 시각을 피해) 확인하고 지운다.

    ``` sh
    ls -l data/backups/*.partial data/backups/pre-restore/*/*.partial data/backups/pre-mvp02/*/*.partial 2>/dev/null
    rm -f data/backups/*.partial data/backups/pre-restore/*/*.partial data/backups/pre-mvp02/*/*.partial
    ```

-   (선택) **`data/backups/` 디렉터리 권한.** Git이 만든 디렉터리는 `drwxrwxr-x`라, 파일 내용은 못 읽어도
    같은 호스트의 다른 사용자가 백업 **파일 이름과 시각**을 볼 수 있다. 막으려면
    `chmod 700 data/backups`. Git은 디렉터리 권한을 추적하지 않으므로 커밋 대상이 바뀌지 않는다
    (`git status`에 아무것도 나오지 않는다).

### 9.2 정기 (하루 1회, crontab 한 줄)

`crontab -e`로 한 줄을 추가한다. 모든 경로는 절대경로다(cron의 PATH는 최소다).

``` text
17 4 * * * cd <REPO> && APP_ENV=production DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB> <UV> run --no-sync python scripts/db_backup.py --pg-bin <PG_BIN> >> <REPO>/data/backup.log 2>&1
```

-   password는 이 줄에 없다(`~/.pgpass`). docker 권한도 필요 없다.
-   **이 줄에 `%`를 넣지 않는다.** crontab에서 `%`는 줄바꿈이다. 파일 이름의 시각은 스크립트가 만든다.
-   `--no-sync`: 새벽 작업이 `.venv`를 바꾸지 않게 한다.
-   서비스가 켜진 채로 dump한다. pg_dump는 한 시점의 스냅샷이라 파일은 일관적이다.
-   시각은 호스트 시간대 기준 04:17이다.

확인 --- cron과 같은 최소 환경으로 한 번 돌려 본다(백업이 하나 더 생긴다).

``` sh
crontab -l | grep db_backup
env -i HOME="$HOME" sh -c 'cd <REPO> && APP_ENV=production DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB> <UV> run --no-sync python scripts/db_backup.py --pg-bin <PG_BIN>'
```

다음 날 아침: `tail -n 8 data/backup.log`에 그날 `backup written:`이 있는지 본다. **cron 백업의
실패는 이 로그에만 남는다.** 주 1회는 확인한다.

### 9.3 한계

**백업이 DB와 같은 디스크에 있다.** 그 디스크가 고장 나면 DB와 백업 7개가 함께 사라진다.
다른 물리 위치(외장 디스크 등)에 사본을 두는 것은 선택이며 지금은 하지 않기로 했다. 사본을 둔다면
같은 권한(`0600`)으로 다룬다.

---

## 10. 복원 훈련과 실제 복원

### 10.1 복원 훈련 (scratch DB에 복원해 검증)

`make db-restore-check`는 백업을 **별도 DB**(`<POSTGRES_DB>_restore_<UTC>`)에 복원해 원본과
비교하고, 끝나면 그 DB를 지운다. 운영 DB는 읽기만 한다. 검증 항목은 여섯이다(alembic 버전,
모든 테이블 행·내용 해시, sequence, 제약·index, 복원 DB에서 login과 history, 1행 훼손을 잡는지).

**API·worker를 멈추고, 그 상태에서 새로 만든 백업으로만 한다.**

-   worker는 job이 없어도 생존 신호를, API는 로그인한 요청마다 session 사용 시각을 DB에 쓴다.
    백업 뒤에 원본에 쓰기가 한 번이라도 있으면 비교가 거짓으로 실패한다.
-   **cron 백업은 서비스가 켜진 채 만들어졌으므로 이 검증의 대상이 될 수 없다.**

``` sh
C stop backend worker
make db-backup ARGS="--pg-bin $PG_BIN"
# 마지막 줄의 파일 경로를 복사한다: backup written: <REPO>/data/backups/backup-<UTC>.dump
make db-restore-check ARGS="--pg-bin $PG_BIN --backup data/backups/backup-<UTC>.dump --login-id <LOGIN_ID>"
```

-   `target:` 줄을 읽는다.
-   `Password:`에 **운영 계정의 password**를 입력한다(검증 5번의 login에 쓴다).
-   기대 출력의 끝:

    ``` text
    compared: alembic_version=<head> (head), ... tables, ... sequences, ... constraints, ... indexes
    negative control: corrupted one row of <table> -> detected, rolled back
    api: login ok, history sessions=... items=...
    dropped restore database: <POSTGRES_DB>_restore_<UTC>
    restore check passed
    ```

``` sh
C up -d --no-deps backend worker
curl -s http://127.0.0.1:8000/api/health; echo
```

-   참고로 실검증(migration head `0003`)에서는 `21 tables, 19 sequences, 94 constraints, 50 indexes`였고
    음성 대조군은 `auth_sessions` 행을 훼손해 검출했다. migration이 늘면 숫자가 달라지고, 훼손 대상
    테이블은 데이터에 따라 달라진다.
-   **계정도 없는 빈 DB에서는 통과하지 않는다.** 5번(login)이 실패하고, 6번은 훼손할 행이 없어
    `negative control: no row in the restored database to corrupt`로 실패한다. 4.3 이후에 한다.
    (계정 1개와 seed 없는 DB로는 통과하는 것을 확인했다.)
-   훈련용 백업도 보관 개수 7에 한 개로 센다.

### 10.2 실제 복원 (운영 DB를 덮어쓴다)

> **되돌릴 수 없다.** 선택한 백업 이후의 모든 학습 기록이 사라진다. 먼저 10.1로 그 백업 파일을
> 검증할 수 있으면 검증한다. migration 실패 때문에 복원한다면, 먼저 `git checkout`으로 **그 백업을
> 만든 시점의 코드**로 돌아간다(새 코드는 옛 schema에서 돌지 않는다).

복원할 파일을 고르고 경로를 변수에 넣는다. 이후 확인과 복원이 **같은 변수**를 쓰므로 확인한 파일과
복원하는 파일이 어긋나지 않는다.

``` sh
ls -l data/backups/
F=data/backups/<FILE>
R="data/backups/pre-restore/$(date -u +%Y%m%dT%H%M%SZ)" && printf 'safety backup dir: %s\n' "$R"
```

`R`은 이번 복원 시도 전용 안전 백업 디렉터리다. **출력된 `safety backup dir:` 줄을 종이나 메모에 적어 둔다.**
그 디렉터리에는 이번 시도의 안전 백업 하나만 생기므로, 되돌릴 때 고를 파일이 하나로 정해진다.

아래 체인은 한 덩어리로 붙여 넣는다. 순서와 이유:

1.  **`prod_db`** --- 셸의 `DATABASE_URL`이 운영 호스트 DSN인지 확인한다(2.3에서 정의). 안전 백업은
    셸의 DSN을 따르고 DROP은 compose의 postgres를 겨냥하므로, 둘이 같은 DB라는 것을 **DROP 전에**
    확인해야 한다. 개발 DSN이 남은 셸이면 안전 백업이 개발 DB를 백업하고 "성공"한 뒤 운영 DB가 지워진다.
2.  **파일 확인** --- 파일이 있고 `pg_restore`가 목차를 읽을 수 있는지. 경로 오타를 DROP 전에 잡는다.
    이어서 `$R`이 비어 있지 않고 **아직 없는 디렉터리**인지 확인한다. 체인만 다시 붙여 넣으면 `$R`이 이미
    있어서 여기서 멈춘다.
3.  **서비스 정지.**
4.  **안전 백업** --- 지금 DB를 **rotation 밖**(`$R` = `data/backups/pre-restore/<시각>/`)에 백업한다. `data/backups/`에
    쓰면 rotation이 가장 오래된 백업(= 복원하려는 파일일 수 있다)을 지운다. `pre-restore/`는 Git 제외
    경로 안이고 rotation이 세지 않는다.
5.  **DROP → CREATE** --- `C exec postgres` 안에서 한다. compose의 postgres만 겨냥한다.
6.  **복원** --- `--single-transaction`: 복원 도중 오류가 나면 전부 롤백되어 **일부만 복원된 DB가 남지
    않는다**(빈 DB가 남는다).

``` sh
prod_db \
  && [ -f "$F" ] \
  && "$PG_BIN/pg_restore" --list "$F" > /dev/null \
  && [ -n "$R" ] && [ ! -e "$R" ] \
  && C stop backend worker \
  && make db-backup ARGS="--pg-bin $PG_BIN --backup-dir $R" \
  && C exec -T postgres sh -c \
       'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  && "$PG_BIN/pg_restore" --no-owner --exit-on-error --single-transaction --no-password \
       --dbname="host=127.0.0.1 port=5432 user=<POSTGRES_USER> dbname=<POSTGRES_DB>" \
       "$F" \
  && echo restored
```

-   **마지막 줄에 `restored`가 없으면 어디선가 멈춘 것이다.** 멈춘 위치는 출력으로 구분한다.
    -   `STOP: DATABASE_URL이 운영 DSN이 아니다` → 1에서 멈췄다. 아무것도 실행되지 않았다. 터미널을 닫고
        2.3부터 다시.
    -   출력 없이 끝났다 → 2에서 멈췄다. 파일이 없거나(`[ -f "$F" ]`), `R=` 줄을 빼먹었거나 체인만 다시
        실행했다(`$R` 확인). 아무것도 실행되지 않았다.
    -   `pg_restore: error: could not open input file` / 목차 오류 → 2에서 멈췄다. 아무것도 실행되지 않았다.
    -   `backup failed` → 4에서 멈췄다. 서비스만 멈춰 있고 DB는 그대로다. 지금 DB가 망가져 백업조차
        안 되는 상황이라면, 그대로 진행할지는 운영자가 판단한다.
    -   `backup written:` 뒤에 `pg_restore: error` → **6에서 실패했다. 운영 DB는 비어 있다.** 아래
        "복원이 실패했을 때"로 간다.
-   체인이 끝난 뒤 안전 백업 출력의 `target:` 줄이 `host=127.0.0.1 port=5432 database=<POSTGRES_DB>`인지도
    읽는다(1이 이미 보장하지만 눈으로 한 번 더 본다).

#### 복원이 실패했을 때 (안전 백업으로 되돌리기)

> **복원이 실패하면 10.2 체인을 다시 실행하지 않는다.** 이 시점의 운영 DB는 이미 DROP된 빈 DB라서, 다시
> 실행하면 **빈 DB가 새 안전 백업**이 되고 그것으로 되돌리면 빈 DB로 "성공"한다. 아래 절차만 한다.

6에서 실패하면 운영 DB는 빈 DB다(`--single-transaction` 덕분에 반쯤 복원된 상태는 아니다). 4에서 만든
안전 백업(= 복원 직전의 운영 DB)으로 같은 절차를 한 번 더 한다. 안전 백업은 복원을 시작할 때의
코드와 schema에 맞는다. 복원 전에 `git checkout`으로 코드를 옮겼다면 원래 코드로 돌아온다.

`P`에는 **10.2 체인이 출력한 `backup written:` 경로를 그대로** 넣는다. 그 경로는 적어 둔
`safety backup dir:` 디렉터리 안의 유일한 `backup-*.dump`다. "가장 최근 파일"로 고르지 않는다.

``` sh
ls -l <SAFETY_BACKUP_DIR>/          # 적어 둔 safety backup dir. backup-*.dump 가 하나만 있어야 한다
P=<SAFETY_BACKUP_FILE>              # 10.2 체인이 출력한 backup written: 경로 그대로
printf '%s\n' "$P"
prod_db \
  && [ -f "$P" ] \
  && "$PG_BIN/pg_restore" --list "$P" > /dev/null \
  && C exec -T postgres sh -c \
       'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  && "$PG_BIN/pg_restore" --no-owner --exit-on-error --single-transaction --no-password \
       --dbname="host=127.0.0.1 port=5432 user=<POSTGRES_USER> dbname=<POSTGRES_DB>" \
       "$P" \
  && echo "rolled back to $P"
```

그다음 아래 "복원 뒤"를 한다. 실패한 원래 백업 파일은 10.1의 복원 훈련으로 원인을 본다.

**`data/backups/pre-restore/` 정리는 운영이 정상임을 확인한 뒤에만 한다.** 확인 = "복원 뒤"의 health가
`ok`이고, 휴대폰에서 로그인과 history에 기대한 기록이 보인다(7절). 그 전에는 지우지 않는다 --- 안전 백업이
복원 직전 운영 상태의 **유일한 사본**일 수 있다. 확인한 뒤에는 rotation이 지우지 않으므로 직접 지운다
(password hash가 들어 있다).

복원 뒤:

``` sh
make db-migrate ARGS="--pg-bin $PG_BIN"     # 백업이 옛 revision이면 올린다. head면 아무것도 안 한다
C up -d --no-deps backend worker
curl -s http://127.0.0.1:8000/api/health; echo
```

브라우저는 복원 시점의 로그인 세션을 쓰므로 다시 로그인해야 할 수 있다.

---

## 11. 업데이트 (새 코드 배포)

``` sh
cd <REPO> && git pull
```

1.  **정책 파일 diff.**

    ``` sh
    diff config/default.yaml /etc/nihongo-context/config.yaml
    ```

    기대: 두 한도 줄만 다르다. **그 밖의 차이가 나오면** `default.yaml`에 키가 추가·삭제·변경된
    것이다. 그대로 두면 키 추가·삭제는 기동 실패로, 값 변경은 **조용히 옛 값으로** 돈다. 3.1의
    `install`로 다시 복사하고, 현재 한도 값(첫날이면 30 / 60000, 올렸으면 100 / 200000)으로 두 줄을
    다시 고친 뒤 diff를 다시 본다.

2.  **서비스 정지 → migration → prompt → 재기동.**

    ``` sh
    C stop backend worker
    make db-migrate ARGS="--pg-bin $PG_BIN"     # target 확인. pending이면 직전 백업을 강제로 만든다
    make prompts ARGS="--provider openai --model gpt-4o-mini"
    C build backend worker
    C up -d --no-deps backend worker
    ```

    -   migration 백업부터 upgrade까지 서비스를 멈추는 이유: 롤백은 그 백업의 복원(10.2)이고, 그 사이
        쓰기는 복원이 지운다. downgrade 명령은 없다.
    -   `make prompts`는 같은 값으로 다시 실행해도 안전하다(upsert). 코드의 prompt version이 바뀐
        경우 이 단계가 없으면 그 task의 job이 `dead_letter`가 된다. "several prompt versions in code"
        오류가 나면 `--task`와 `--version`으로 하나를 고른다.
    -   `up -d`는 `.env`나 compose 파일이 바뀌었으면 컨테이너를 새로 만든다. `restart`는 바뀐 `.env`를
        반영하지 않는다.

3.  **확인** --- 4.6의 worker 확인, 4.7의 health 확인.

4.  `frontend/`가 바뀌었으면 6.2를 다시 실행한다.

MVP-02(후리가나·선택 홈·가나) 첫 업데이트는 이 절 대신 17절을 따른다.

---

## 12. seed 초기화 (확장 seed 적재, 1회)

> **되돌릴 수 없다. 운영 DB의 모든 계정, 학습 기록, 생성된 문장이 사라진다.** 기술 검증을 끝내고
> 확장한 seed로 본 사용을 시작할 때 **한 번만** 한다. 본 사용이 시작된 뒤에는 이 절을 쓰지
> 않는다 --- 그때는 몇 주치 학습 기록이 사라진다.

이 절차는 ADR-020 결정 7이다. 운영 초기화를 위한 명령은 일부러 만들지 않았다(`make db-reset`은
`APP_ENV=production`에서 거부한다). 거부를 우회하려고 `APP_ENV`를 바꿔 치지 않는다.

### 12.0 확장 seed가 적재되는지 로컬에서 먼저 확인

운영 DB를 지운 뒤에 seed 오류를 발견하지 않게 한다. **운영 셸이 아닌 별도 터미널**(`APP_ENV`가
production이 아닌 셸)에서, 확장 seed가 들어간 코드로 한다. 개발 DB를 건드리지 않도록 DB 이름을 따로 준다.

``` sh
cd <REPO>
export DATABASE_URL="$(make -s db-up-local ARGS='--database nc_seedcheck')" \
  && make db-reset ARGS=--yes \
  && make seed
```

확인: `loaded seed from <REPO>/seed: <N> items, ...`에서 `<N>`이 확장한 seed 파일의 item 수와 같다. 오류가 나면 여기서 멈추고 seed를 고친다.
이 터미널은 닫는다.

### 12.1 운영 초기화

**운영 셸(2.3)을 새로 열어서** 한다. 12.0에서 쓴 터미널을 이어 쓰지 않는다 --- 그 터미널의
`DATABASE_URL`은 개발 DB를 가리킨다. 확장 seed가 들어간 코드를 `git pull`한 상태여야 한다.

아래는 **하나의 `&&` 체인**이다. 앞 단계가 실패하면 DROP이 실행되지 않는다. 체인을 끊어 DROP 줄만
따로 치지 않는다.

``` sh
prod_db \
  && C stop backend worker \
  && make db-backup ARGS="--pg-bin $PG_BIN" \
  && C exec -T postgres sh -c \
       'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  && echo reset
```

-   **맨 앞의 `prod_db`가 백업 대상을 DROP 전에 확인한다.** 백업은 셸의 `DATABASE_URL`을 따르고 DROP은
    compose의 postgres를 겨냥한다. 확인이 없으면 개발 DSN이 남은 셸에서 백업이 **개발 DB를** 백업하고
    성공한 뒤 운영 DB가 지워진다. 운영 DB의 초기화 직전 백업은 없고, 그 개발 DB 백업이 rotation으로
    가장 오래된 운영 백업 하나를 밀어낸다. 백업의 `target:` 줄을 읽는 것만으로는 막지 못한다 --- 읽을
    때는 DROP이 이미 실행된 뒤다.
-   `STOP: DATABASE_URL이 운영 DSN이 아니다`가 나오면 아무것도 실행되지 않았다. 터미널을 닫고 2.3부터 다시.
-   마지막 줄에 `reset`이 없으면 체인이 멈춘 것이다. `backup failed`라면 DROP 전이라 DB는 그대로다.
    `dropdb`/`createdb` 오류라면 DB가 없을 수 있다 --- 같은 `C exec` 줄만 다시 실행해 빈 DB를 만든다
    (백업은 이미 성공했다).
-   작은따옴표 안의 변수는 호스트가 아니라 컨테이너 셸에서 풀린다. DB 이름을 손으로 치지 않는다.

이어서(4.2\~4.7과 같은 확인을 한다):

``` sh
make db-migrate ARGS="--pg-bin $PG_BIN"          # 빈 DB라 빈 DB 백업이 하나 더 생긴다
printf '%s\n' "$DATABASE_URL"
make create-user ARGS="--login-id <LOGIN_ID>"
make seed                                        # 12.0과 같은 <N> items
make prompts ARGS="--provider openai --model gpt-4o-mini"
C up -d --no-deps worker backend
curl -s http://127.0.0.1:8000/api/health; echo
```

-   `generation_jobs`가 비었으므로 **그날의 사용량 집계도 0부터 다시 센다.**
-   휴대폰의 기존 로그인은 401이 되고 다시 로그인해야 한다(홈 화면 PWA도 따로).
-   초기화 직전 백업은 이후 백업이 6개 더 쌓이면 rotation으로 사라진다. 검증 기간 데이터는 버리기로
    한 데이터라 따로 보존하지 않는다.
-   7절 실기 확인을 다시 한다.

---

## 13. 재시작과 재부팅

-   세 컨테이너는 `restart: unless-stopped`이고 docker는 부팅 시 자동 기동이 켜져 있다. **재부팅하면
    docker가 컨테이너를 다시 띄운다.** 이 앱을 위한 systemd unit은 없다.
-   **`C stop`으로 멈춘 컨테이너는 재부팅 뒤에도 멈춘 채로 남는다.** migration이나 복원 훈련 도중에
    재부팅했다면 `C up -d --no-deps backend worker`를 직접 친다.
-   터널은 `<TUNNEL_SERVICE>`(systemd, 부팅 시 자동 기동)가 맡는다.

재부팅 뒤 확인:

``` sh
C ps postgres backend worker
curl -s http://127.0.0.1:8000/api/health; echo
systemctl is-active <TUNNEL_SERVICE>
curl -s -o /dev/null -w '%{http_code}\n' https://<API_HOST>/api/health
```

서비스 하나만 재시작: `C restart worker`(또는 `backend`). **`C restart postgres` 뒤에 backend를
따로 재시작할 필요는 없다** --- backend는 끊긴 DB 연결을 사용 전에 확인하고 다시 붙는다(실검증: postgres
재시작 직후 backend 재시작 없이 health `ok`, 로그인 유지). 재시작 전의 로그인 cookie와 학습 기록도 그대로다. `.env`를 바꿨다면 `restart`가 아니라
`C up -d --no-deps <서비스>`다.

---

## 14. 문제 해결

로그 보기: `C logs --tail 50 <postgres|backend|worker>`

| 증상 | 확인 | 원인과 조치 |
|---|---|---|
| `C ps worker`가 `Restarting` (알림 없이 간격을 늘리며 재시작만 반복한다) | `C logs --tail 30 worker` | `no active prompt_versions row` → 4.5를 안 했다. `relation ... does not exist` → 4.2를 안 했다. `app.llm.provider.ProviderConfigError: unknown LLM provider ''; supported: 'openai'` → `.env`의 `LLM_PROVIDER`가 비었거나 `openai`가 아니다. `... requires an API key` → `LLM_API_KEY`가 비었다. 고친 뒤 `C up -d --no-deps worker`. |
| `C ps worker`가 `Restarting`, 로그에 `ModuleNotFoundError: No module named 'sudachipy'` (MVP-02 이후) | `grep -c -- '--group furigana' infra/Dockerfile.worker` (1이어야 한다) | worker 이미지에 형태소 분석기가 없다. worker는 분석기가 없으면 일부러 기동하지 않는다. 옛 이미지를 띄웠거나 재빌드를 건너뛰었다. `C build worker` → 17.3의 worker 확인 → `C up -d --no-deps worker`. 호스트의 `make backfill-ruby`가 같은 오류로 끝나면 `uv sync`를 안 한 것이다(17.1). 그동안 학습 세션은 이미 만들어진 문장으로 계속된다. |
| `make backfill-ruby`의 출력에 `failed sentence=<id> error=<예외 타입>` | 같은 출력의 `ruby: ... failed=N` | 그 문장의 후리가나 계산이 실패했다. 그 문장은 `ruby_json`이 NULL로 남아 후리가나 없이 보일 뿐 학습에는 쓰인다. 명령은 exit 0이 아니다(`--apply`여도 나머지 문장은 이미 썼다 --- `updated N of M` 줄). 다시 실행하면 실패한 문장만 다시 계산한다. 계속 실패하면 id와 예외 타입을 적어 두고 진행한다. 데이터를 손으로 고치지 않는다. |
| `C ps backend`가 `Restarting` | `C logs --tail 30 backend` | `CORS_ALLOW_ORIGINS contains an invalid origin` → 끝의 `/`, path, 공백을 지운다. `auth_session_ttl_days` 검증 오류 → `.env`에 `AUTH_SESSION_TTL_DAYS=30`. |
| `C ps postgres`가 `Restarting`, `ls data/postgres`나 `git status`가 Permission denied | `C logs --tail 30 postgres` | `initdb: error: directory "/var/lib/postgresql/data" exists but is not empty`(`.gitkeep`) → `PGDATA`가 없는 옛 compose로 띄웠다. 14.1. |
| 운영 명령이 `password authentication failed` | `grep -c '^POSTGRES_PASSWORD=.*\$' .env` (1이면 `$`가 있다) | password에 `$`가 있었다면 DB가 다른 password로 초기화되었다(2.1). 이미 초기화된 DB의 password는 `.env`를 고쳐도 바뀌지 않는다. 데이터가 없는 첫 기동 직후라면 14.1과 같은 방식으로 `data/postgres/pgdata`를 비우고 영숫자 password로 다시 초기화한다(검증되지 않음, root 필요). `~/.pgpass` 권한(0600)과 사용자 이름도 본다. |
| 로그인 요청이 **403** | 5절 마지막 curl | 요청에 Origin이 없거나(브라우저 밖의 도구) `.env`의 `CORS_ALLOW_ORIGINS`가 브라우저 주소창의 origin과 글자 그대로 같지 않다(`https://`, 끝 `/`, 오타). 고친 뒤 `C up -d --no-deps backend`. |
| **로그인 직후 401**로 로그인 화면에 돌아옴 | 주소창 주소 | cookie가 저장·전송되지 않았다. `*.workers.dev` 주소로 들어왔다, `http://`다, 화면과 API가 다른 site다(0.2), 또는 iOS 홈 화면 PWA에서 Safari 로그인을 기대했다(7절). cookie 속성을 낮추는 설정은 없다 --- 주소를 고친다. |
| 화면에서 모든 요청이 "네트워크 실패" | `grep -rlF 'localhost:8000' frontend/dist` | 번들이 localhost를 가리킨다. 6.2의 체인을 **통째로** 다시 실행한다(grep이 있어 잘못된 번들은 배포되지 않는다). 번들이 맞다면 `https://<API_HOST>/api/health`를 휴대폰에서 연다. |
| compose가 `required variable NC_CONFIG_PATH is missing a value` | `grep NC_CONFIG_PATH .env` | `.env`에 값이 없다. `NC_CONFIG_PATH=/etc/nihongo-context/config.yaml`. `make db-up`도 같은 이유로 실패한다. |
| compose가 `invalid mount config for type "bind": bind source path does not exist: <경로>`로 exit 1 | `ls -l /etc/nihongo-context/config.yaml` | 정책 파일이 없다(3.1). 경로는 절대경로여야 한다. 호스트에 그 경로의 디렉터리는 생기지 않는다(생기지 않도록 설정되어 있다). 실패 전에 compose network는 이미 만들어지지만 남아도 해가 없다. 파일을 만든 뒤 같은 명령을 다시 친다. |
| backend/worker가 config 읽기 권한 오류 | `ls -l /etc/nihongo-context/config.yaml` | `-rw-r--r--`가 아니다. `sudo chmod 0644 /etc/nihongo-context/config.yaml`. |
| 생성이 멈춘 것 같다 | 3.4의 `grep cost.ceiling_reached` | 한도 도달. 한국시간 오전 9시에 풀린다. `jobs_with_unknown_tokens`가 0이 아니면 token 수를 모르는 호출 때문이다. 0이나 음수 한도를 넣었다면 영구 정지다(3.3). |
| 생성 job이 전부 `failed`, `last_error`에 `Error code: 401` | 8.2의 두 번째 SQL | OpenAI 키 오류. 4.6의 키 확인 → `.env` 수정 → `C up -d --no-deps worker`. |
| health의 `worker`가 `stale` | `C ps worker`, 로그 | worker가 멈췄거나 DB에 쓰지 못한다. |
| `make ...`가 엉뚱한 target을 출력 | `printf '%s\n' "$DATABASE_URL"` | 운영 셸이 아니다. 터미널을 닫고 2.3부터 다시. |
| 백업이 `--pg-bin` 실행 파일 오류 | `ls "$PG_BIN"/pg_dump` | `.venv`가 없거나 Python minor가 바뀌었다. `uv sync` 뒤 경로를 다시 확인한다(ADR-020 결정 2). |

### 14.1 옛 compose로 postgres를 한 번 띄워 `data/postgres`가 망가진 경우

`PGDATA` 설정이 없는 compose로 `C up -d postgres`를 한 번이라도 했다면 다음이 함께 보인다.

-   `C logs postgres`: `initdb: error: directory "/var/lib/postgresql/data" exists but is not empty`
    (`.gitkeep`이라는 점 파일 때문이다). postgres는 재시작을 무한히 반복한다.
-   컨테이너 entrypoint가 `data/postgres/`와 `.gitkeep`의 소유자를 `999`, 권한을 `700`으로 바꿔 놓아
    `ls data/postgres`가 Permission denied이고 `git status`도 그 디렉터리에서 Permission denied를 낸다.

초기화가 실패했으므로 그 안에 DB 데이터는 없다. 복구 방향은 "컨테이너를 멈추고 → 소유자와 권한을
Git이 만든 상태로 되돌리고 → `PGDATA`가 있는 compose로 다시 띄운다"이다.

> **아래 절차는 검증되지 않았다.** root 권한으로 파일 소유자를 바꾸는 작업이다. 한 줄씩 실행하고
> 결과를 본다. `sudo ls -la data/postgres`에 `.gitkeep` 말고 다른 것이 있으면 멈춘다.

``` sh
C stop postgres
sudo ls -la data/postgres                       # . .. .gitkeep 만 있어야 한다
sudo chown "$(id -u):$(id -g)" data/postgres data/postgres/.gitkeep
sudo chmod 0775 data/postgres
sudo chmod 0664 data/postgres/.gitkeep
git status --short data/postgres                # 출력 없음
git pull                                        # PGDATA가 있는 compose를 받는다
```

그다음 4.1을 처음부터 한다.


---

## 15. 알려진 한계

명세가 **결정하지 않은** 것들이다. 운영자가 알고 있어야 한다.

-   **출력 토큰 상한이 없다.** 요청에 출력 길이 상한을 싣지 않는다. 응답이 폭주하면 호출 한 번이
    모델의 최대 출력 길이까지 간다.
-   **실패한 호출은 한도에 잡히지 않는다.** timeout, 5xx, 429처럼 예외로 끝난 호출은 요청 수에도
    token 수에도 들어가지 않는다. SDK가 내부에서 재시도한 요청도 한 번으로 센다. 그래서 실제 요청 수는
    `daily_request_limit`이 세는 수보다 많을 수 있다.
-   **호출 하나가 30분을 넘길 수 있다.** OpenAI SDK 기본값이 요청당 timeout 600초에 재시도 2회다.
    job 회수 임계값(`claim_lease_seconds` 300초)보다 길다. 이때의 동작은 결정하지 않았다.
-   **한도에 0이나 음수를 넣으면 생성이 영구히 멈춘다.** 허용 범위를 로더가 검사하지 않는다.
-   **item 추가 적재가 없다.** 새 단어의 공급원은 seed뿐이고, 이미 적재된 DB에 item을 더하는 절차가
    없다. 본 사용이 시작된 뒤 item을 늘릴 방법은 초기화(12절, 학습 기록 삭제)뿐이다.
-   **로그인 시도 횟수 제한이 없다**(ADR-006). 방어는 16자 이상 password와 password hash 계산 비용뿐이다.
    Cloudflare rate limit은 선택이다(16절).

**그래서 실질적인 비용 안전장치는 OpenAI 쪽의 월 예산 한도다.** 앱의 하루 한도는 위 구멍 때문에
상한을 보장하지 못한다. OpenAI 대시보드에서 이 앱이 쓰는 project(또는 조직)의 월 사용 한도를 설정한다
(메뉴 위치는 확인 필요).

---

## 16. (선택) 로그인 요청 rate limit (Cloudflare)

이 저장소의 구현물이 아니며, 앱은 이것이 켜져 있다고 가정하지 않는다. 대시보드의 `<ZONE>` →
Security → WAF → **Rate limiting rules**에서 규칙 하나를 만든다(메뉴 위치와 요금제별로 고를 수 있는
기간·동작은 확인 필요).

``` text
조건        (http.host eq "<API_HOST>" and http.request.uri.path eq "/api/auth/login"
             and http.request.method eq "POST")
기준        IP
한도 예     10초에 5회
동작        Block (일정 시간)
```

켠 뒤 5절의 `422` curl을 연속으로 여러 번 쳐서 차단 응답(429 등)이 나오는지 본다. 사용자 본인이 잠기지
않을 만큼 넉넉하게 잡는다.

---

## 17. MVP-02 업데이트 (후리가나·선택 홈·가나, 1회)

MVP-01이 돌고 있는 운영에 MVP-02를 올리는 첫 업데이트다. **11절 대신 이 절을 따른다.** 모든 명령은 2.3의
운영 셸에서 친다.

이 절의 기대 출력은 운영과 분리된 로컬 DB(pgserver, seed만 적재)에서 **옛 코드로 계정·학습 기록을 만든 뒤
새 코드로 17.4\~17.7을 실제로 실행한 결과**다. 운영에서는 문장 수(`765`)와 통계 숫자가 다르고, 서버 버전은
`16.x`다. 이 리허설은 docker 없이 했다. 그래서 이미지 태그(17.2, 17.11 A)와 이미지 안의 확인(17.3)은
**확인 필요**다.

### 17.0 무엇이 바뀌나

``` text
DB          migration 0003 -> 0004. sentences.ruby_json JSONB NULL 컬럼 하나를 더한다(additive). 기존 행은 그대로다
            기존 문장의 후리가나는 migration이 아니라 backfill(make backfill-ruby)이 채운다
worker      이미지에 형태소 분석기(SudachiPy + 사전)가 들어간다. 이미지가 약 212M(압축 전) 커진다
            분석기가 없으면 worker는 기동하지 않는다
backend     의존성 그대로다. 분석기가 없고, 저장된 읽기를 응답에 실어 보내기만 한다
호스트      uv sync로 분석기가 .venv에 들어온다. backfill은 호스트에서 돈다
frontend    선택 홈, 상단바, 체험 확장, 글자 배우기, 후리가나 토글 -> 6.2로 다시 배포한다
그대로      config/default.yaml, .env, infra/docker-compose.yml, prompt, seed
```

-   **운영 DB를 초기화하지 않는다.** 계정과 학습 기록은 그대로 남는다.
-   정책 파일·compose·prompt·seed가 그대로이므로 **3절, 12절, `make prompts`는 하지 않는다.** 11절 1단계의
    diff만 한다.
-   순서: 사전 확인 → 이전 이미지 보존 → 재빌드(서비스는 계속 돈다) → 정지·백업 → migration → backfill →
    재기동 → 프론트 → 확인. **17.4부터 17.8까지 API와 worker가 멈춰 있다.**

### 17.1 사전 확인

``` sh
cd <REPO>
git status --short                 # 출력 없음
git rev-parse --short HEAD         # <PREV_COMMIT>로 적어 둔다
C images backend worker            # REPOSITORY 열을 <BACKEND_IMAGE>, <WORKER_IMAGE>로 적어 둔다
```

`git status`에 무엇이든 나오면 멈춘다. 적어 둔 세 값은 되돌리기(17.11)에 쓴다. 그다음 코드를 받는다.

``` sh
git pull
diff config/default.yaml /etc/nihongo-context/config.yaml    # 11절 1단계. 두 한도 줄만 달라야 한다
uv sync
uv run python -c 'import sudachipy, sudachidict_core; print("analyzer import ok")'
df -h .
```

-   `analyzer import ok`가 나와야 한다. `ModuleNotFoundError`면 `uv sync` 출력을 다시 본다. backfill이 이
    `.venv`로 돈다.
-   `df`의 Avail을 본다. worker 이미지 증가분, 보존하는 옛 이미지(17.2), 백업 세 개(17.4, 17.5, 17.7)가 더 필요하다.

### 17.2 이전 이미지 보존 (확인 필요)

재빌드(17.3)는 `latest` 이름을 새 이미지로 옮긴다. 그 전에 지금 이미지에 이름을 하나 더 붙여 둔다. 이름이
없어진 옛 이미지는 되돌리기(17.11 A)에 쓸 수 없다.

``` sh
docker tag <BACKEND_IMAGE>:latest <BACKEND_IMAGE>:pre-mvp02
docker tag <WORKER_IMAGE>:latest <WORKER_IMAGE>:pre-mvp02
docker image ls <BACKEND_IMAGE>; docker image ls <WORKER_IMAGE>   # 각각 latest와 pre-mvp02의 IMAGE ID가 같다
```

-   **확인 필요:** 리허설은 docker 없이 했다. `C images`의 TAG 열이 `latest`가 아니면 그 값으로 바꿔 친다.

### 17.3 이미지 재빌드

``` sh
C build backend worker
docker run --rm --pull never --network none <WORKER_IMAGE>:latest python -c 'import sys; sys.path.insert(0, "backend"); from app.furigana import load_analyzer; load_analyzer(); print("analyzer ok")'
docker run --rm --pull never --network none <BACKEND_IMAGE>:latest python -c 'import importlib.util as u; print("sudachipy", "present" if u.find_spec("sudachipy") else "absent")'
```

-   **실행 중인 컨테이너는 옛 이미지로 계속 돈다.** 새 이미지는 17.8에서 띄운다.
-   **build가 실패하면 여기서 멈춘다.** 두 Dockerfile은 `--no-build`로 `uv.lock`에 고정된 wheel만 설치한다.
    wheel이 없는 패키지가 있으면 컴파일로 넘어가지 않고 실패하는 것이 의도한 동작이다. 운영은 옛 이미지로
    그대로 돌고 있다.
-   기대: worker는 `analyzer ok`, backend는 `sudachipy absent`. backend가 `present`면 `infra/Dockerfile.backend`의
    `uv sync` 명령이 바뀐 것이다. 멈춘다(ADR-021 결정 6).
-   두 `docker run`은 이미지만 돌린다. `.env`, mount, 네트워크가 없다. `--pull never`: 이 호스트에서 방금 빌드한
    이미지만 쓰고, 이름이 틀려도 레지스트리에서 받아 오지 않고 실패한다.
-   **확인 필요:** 같은 두 명령을 호스트 Python으로는 확인했다(`analyzer ok`). 이미지 안에서는 확인하지 않았다.

### 17.4 정지와 백업 (rotation 밖)

`B`는 이번 업데이트 전용 백업 디렉터리다. 출력된 `pre-mvp02 backup dir:` 줄을 적어 둔다.

``` sh
B="data/backups/pre-mvp02/$(date -u +%Y%m%dT%H%M%SZ)" && printf 'pre-mvp02 backup dir: %s\n' "$B"
```

아래 체인은 한 덩어리로 붙여 넣는다.

``` sh
prod_db \
  && [ -n "$B" ] && [ ! -e "$B" ] \
  && C stop backend worker \
  && make db-backup ARGS="--pg-bin $PG_BIN --backup-dir $B" \
  && echo stopped-and-backed-up
```

기대 출력:

``` text
target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
pg_dump client: pg_dump (PostgreSQL) 16.2
server version: 16.x
backup verified: data/backups/pre-mvp02/<UTC>/backup-<UTC>.dump
backup written: data/backups/pre-mvp02/<UTC>/backup-<UTC>.dump
stopped-and-backed-up
```

-   **왜 따로 백업하나:** 17.5의 migration도 직전 백업을 만들지만 `data/backups/`의 7개 rotation 안이라 cron
    백업에 밀려 사라진다. `pre-mvp02/`는 Git 제외 경로 안이고 rotation이 세지 않는다. **17.10 통과 후 최소 7일
    보존한다**(cron rotation이 한 바퀴 돌면 이것이 유일한 0003 백업이다). 그동안 되돌리기(17.11 B)의 기준이다.
-   `<UTC>` 디렉터리는 `drwx------`, 파일은 `-rw-------`로 만들어졌다(리허설).
-   마지막 줄에 `stopped-and-backed-up`이 없으면:
    -   `STOP: DATABASE_URL이 운영 DSN이 아니다` → 아무것도 실행되지 않았다. 터미널을 닫고 2.3부터 다시.
    -   출력 없이 끝났다 → `B=` 줄을 빼먹었거나 체인만 다시 붙여 넣었다(`$B`가 이미 있다). 아무것도 실행되지
        않았다. `B=` 줄부터 다시.
    -   `backup failed` → 서비스만 멈춰 있고 DB는 그대로다. 원인을 고치기 전에 운영을 다시 켜려면
        `C start backend worker`를 친다. **`C up`이 아니다** --- `up`은 17.3에서 만든 새 이미지로 컨테이너를
        다시 만들 수 있다. `start`는 멈춘 옛 컨테이너를 그대로 다시 켠다.

### 17.5 migration

``` sh
prod_db && make db-migrate ARGS="--pg-bin $PG_BIN"
```

기대 출력:

``` text
target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
pending migrations: 0003 -> 0004
precondition: API and worker are stopped until the upgrade finishes (rollback = restoring the backup taken below)
pg_dump client: pg_dump (PostgreSQL) 16.2
server version: 16.x
backup verified: <REPO>/data/backups/backup-<UTC>.dump
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0003 -> 0004, sentences.ruby_json
alembic upgrade head: done (0003 -> 0004)
```

-   `db-migrate`는 `backup written:` 줄을 출력하지 않는다. `backup verified:`가 백업 완료다. 백업이 7개를
    넘으면 `rotated out: ...` 줄이 더 나온다.
-   `pending migrations:`가 `0003 -> 0004`가 아니면 멈춘다. `error: database revision ... is not in this code's
    migration history`는 코드와 DB가 맞지 않는다는 뜻이다. 17.1의 `git pull`과 `target:` 줄을 다시 본다.
-   `error: upgrade failed; roll back by restoring ...`가 나오면 17.11 B로 간다.

확인 --- 한 번 더 실행하면 아무것도 하지 않아야 한다.

``` sh
prod_db && make db-migrate ARGS="--pg-bin $PG_BIN"
# target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
# dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
# already at head (0004); nothing to do, no backup taken
```

``` sh
C exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT version_num FROM alembic_version;
SELECT count(*) AS total, count(*) FILTER (WHERE ruby_json IS NULL) AS null_rows FROM sentences;
SQL
```

기대: `0004`, 그리고 `total`과 `null_rows`가 같다(리허설: `765 | 765`). 이 `total`을 **N**으로 적어 둔다.

### 17.6 backfill dry-run (쓰기 없음)

``` sh
prod_db && make backfill-ruby; echo "exit=$?"
```

리허설 출력(seed 765문장):

``` text
target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
algorithm_version=2
sentences with ruby_json IS NULL: 765
ruby: algorithm_version=2 sentences=765 computed=765 failed=0 omitted_tappable_boundary=0 omitted_numeric=55 omitted_no_reading=0 corrected_explanation_tokens=508 corrected_table_rules=97 reading_mismatches=0 explanation_overrides=0 kanji_tokens=2097
rule 私->わたし hits=16
rule 明日->あした hits=28
rule 今日->きょう hits=34
rule 何->なに next=か|が|も|を hits=17
rule 中->じゅう prev=今日 hits=1
rule 中->じゅう prev=日 hits=1
rule 空い->すい prev=お腹,が hits=0
rule 空く->すく prev=お腹,が hits=0
dry-run: nothing written
exit=0
```

읽을 줄:

| 줄 | 기대 |
|---|---|
| `target:` | `host=127.0.0.1 port=5432 database=<POSTGRES_DB>`. 다르면 Ctrl-C |
| `algorithm_version=2` | `2` |
| `sentences with ruby_json IS NULL:` | 17.5의 N |
| `ruby: ...` | `computed=`가 N, **`failed=0`** |
| `rule ... hits=` | 교정 표 규칙별 적중 수. 0이어도 줄이 나온다. 참고용 |
| `mismatch kind=reading_mismatch` / `kind=explanation_override` | 설명의 읽기와 분석기의 읽기가 다른 곳. 참고용이며 실패가 아니다(종료 코드에 영향 없음). 설명 데이터를 자동으로 고치지 않는다. 리허설(seed만)에서는 0줄이었다. 생성 문장에서 나오면 줄을 적어 둔다 |
| `dry-run: nothing written` | DB에 아무것도 쓰지 않았다 |

`exit=0`이면 17.7로 간다. **그 밖이면** 원인을 출력 줄로 가른다(make는 실패 종류와 무관하게 같은 종료 코드를 낸다).

-   `failed sentence=<id> error=<예외 타입>` 줄이 있고 `failed=`가 1 이상 → 그 문장만 계산이 실패했다. 14절. 17.7로
    진행해도 된다(실패한 문장은 NULL로 남는다).
-   `ModuleNotFoundError: No module named 'sudachipy'` → 17.1의 `uv sync`. DB에 닿기 전에 끝났다.
-   `STOP: DATABASE_URL이 운영 DSN이 아니다` → 아무것도 실행되지 않았다. 2.3부터 다시.

### 17.7 backfill 적용

``` sh
prod_db && make backfill-ruby ARGS="--apply --pg-bin $PG_BIN" && echo applied
```

리허설 출력:

``` text
target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
algorithm_version=2
sentences with ruby_json IS NULL: 765
ruby: algorithm_version=2 sentences=765 computed=765 failed=0 ... (17.6과 같은 줄)
rule ... (17.6과 같은 여덟 줄)
pg_dump client: pg_dump (PostgreSQL) 16.2
server version: 16.x
backup verified: <REPO>/data/backups/backup-<UTC>.dump
updated 765 of 765 sentences
applied
```

-   쓰기 전에 검증된 백업을 만든다(건너뛰는 옵션은 없다). `backup written:` 줄은 없다.
-   `updated N of N sentences`: 두 수가 같고 17.6의 N이다. 계산 실패가 F개면 `updated N−F of N−F sentences`다
    (뒤의 수는 계산에 성공해 쓸 행 수다).
-   마지막 줄에 `applied`가 없으면:
    -   `error: backup failed; nothing was written: ...` → 아무것도 쓰지 않았다. 원인(디스크, `$PG_BIN`)을 고치고
        같은 명령을 다시 친다.
    -   `backfill_ruby.py: error: argument --pg-bin: expected one argument` → `$PG_BIN`이 비었다(`--pg-bin` 뒤에
        값이 없어 인자 해석에서 끝났다. 리허설 확인). 2.3의 운영 셸이 아니다. `--pg-bin` 자체를 빼먹었으면
        `error: --apply requires --pg-bin ...`이다. 둘 다 DB에 닿기 전에 끝났다.
    -   `updated ... of ... sentences` 뒤에 끝났다 → 계산 실패 문장이 있다(17.6과 같은 `failed sentence=` 줄).
        **나머지 문장은 이미 썼다.** 14절.

확인 --- 한 번 더 실행하면 쓸 것이 없어야 한다.

``` sh
prod_db && make backfill-ruby ARGS="--apply --pg-bin $PG_BIN" && echo applied
```

``` text
target: host=127.0.0.1 port=5432 database=<POSTGRES_DB>
dsn: postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
algorithm_version=2
sentences with ruby_json IS NULL: 0
ruby: algorithm_version=2 sentences=0 computed=0 failed=0 omitted_tappable_boundary=0 omitted_numeric=0 omitted_no_reading=0 corrected_explanation_tokens=0 corrected_table_rules=0 reading_mismatches=0 explanation_overrides=0 kanji_tokens=0
rule ... hits=0 (여덟 줄 모두 0)
nothing to write; no backup taken
applied
```

-   **두 번째의 `applied`는 "쓸 것이 없어 성공"이다.** 판단은 `nothing to write; no backup taken` 줄로 한다.
    백업도 생기지 않는다.
-   계산 실패 문장이 있었다면 `IS NULL:`이 그 수이고, 다시 계산해 또 실패하면 `applied` 없이 끝난다.

``` sh
C exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT count(*) AS total, count(*) FILTER (WHERE ruby_json IS NULL) AS null_rows FROM sentences;
SELECT ruby_json->>'algorithm_version' AS algorithm_version, count(*) FROM sentences WHERE ruby_json IS NOT NULL GROUP BY 1;
SQL
```

기대: `null_rows`가 0(계산 실패 문장이 있으면 그 수), `algorithm_version`은 `2` 한 행이고 그 count가
`total - null_rows`다(리허설: `765 | 0`, `2 | 765`).

### 17.8 재기동 (worker 먼저)

worker를 먼저 띄워 분석기가 이미지에 있는지 본다. 없으면 worker가 기동하지 않는다.

``` sh
C up -d --no-deps worker
sleep 40
C ps worker                                                       # STATUS가 "Up ..."
C logs worker 2>&1 | grep -c -E 'sudachi|ModuleNotFoundError'     # 0
C logs worker 2>&1 | grep -c 'cost.guard_disabled'                # 0
C logs worker 2>&1 | tail -20                                     # Traceback이 없어야 한다
```

-   `Restarting`이고 로그에 `No module named 'sudachipy'` → 새 이미지가 아니다. 14절. worker가 멈춰 있는
    동안에도 backend는 띄워도 된다. 학습 세션은 이미 만들어진 문장으로 계속된다.

``` sh
C up -d --no-deps backend
sleep 5
C ps backend
C images backend worker            # IMAGE ID가 17.2의 pre-mvp02와 달라야 한다
curl -s http://127.0.0.1:8000/api/health; echo
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs            # 404
```

health 기대값은 4.7과 같다(`database`와 `worker`가 `ok`).

### 17.9 프론트

**6.2의 체인을 그대로 한 덩어리로** 실행한다. 명령은 바뀌지 않았다. 체인의 두 grep은 MVP-02 번들에서도
그대로 성립한다(로컬 빌드로 확인: API 주소는 로그인 영역 청크에만 들어 있고 `localhost:8000`은 없다). backend
재기동(17.8) 뒤에 한다.

### 17.10 확인

데스크톱 브라우저로 `https://<FRONTEND_HOST>`를 열고 개발자 도구의 Network 탭을 켠다.

-   [ ] **서버 요청 0건:** 선택 홈, `표현 학습 체험해 보기`, `글자부터 배우기`를 오가는 동안 `<API_HOST>`로 가는
    요청이 없다. 상단바 `로그인`을 누를 때 처음으로 `/api/auth/me`가 한 번 나간다.
-   [ ] **로그인 흐름:** `로그인` → 로그인 화면 → 학습 화면. 새로고침하면 선택 홈이고, 다시 `로그인`을 누르면
    곧바로 학습 화면이다. `로그아웃`하면 선택 홈이다.
-   [ ] **후리가나:** 학습 화면 상단바 `후리가나`. 처음에는 꺼져 있다. 켜면 한자 위에 읽기가 나오고, 새로고침
    뒤에도 켜진 채다. backfill한 기존 문장에도 읽기가 있다. 설정은 이 브라우저에서 체험과 공유되므로, 체험에서
    먼저 켰다면 켜진 상태로 시작한다(그래서 이 확인을 체험보다 먼저 한다).
-   [ ] **글자 배우기:** 히라가나·가타카나 탭, 퀴즈 한 라운드, 결과.
-   [ ] **체험:** 진행 표시가 `0 / 171`에서 시작한다. 몇 문장 본 뒤 새로고침하면 같은 위치에서 이어진다.
    `진도 초기화` → `초기화하기`면 처음부터다. (시간이 있으면) 끝까지 보면 완료 화면이 나온다.
-   [ ] **health:** 17.8의 `curl`이 `ok` / `ok`.
-   [ ] **DB:** 17.7의 SQL에서 `null_rows`가 그대로다.
-   [ ] **로그:** 아래 두 수가 0이다.

    ``` sh
    C logs --since 24h worker 2>&1 | grep -c -E 'ruby\.(failed|log_failed)'
    C logs --since 24h backend 2>&1 | grep -c 'ruby.invalid_stored'
    ```

-   [ ] **휴대폰:** 7절 전체. iOS 홈 화면 PWA는 Safari와 cookie 저장소가 따로라 PWA 안에서 다시 로그인한다.

### 17.11 되돌리기

문제의 범위에 맞는 것 하나를 고른다.

``` text
화면만 문제                 -> 프론트만: <PREV_COMMIT>으로 6.2
backend·worker가 문제       -> A 이미지만 (DB는 0004 그대로, 학습 기록 보존)
DB까지 되돌려야 한다        -> B pre-mvp02 백업 복원 (17.4 백업 이후의 모든 쓰기가 사라진다)
후리가나 읽기만 문제        -> C ruby_json만 비운다
```

#### 프론트만

``` sh
cd <REPO> && git switch --detach <PREV_COMMIT>
```

그 상태에서 6.2 체인을 실행하고, 끝나면 돌아온다.

``` sh
cd <REPO> && git switch -          # 17.1에서 pull한 브랜치로
```

-   **detach한 동안 `make db-migrate`, `make db-restore-check`, `make backfill-ruby`를 치지 않는다.** 옛 코드는
    0004를 모른다(리허설: 옛 코드의 `make db-migrate`가 `error: database revision '0004' is not in this code's
    migration history`로 멈췄다).
-   옛 화면은 새 API와 함께 돈다(새 응답의 필드는 추가뿐이다). 반대로 **새 화면은 옛 API와 돌지 않는다** ---
    옛 API 응답에는 `ruby`가 없다. 그래서 A는 프론트를 먼저 되돌린다.

#### A. 이미지만

리허설: 옛 코드(API)를 migration·backfill이 끝난 0004 DB에 붙여 login, `/api/auth/me`, 세션 시작, `/next`,
`/click`, `/complete`, history가 모두 200이었다. 새 코드로 학습한 뒤 다시 붙였을 때도 같았다.

먼저 위의 "프론트만"을 한다. 그다음:

``` sh
docker tag <BACKEND_IMAGE>:pre-mvp02 <BACKEND_IMAGE>:latest
docker tag <WORKER_IMAGE>:pre-mvp02 <WORKER_IMAGE>:latest
C up -d --no-deps --no-build backend worker
C images backend worker            # IMAGE ID가 17.2의 pre-mvp02와 같다
curl -s http://127.0.0.1:8000/api/health; echo
```

-   `<REPO>`의 코드는 새 커밋에 둔다. DB가 0004이므로 호스트 운영 명령도 새 코드로 친다.
-   **되돌린 동안 `C build`를 치지 않는다.** 새 코드로 다시 빌드되어 `latest`가 새 이미지가 된다.
-   옛 API는 `ruby_json`을 읽지 않는다(화면에 후리가나 없음). 옛 worker가 만든 문장은 `ruby_json`이 NULL로
    남는다. 다시 올릴 때는 17.3(재빌드) → 17.8(재기동) → 17.6·17.7(그 문장만 채운다) → 17.9(프론트 재배포)다.
    17.4(pre-mvp02 백업)와 17.5(migration)는 하지 않는다. DB가 이미 0004라 17.5는 `already at head (0004)`로
    끝나고, 17.7이 쓰기 전에 백업을 만든다.
-   **확인 필요:** 태그를 되돌린 뒤 `up`이 컨테이너를 옛 이미지로 다시 만드는지(리허설은 docker 없이 했다).
    옛 worker가 0004 DB에서 생성 job을 처리하는지(provider 호출이 필요해 리허설하지 않았다).

#### B. DB까지 (pre-mvp02 백업 복원)

downgrade 명령은 없다. 17.4의 백업을 10.2 절차로 복원한다.

> **17.4 백업 이후의 모든 쓰기가 사라진다.** 학습 기록, 생성된 문장·job과 그 LLM 비용, 로그인 세션, 계정·비밀번호
> 변경이 전부다. 운영한 날이 길수록 잃는 것이 많으므로 **A나 C로 풀리는지 먼저 본다.** 10.2 체인이 복원 직전에
> 만드는 안전 백업 `$R`이 **그 쓰기들의 유일한 사본**이다. 10.2의 정리 규칙대로, 운영이 정상임을 확인하기 전에는
> 지우지 않는다.

리허설: 17.4의 백업을 별도 DB에 10.2와 같은 `pg_restore` 옵션으로 복원해 `restored`, `alembic_version`
`0003`, 옛 코드로 만든 학습 행 보존, `ruby_json` 컬럼 없음을 확인했다.

-   **10.1(`make db-restore-check`)은 하지 않는다.** 그 검증은 백업을 지금 DB와 비교한다. pre-mvp02 백업은
    지금 DB(0004, 그 뒤의 쓰기)와 다르므로 반드시 실패한다.

1.  10.2의 경고대로 **백업을 만든 시점의 코드로 먼저 돌아간다.**

    ``` sh
    cd <REPO> && git switch --detach <PREV_COMMIT> && uv sync
    ls -l <PRE_MVP02_BACKUP_DIR>/      # 17.4에서 적어 둔 pre-mvp02 backup dir. backup-*.dump 하나
    ```

2.  **프론트를 먼저 되돌린다:** 6.2 체인을 실행한다(이미 `<PREV_COMMIT>`에 있다). 옛 화면은 지금의 새 API와도
    돌지만, 새 화면은 복원 뒤의 옛 API와 돌지 않는다(A와 같은 이유).
3.  10.2를 한다. `F=`에는 위 디렉터리의 그 파일 경로를 넣는다. `R=` 줄과 체인은 10.2 그대로다.
4.  이미지를 되돌린다: A의 `docker tag` 두 줄.
5.  10.2의 "복원 뒤"를 한다. `make db-migrate`는 옛 코드라 `already at head (0003)`이다.
    17.4 이후 비밀번호를 바꿨거나 세션을 끊었다면(로그아웃·폐기) 복원으로 옛 비밀번호 hash와 세션이 되살아나므로
    복원 뒤 다시 한다.

MVP-02를 다시 시도할 때는 `git switch -`로 돌아와 17.1부터 한다.

#### C. 후리가나만 비우기

``` sh
prod_db && C exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
UPDATE sentences SET ruby_json = NULL;
SQL
```

-   기대: `UPDATE <total>`(리허설: `UPDATE 765`). 학습 기록은 그대로다. 표시 보조 컬럼만 비운다.
-   **C는 백업을 만들지 않는다.** 지운 값은 backfill 재계산으로만 다시 생긴다.
-   후리가나를 켜도 읽기가 나오지 않는다. worker가 새로 만드는 문장에는 다시 계산되어 들어간다.
-   **같은 코드로 다시 채우면 같은 값이 다시 들어간다.** 읽기가 틀려서 비웠다면 코드를 고친 뒤에만 17.6·17.7을
    다시 돌린다(리허설: 비운 뒤 `IS NULL: 765`, `updated 765 of 765 sentences`).
-   worker가 생성할 때 넣은 원래 값과 backfill이 다시 계산한 값은 다를 수 있다(backfill은 그 시점의 설명 읽기로
    계산한다).

#### pre-mvp02 백업과 이미지 정리

**17.10 통과 후 최소 7일 보존한다**(cron rotation이 한 바퀴 돌면 이것이 유일한 0003 백업이다). 그 전에는
17.11 B의 기준이다. 그 뒤에 이상이 없으면 지운다. rotation이 세지 않으므로 직접 지운다(password hash가 들어 있다).

``` sh
ls -l data/backups/pre-mvp02/
rm -r data/backups/pre-mvp02
docker image rm <BACKEND_IMAGE>:pre-mvp02 <WORKER_IMAGE>:pre-mvp02    # 이름만 지운다 (확인 필요)
```
