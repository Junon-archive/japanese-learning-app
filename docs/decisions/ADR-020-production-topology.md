# ADR-020 --- 운영 토폴로지: 단일 호스트 compose, 호스트 운영 CLI, 기존 터널

Status: Accepted (결정 6 개정 2026-09-13)

Decision: MVP 운영은 **이 머신 한 대**에서 한다.
PostgreSQL·API·worker는 `infra/docker-compose.yml`로 띄우고, API는 이 호스트에
이미 돌고 있는 cloudflared 터널에 규칙 하나를 더해 공개하며, frontend는
Cloudflare Workers Static Assets에 올린다. 운영 CLI(migration, 백업, 계정, seed,
prompt)는 **컨테이너가 아니라 호스트에서 `uv run`으로** 실행한다.

``` text
Browser ── https://<FRONTEND_HOST> ── Workers Static Assets (Custom Domain)
        └─ https://<API_HOST> ─────── 기존 cloudflared 터널 (호스트 systemd)
                                          └─ http://127.0.0.1:8000  backend 컨테이너
                                             worker 컨테이너
                                             postgres 컨테이너 ── 127.0.0.1:5432
호스트 운영 CLI (uv run) ─────────────────────┘  (터널에 넣지 않는다)
```

결정은 아홉 개다.

``` text
1  운영 CLI 실행 위치     호스트 uv run, DSN만 127.0.0.1:5432 (password 없음, ~/.pgpass)
2  pg_dump 바이너리       호스트 바이너리 한 형태: DATABASE_URL + --pg-bin DIR
                          운영 DIR = pgserver 번들(16.2). compose exec는 백업에 쓰지 않는다
3  정책 override 파일     /etc/nihongo-context/config.yaml, 호스트와 컨테이너가 같은 절대경로
                          compose가 ${NC_CONFIG_PATH:?}로 source/target을 채우고
                          long syntax + create_host_path: false
4  cloudflared            기존 ~/.cloudflared/config.yml의 catch-all 앞에 API 규칙 1개
                          service = http://127.0.0.1:8000. API만 노출한다
5  frontend 배포          wrangler CLI flag 배포 (설정 파일 없음), Custom Domain은 대시보드,
                          workers.dev 끄기, 빌드 산출물 grep으로 API origin 확인 후에만 배포
6  도메인 표기            커밋되는 모든 파일은 <FRONTEND_HOST> / <API_HOST> 자리표시자
                          (개정 2026-09-13: README의 사이트 주소 1개만 예외)
7  seed 초기화 경로       db_reset의 production 거부를 유지한다. 새 코드 없이 문서의
                          수동 절차로 하되, 대상 DSN 확인 → 백업 → DROP을 하나의 && 체인으로
                          묶는다. compose는 셸 환경을 비운 wrapper(env -i)로 부른다
8  재부팅 후 기동          restart: unless-stopped + docker 부팅 활성화. systemd unit 없음
                          정기 백업은 사용자 crontab 한 줄
9  에이전트 compose 검증  sg docker, 별도 project(-p), scratchpad env/override,
                          운영 port·data 디렉터리 미사용, down -v로 전부 제거.
                          실검증 19개 항목 통과. 발견한 .gitkeep 결함은 PGDATA 하위 디렉터리로 해결
```

postgres 서비스는 `PGDATA=/var/lib/postgresql/data/pgdata`를 둔다. bind mount 루트(`data/postgres/`)가
아니라 그 **하위 디렉터리**에 클러스터를 만든다(결정 9의 `.gitkeep` 절).

## 문제

Wave 4까지의 명세와 코드는 "배포는 docker compose, API는 Tunnel, frontend는
Workers Static Assets"라는 방향만 정했다(ADR-001, `spec/02_ARCHITECTURE.md`).
실제로 운영하려면 다음이 정해져 있어야 하는데 어느 문서에도 없었다.

-   운영 CLI를 컨테이너와 호스트 중 어디서 돌리는가. `.env`의 `DATABASE_URL`은
    컨테이너용(`@postgres:5432`)이라 호스트에서 그대로 쓸 수 없다.
-   백업의 pg_dump를 어디서 가져오는가. 호스트에는 시스템 postgres 바이너리가 없다.
-   `NC_CONFIG_PATH`가 가리키는 override 파일을 어디에 두고 두 컨테이너에 어떻게
    넣는가. 명세는 파일을 **작업 트리 밖**에 두라고 한다
    (`spec/mvp-01-core/14_CONFIGURATION.md`의 `production override`).
-   이 호스트에는 이미 다른 서비스를 라우팅하는 cloudflared 터널
    (`<TUNNEL_SERVICE>`, locally-managed, `--config ~/.cloudflared/config.yml`)이
    있다. 새 터널을 만들지, 거기에 더할지.
-   기술 검증용 seed(7 item)로 운영 DB를 한 번 채운 뒤 확장 seed로 **한 번 초기화**해야
    하는데, `make db-reset`은 `APP_ENV=production`에서 거부된다.

사용자가 확정한 전제는 다음이다(다시 열지 않는다).

``` text
운영 호스트      이 머신. Docker Engine + compose plugin은 사용자가 설치했다
                (Compose v5.5.1, docker/containerd enabled)
터널            기존 터널에 규칙 추가. 재시작 시 같은 터널의 기존 서비스의 짧은 중단을 수용
주소            사용자 zone의 1단계 서브도메인 두 개 (화면용, API용). same-site
LLM             OpenAI gpt-4o-mini
사용량 한도      첫날 30 요청 / 60000 token, 이상 없으면 100 / 200000
백업            하루 1회, 최근 7개. 다른 물리 위치 사본은 지금 하지 않는다
seed            7 item으로 검증 → 확장 seed로 DB를 한 번 초기화 → 본 사용. 추가 적재 기능 없음
```

---

## 결정 1 --- 운영 CLI는 호스트에서 `uv run`으로 실행한다

migration, 백업, restore 검증, `create-user`, `seed`, `prompts`는 전부 repo 루트에서
`uv run`(= 기존 `make` 타깃)으로 실행한다. 컨테이너와 달라지는 것은 DSN 하나다.

``` text
컨테이너 (.env)    postgresql+psycopg://<POSTGRES_USER>:<password>@postgres:5432/<POSTGRES_DB>
호스트 (셸/cron)   postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>
                   password는 DSN에 넣지 않는다 → ~/.pgpass (0600)
                   127.0.0.1:5432:*:<POSTGRES_USER>:<password>
```

-   호스트 DSN에는 **password가 없다.** libpq(psycopg와 pg_dump 모두)가 `~/.pgpass`를
    읽는다. 그래서 호스트 DSN은 crontab, 셸 history, 화면 출력에 그대로 남아도 된다.
    데이터베이스 필드를 `*`로 두는 이유는 restore 검증이 별도 DB에 붙기 때문이다.
-   운영 셸에서는 `APP_ENV=production`을 호스트 DSN과 **같은 export 줄에** 둔다.
    `make db-reset`의 production 거부는 호출한 셸의 `APP_ENV`만 보기 때문이다
    (`scripts/db_reset.py`). 둘을 따로 설정하면 거부가 빠진 채 운영 DSN이 쓰일 수 있다.
-   `create-user`는 config를 읽으므로(`user.user_timezone`) 운영 셸에서
    `NC_CONFIG_PATH`도 결정 3의 경로로 export 한다. 경로가 호스트와 컨테이너에서 같으므로
    `.env`의 값을 그대로 쓴다.

### 엉뚱한 DB에 적용되는 위험과 완화

DSN이 두 가지라 틀린 DSN으로 실행할 위험이 있다. 실제로 조용히 틀리는 조합은 하나다.

``` text
컨테이너 DSN을 호스트에서     host "postgres"가 풀리지 않는다         → 즉시 실패 (시끄럽다)
호스트 DSN을 컨테이너에서     127.0.0.1은 그 컨테이너 자신이다        → 연결 거부 (시끄럽다)
로컬 개발 DSN을 운영 셸에서   이 머신에는 pgserver 개발 DB(ADR-002)도  → 성공한다 (조용하다)
                              있다. 운영 대신 개발 DB에 적용된다
```

**이 머신은 운영 호스트이자 개발 머신이다.** 그래서 migration과 백업 명령은 **작업 전에
password를 가린 대상 DSN을 출력한다**(`spec/mvp-01-core/04_DB_SPEC.md`의
`운영 DB에 migration을 적용하는 경로` 1단계, `make db-reset`의 기존 출력과 같은 형태).
운영 DSN은 `127.0.0.1:5432`, pgserver DSN은 `host=` unix socket 경로라서 한 줄로
구분된다. pgserver는 TCP를 열지 않으므로(`-h ""`) 5432를 두고 compose와 겹치지 않는다.

### 버린 대안

-   **`docker compose run --rm backend <명령>`.** DSN이 하나로 줄어드는 것이 유일한
    이점이다. 대가: backend·worker 이미지에 `alembic.ini`와 `seed/`가 없고, backend
    이미지에는 `scripts/`도 없다. 넣으면 런타임 이미지에 운영 도구와 seed 데이터가
    실리고, 이미지에는 pg 클라이언트도 없으므로 백업은 결국 따로 해결해야 한다. 백업 파일을
    `data/backups/`에 쓰려면 bind mount가 또 필요하고 그 파일은 컨테이너 uid(10001) 소유로
    생겨 호스트 사용자가 다루기 어렵다. 게다가 `password` 프롬프트가 있는
    `create-user`는 TTY 전달까지 신경 써야 한다.
-   **호스트 DSN에 password를 넣는다.** crontab 줄은 cron이 `sh -c`로 실행하는 동안
    프로세스 인자로 보이고, 셸 history에도 남는다. `~/.pgpass`로 충분하다.

### 근거

-   기존 Makefile·scripts·테스트가 전부 호스트 경로다. 운영을 위해 새 실행 경로를 만들지
    않는다.
-   compose가 postgres를 `127.0.0.1:5432`에만 publish하므로(인터넷 비노출은 유지)
    호스트에서 그대로 붙을 수 있다.
-   백업과 migration이 **같은 DSN**을 쓰므로 "migration 직전 백업이 migration 대상과
    같은 DB"라는 조건이 구성으로 성립한다(결정 2의 핵심 근거).

---

## 결정 2 --- pg_dump는 호스트 바이너리 한 형태, 운영은 pgserver 번들

백업·검증·restore 명령은 로컬과 운영 모두 **`DATABASE_URL` + `--pg-bin DIR`** 한 형태로
부른다. `--pg-bin`은 필수 인자다(기본값도 PATH 탐색도 없다). 운영의 DIR은 pgserver 번들이다.

``` text
로컬 검증   <REPO>/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin   pg_dump 16.2 (실측)
운영        같은 경로 (운영 호스트 = 이 머신)
```

-   password는 **argv에 넣지 않는다.** DSN에 password가 없으면 libpq가 `~/.pgpass`를
    읽는다. DSN에 password가 있으면(테스트용 일회성 DB 등) 스크립트가 자식 프로세스
    환경의 `PGPASSWORD`로 넘긴다. argv는 같은 호스트의 모든 사용자가 `ps`로 볼 수 있지만
    프로세스 환경은 같은 사용자와 root만 읽는다.
-   SQLAlchemy DSN(`postgresql+psycopg://`)은 libpq가 읽지 못한다. 스크립트가 host / port /
    user / dbname으로 풀어 넘기며, pgserver의 unix socket DSN(`?host=<dir>`)도 같은 규칙으로
    처리한다.
-   백업 출력에 **클라이언트와 서버 버전을 함께 남긴다**(`pg_dump --version`,
    `SHOW server_version`). 버전 차이가 로그에서 보이게 하기 위해서다.
-   **운영 경로는 dev dependency group에 기댄다. pgserver 번들만이 아니다.** restore 검증
    (`scripts/db_restore_check.py`)은 복원 DB에 붙인 API를 `fastapi.testclient`로 부르고, 그 client가
    쓰는 `httpx2`는 dev group이다. 결정 1의 호스트 `uv run`은 dev group까지 sync하므로 동작에는 문제가
    없다. 운영 호스트를 `uv sync --no-dev`로 바꾸면 백업·migration(`--pg-bin` 경로 없음)과 restore
    검증(import 실패)이 함께 시끄럽게 실패한다. 아래 (a)의 "dev group에 묶여 있다"와 같은 조건이다.

### 세 선택지의 귀결 (docker 설치 후 재판단)

**(a) pgserver 번들 (채택).**
-   추가 설치가 없다. 결정 1의 `uv run`이 동작하는 호스트에는 이미 있다(`uv run`은 dev
    group을 sync한다).
-   backup/restore 테스트(`spec/mvp-01-core/12_TEST_PLAN.md`)가 쓰는 바이너리와 **같은
    바이너리**가 운영에서 돈다.
-   16.2에 고정되어 있다. 서버 `postgres:16`은 minor가 따라 오른다. pg_dump는 **서버 major가
    클라이언트보다 높을 때만** 거부하므로 16.2로 16.x는 문제없다. 16.2 이후 minor에서 고쳐진
    pg_dump 결함은 받지 못한다(예: 16.4의 보안 수정은 dump 도중 DB 객체를 만들 수 있는 행위자를
    전제로 한다. 이 배포에서 그런 행위자는 앱의 DB superuser 자신이다).
-   dev group에 묶여 있다. 운영 호스트에서 `uv sync --no-dev`를 하면 사라지고, Python minor가
    바뀌면 경로가 바뀐다. 어느 쪽이든 `--pg-bin` 경로가 없어 **백업이 non-zero로 끝난다**.
    조용한 실패가 아니다.

**(b) `postgresql-client-16` apt 설치.**
-   호스트 OS 기본 저장소의 PostgreSQL 클라이언트는 16보다 낮았다(판단 시점 확인). 낮은 major의 pg_dump는
    16 서버를 거부한다. 16을 쓰려면 PGDG apt 저장소(apt.postgresql.org)를 추가해야 한다(sudo, 외부 저장소 신뢰).
-   minor 보안 수정을 apt로 받는다. 형태는 (a)와 같고 DIR만 `/usr/lib/postgresql/16/bin`이다.

**(c) `docker compose exec -T postgres pg_dump`.**
-   서버와 **완전히 같은 바이너리**다. 버전 불일치 위험이 셋 중 가장 낮고, 호스트 설치도
    password도 필요 없다(컨테이너 안 unix socket).
-   그러나 연결 대상이 **DSN이 아니라 compose 서비스**가 된다. socket으로 붙으면 user와 DB는
    컨테이너 환경(`POSTGRES_USER`, `POSTGRES_DB`)에서 온다. 그러면:
    -   migration 경로의 "대상 DSN 출력 → 그 DB를 백업 → 그 DB에 upgrade"가 깨진다. alembic은
        호스트 DSN으로, 백업은 compose 서비스로 가므로 **둘이 같은 DB라는 보장이 구성에서
        사라진다.** 셸의 DSN이 개발 DB를 가리키면 운영 DB를 백업하고 개발 DB를 migrate하고도
        둘 다 성공한다. 이것을 막으려면 양쪽에서 `system_identifier`를 읽어 비교하는 코드를
        새로 넣어야 한다.
    -   출력한 대상 DSN과 실제로 dump한 DB가 다를 수 있다. 출력이 확인 수단 구실을 못 한다.
    -   TCP로 붙어 DSN을 따르게 하면 password를 exec 안으로 넘겨야 한다. 게다가 컨테이너 안의
        `127.0.0.1:5432`가 호스트 DSN의 `127.0.0.1:5432`와 같은 서버라는 것은 publish port와
        컨테이너 port가 같을 때만 성립한다.
    -   한 스크립트가 두 argv 형태(`<DIR>/pg_dump` / `docker compose exec ... pg_dump`)를
        가지면 로컬 테스트는 한쪽만 실행한다.

### 두 형태를 한 스크립트로 어떻게 맞추는가

**맞추지 않는다. 형태를 하나만 둔다.** 버전 정확성(c)과 대상 일치(a)가 부딪히는 자리이며,
이 배포에서 더 비싼 사고는 대상 불일치다. 버전 차이는 같은 major 안에서는 실패하지 않고,
major가 어긋나면 pg_dump가 시끄럽게 거부한다. 대상 불일치는 두 명령이 모두 성공한 채로
일어난다.

`docker compose exec postgres`는 **일회성 관리 작업**(결정 7의 DROP/CREATE)에만 쓴다. 거기서는
"compose 서비스만 겨냥할 수 있다"는 성질이 원하는 안전장치다.

### 바꿔야 하는 조건

다음 중 하나가 성립하면 `--pg-bin`만 (b)의 DIR로 바꾼다. 코드 변경은 없다.

``` text
서버 이미지 major를 올린다       반드시 서버 upgrade 전에 바꾼다 (16.2는 17 서버를 dump하지 못한다)
uv.lock 갱신으로 번들 major가 바뀐다
운영 호스트가 dev group 없이 sync 해야 한다
16.2 이후 pg_dump 수정이 이 배포에 해당하게 된다
```

---

## 결정 3 --- 정책 override 파일: `/etc/nihongo-context/config.yaml`

``` text
호스트 경로       /etc/nihongo-context/config.yaml   (root 소유 0644, 디렉터리 0755)
컨테이너 경로     /etc/nihongo-context/config.yaml   (같은 절대경로, read-only)
.env              NC_CONFIG_PATH=/etc/nihongo-context/config.yaml
운영 셸           같은 값을 export (create-user가 읽는다)
```

compose의 backend와 worker에 **같은 mount**를 둔다. 형태는 다음이다(배선은 뒤따르는 작업).

``` yaml
x-policy-mount: &policy-mount
  type: bind
  source: ${NC_CONFIG_PATH:?NC_CONFIG_PATH must be the absolute path of the policy file}
  target: ${NC_CONFIG_PATH:?NC_CONFIG_PATH must be the absolute path of the policy file}
  read_only: true
  bind:
    create_host_path: false
```

-   **작업 트리 밖이다.** 명세가 요구한다. Git 제외가 `.gitignore` 한 줄에 기대지 않고,
    `COPY config ./config`가 사본을 이미지에 구워 넣지도 않는다.
-   **호스트와 컨테이너가 같은 절대경로다.** `source`와 `target`을 같은 변수로 채우므로
    mount와 `NC_CONFIG_PATH`가 어긋날 수 없다. 상대경로는 쓰지 않는다. 앱은 상대경로를
    cwd(컨테이너 `/app`, 호스트 repo 루트)로 풀고 compose는 bind source를 compose 파일
    디렉터리(`infra/`)로 풀어 둘이 갈린다. 상대경로를 넣으면 docker가 상대 target을
    거부하므로 시끄럽게 실패한다.
-   **파일이 없을 때 docker가 디렉터리를 만들어버리는 문제**: short syntax
    (`src:dst`)는 source가 없으면 호스트에 **root 소유 디렉터리**를 만든다. 그 뒤 로더는
    디렉터리를 읽으려다 실패하고, 호스트에는 sudo로 지워야 하는 디렉터리가 남는다. long
    syntax에 `create_host_path: false`를 **명시**하면 컨테이너 생성 단계에서 오류로 끝난다.
    기본값에 기대지 않고 적는다.
-   **`${NC_CONFIG_PATH:?}`는 비어 있어도 실패한다.** `.env`에서 값을 잊으면 컨테이너가
    `config/default.yaml`(두 한도 `null`)로 조용히 도는 대신 compose가 아무것도 띄우지 않는다.
    명세가 "production은 두 한도를 둘 다 integer로 켠다"고 했으므로 이 실패가 맞다.
-   `/etc` 아래 root 소유라 수정에 sudo가 필요하다. 한도 변경은 드문 작업이고, 실수로 고치기
    어려운 쪽이 낫다. 0644는 필수다. 컨테이너 사용자(uid 10001)가 읽어야 한다. 내용에 secret이
    없으므로 공개 읽기로 충분하다.

만들기와 한도 올리기(명세의 diff 규칙을 따른다):

``` sh
sudo install -d -m 0755 /etc/nihongo-context
sudo install -m 0644 config/default.yaml /etc/nihongo-context/config.yaml
sudoedit /etc/nihongo-context/config.yaml     # daily_request_limit: 30, daily_token_limit: 60000
diff config/default.yaml /etc/nihongo-context/config.yaml   # 기대하는 차이는 두 줄뿐
# 이상 없으면 100 / 200000으로 고치고 worker만 재시작한다 (14_CONFIGURATION.md)
```

### 귀결

-   **compose 파일의 모든 명령이 `NC_CONFIG_PATH`를 요구한다.** interpolation은 파일 전체에
    적용되므로 `make db-up`(postgres만)도 값이 없으면 실패한다. compose는 배포 경로이고 개발
    머신은 pgserver를 쓰므로(ADR-002) 받아들인다. `.env.example`의 "비워두면 default.yaml"
    설명은 compose 밖(호스트 실행)에만 맞는 말이 되므로 뒤따르는 작업이 고친다.
-   worker는 실제 키로 도는데 한도가 `null`이면 기동 시 `cost.guard_disabled`를 남긴다.
    첫 기동 뒤 worker 로그에 이 이벤트가 **없는** 것을 확인 항목으로 둔다.

### 버린 대안

-   **`config/production.yaml`(작업 트리 안, gitignore).** 명세가 금지한다. 추가로
    `.dockerignore`에도 넣지 않으면 이미지에 옛 사본이 구워진다.
-   **`~/.config/nihongo-context/config.yaml`.** 작업 트리 밖이지만 같은 절대경로를
    컨테이너에 두면 컨테이너 안에 사용자 이름이 박힌 경로가 생긴다. 사용자 권한으로 쓰기
    가능하고 umask에 따라 0600으로 만들어져 컨테이너가 못 읽을 수도 있다.
-   **compose에 경로를 고정하고 `.env`는 따로 둔다.** 같은 값이 두 곳에 있어 어긋날 수 있고,
    `.env`에서 값이 빠지면 mount는 있는데 default.yaml로 도는 조용한 상태가 된다.
-   **production 전용 compose override 파일(`-f` 두 개).** backend/worker를 compose로 띄우는
    환경은 운영뿐이라 나눌 대상이 없다. 명령 형태만 둘로 늘어난다.

---

## 결정 4 --- cloudflared: 기존 터널에 API 규칙 하나

기존 터널 서비스(`<TUNNEL_SERVICE>`)가 읽는 `~/.cloudflared/config.yml`의 `ingress:`에서
**catch-all(`service: http_status:404`) 바로 앞에** 규칙 하나를 넣는다.

``` yaml
  - hostname: <API_HOST>
    service: http://127.0.0.1:8000
  # 기존 catch-all은 마지막 그대로
  - service: http_status:404
```

절차(사용자가 실행한다):

``` sh
cp ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak.$(date +%Y%m%d-%H%M%S)  # 기존 관례
# 규칙 추가
cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://<API_HOST>/api/health
    # 새 규칙이 127.0.0.1:8000으로 매칭되는지 확인
cloudflared tunnel route dns <TUNNEL_NAME> <API_HOST>     # DNS CNAME
sudo systemctl restart <TUNNEL_SERVICE>                  # 같은 터널의 기존 서비스가 잠깐 끊긴다
# 되돌림: .bak 복원 후 같은 restart
```

-   **`127.0.0.1`이지 `localhost`가 아니다.** `localhost`는 `::1`로 풀릴 수 있는데 compose는
    IPv4 loopback(`127.0.0.1:8000`)에만 publish한다. 기존 규칙이 `localhost`를 쓰는 것은
    건드리지 않는다.
-   **터널은 API만 노출한다.** frontend는 Workers가 서빙한다. **Postgres(5432)는 ingress에
    절대 넣지 않는다**(`spec/02_ARCHITECTURE.md`).
-   catch-all 뒤에 넣은 규칙은 매칭되지 않는다. cloudflared는 위에서부터 첫 매칭을 쓴다.
-   repo의 `infra/cloudflared/`에는 **자리표시자만 쓴 예시 조각**을 새로 작성해 둔다. 호스트의
    `~/.cloudflared/config.yml`을 복사해 만들지 않는다. 그 파일의 주석에 실제 호스트명이 있다.
    credentials JSON과 `cert.pem`은 읽지도 옮기지도 않는다.
-   login endpoint의 Cloudflare rate limit은 여전히 운영자 선택이다(ADR-006). 이 ADR은 켜져
    있다고 가정하지 않는다.

### 버린 대안

-   **이 앱 전용 새 터널 + 새 systemd unit.** 기존 서비스 중단이 없는 것이 이점이다. 대가로
    credentials 파일, unit, cloudflared 프로세스가 하나씩 더 생긴다. 사용자가 기존 터널
    재시작의 짧은 중단을 수용했다.
-   **cloudflared를 compose 서비스로.** 호스트에 이미 systemd로 돌고 있는 cloudflared가 있다.
    두 번째 실행 방식을 만들고 credentials를 컨테이너에 mount해야 한다.
-   **remotely-managed(token) 터널로 전환.** 현재 터널은 로컬 설정 파일 방식이다. 방식 전환은
    같은 터널의 기존 서비스까지 옮기는 일이다.

---

## 결정 5 --- frontend: wrangler CLI flag 배포 + 대시보드 Custom Domain

``` sh
cd frontend \
  && npm ci \
  && VITE_API_BASE_URL=https://<API_HOST> npm run build \
  && grep -rqF 'https://<API_HOST>' dist \
  && ! grep -rqF 'localhost:8000' dist \
  && npx --yes wrangler@<고정 버전> deploy --name <WORKER_NAME> --assets ./dist \
       --compatibility-date <YYYY-MM-DD>
```

-   **확인 절차가 배포의 일부다.** `frontend/src/env.ts`는 `VITE_API_BASE_URL`이 없으면 조용히
    `http://localhost:8000`을 쓴다. 그 번들은 배포되면 모든 요청이 사용자 기기의 localhost로
    나가고 오류는 "네트워크 실패"로만 보인다. 그래서 두 grep을 같은 `&&` 체인에 둔다. 산출물에
    API origin이 있고 localhost origin이 없을 때만 deploy가 실행된다. origin 리터럴이
    `env.ts` 하나뿐이라는 것은 이미 테스트가 강제하므로(`tests/unit/no-hardcoded-origin.test.ts`)
    이 grep이 오탐하지 않는다. `vite build`는 `dist`를 비우고 다시 쓰므로 옛 산출물이 검사를
    통과할 수 없다.
-   `VITE_API_BASE_URL`은 **빌드 셸의 환경변수로만** 준다. `frontend/.env.production` 같은
    파일을 두지 않는다. 두면 같은 머신의 개발 빌드(`make frontend-build`)에도 운영 URL이
    조용히 들어간다.
-   **Custom Domain `<FRONTEND_HOST>`는 Cloudflare 대시보드에서 한 번 붙인다.** 도메인을 CLI
    인자나 설정 파일에 적으면 결정 6과 부딪힌다.
-   **`*.workers.dev`와 Preview URL은 끈다.** 그 origin은 API와 same-site가 아니고
    `CORS_ALLOW_ORIGINS`에도 없어 **로그인이 구조적으로 불가능한** 사본이다. 보안 문제는
    아니다(정적 자산은 원래 공개이고 cookie가 흐르지 않는다). 사용자가 그 주소로 들어가
    "로그인이 안 된다"를 겪는 혼란을 막는 조치다.
-   wrangler는 `package.json`에 넣지 않고 배포 때 **버전을 고정한 `npx`**로 부른다.
    `make frontend-test`와 e2e의 `npm ci`가 배포 도구(workerd 바이너리 포함)를 매번 받지
    않게 한다.

### 설정 파일을 두지 않는 근거

-   이 frontend는 **hash 라우팅**이다(`frontend/src/main.ts`). SPA fallback
    (`not_found_handling`)이 필요 없고, Worker 스크립트도 없다. 설정 파일에 들어갈 비기본값은
    assets 디렉터리뿐인데 그것은 flag 하나다.
-   도메인은 결정 6 때문에 어차피 설정 파일에 들어갈 수 없다.

### 설정 파일로 옮기는 조건

config 없는 `wrangler deploy`가 배포할 때마다 `workers.dev`를 다시 켜는지는 wrangler 버전에
달려 있고 **이 환경에서 확인하지 않았다**. 첫 배포 뒤 대시보드에서 확인한다. 다시 켜진다면
`frontend/wrangler.jsonc`를 두고 `workers_dev: false`와 `preview_urls: false`만 적는다. 도메인과
`routes`는 적지 않는다.

---

## 결정 6 --- 커밋되는 파일에는 실제 도메인을 쓰지 않는다

`infra/`, `docs/`, `scripts/`, `Makefile`, 예시 설정, 운영 문서, 테스트, 이 ADR까지 커밋되는 모든
파일은 자리표시자를 쓴다.

``` text
<FRONTEND_HOST>   화면용 서브도메인
<API_HOST>        API용 서브도메인
<TUNNEL_NAME>     기존 터널 이름
<TUNNEL_SERVICE>  기존 터널을 돌리는 systemd 서비스 이름
<WORKER_NAME>     Workers 이름
```

실제 값이 놓이는 곳은 전부 저장소 밖이거나 Git 제외다.

``` text
.env                           CORS_ALLOW_ORIGINS=https://<FRONTEND_HOST>   (Git 제외)
~/.cloudflared/config.yml      hostname: <API_HOST>                          (저장소 밖)
frontend 빌드 셸               VITE_API_BASE_URL=https://<API_HOST>          (파일 없음)
Cloudflare 대시보드            Custom Domain, DNS
```

### 근거

-   `spec/04_SECURITY_AND_DATA.md`: "`infra/`에 도메인을 고정하지 않는다."
-   원격 저장소가 GitHub다. login endpoint에는 애플리케이션 rate limit이 없다(ADR-006).
    커밋하면 그 호스트명이 검색 가능한 곳에 영구히 남는다.

### 한계

이 규칙이 막는 것은 **저장소를 통한 발견**뿐이다. `<API_HOST>`는 공개 frontend 번들에 그대로
들어 있으므로(`VITE_*`는 공개값) `<FRONTEND_HOST>`를 여는 사람은 누구나 API 호스트를 안다.
Universal SSL 인증서는 zone과 `*.zone`으로 발급되므로 CT 로그로 개별 서브도메인이 드러나지는
않지만, DNS 열거까지 막아 주지는 않는다. 방어의 중심은 여전히 password 엔트로피다(ADR-006).

### 개정 (2026-09-13) --- README의 사이트 주소 1개만 예외

사용자 결정(2026-09-13, `updates/U-002`)으로 이 결정에 **예외 하나**를 둔다.

``` text
예외        루트 README.md에 방문자가 여는 사이트 주소 1개 (<FRONTEND_HOST>의 실제 값)
그대로      README를 포함한 모든 커밋 파일에 운영 환경의 실제 값을 쓰지 않는다:
            <API_HOST>, <TUNNEL_NAME>, <TUNNEL_SERVICE>, <WORKER_NAME>의 실제 값,
            운영 포트·서버 경로·IP·계정 ID
그대로      README 밖의 커밋 파일(infra/, docs/, scripts/, Makefile, 예시 설정, 운영 문서,
            테스트, spec/, updates/, 이 ADR)은 사이트 주소도 자리표시자로 쓴다
대상 아님   다음은 운영 환경의 실제 값이 아니므로 이 결정의 대상이 아니다
            loopback 기본값(localhost, 127.0.0.1)과 로컬 개발·검증용 포트
            문서 예시 자리표시자(<API_HOST>, example.com 류)
            제3자 참고 URL(화면 전환 참고 사이트 등)
```

-   **이유:** 저장소가 공개되었고, 루트 README는 포트폴리오 방문자가 앱을 바로 써 보게 하는
    문서가 되었다(`updates/U-002`). 사이트 주소는 방문자에게 알리려고 있는 주소다.
-   **이 예외가 바꾸는 것:** 위 `한계`대로 사이트를 여는 사람은 공개 번들에서 API 호스트를 알 수
    있다. README에 사이트 주소가 있으면 저장소를 읽는 사람도 그 경로로 API 호스트에 닿는다. 즉
    "저장소를 통한 발견"을 막는 효과가 API 호스트에 대해서도 약해진다. 방어의 중심이 password
    엔트로피(ADR-006)라는 판단은 그대로이며, 이 개정으로 login endpoint의 방어를 바꾸지 않는다.
-   예외는 **README 한 파일, 주소 한 개**다. 늘리려면 이 절을 다시 개정한다. 실제 주소 값은 이
    ADR에 적지 않는다.

---

## 결정 7 --- seed 초기화: 거부는 유지하고, 수동 절차를 백업 체인으로 묶는다

`scripts/db_reset.py`의 production 거부를 **그대로 둔다.** 운영 초기화를 위한 새 코드 경로를
만들지 않는다. 운영 문서에 다음 절차를 둔다. 대상 확인 → 정지 → 백업 → DROP은 **하나의 `&&` 체인**이라
어느 단계가 실패해도 DROP이 실행되지 않는다.

``` sh
# 0. 확장 seed가 적재되는지 로컬 pgserver에서 먼저 확인한다 (운영 DB를 지운 뒤에 발견하지 않게)
#    (운영 셸이 아닌 별도 터미널, 개발 DB와 다른 이름)
#    export DATABASE_URL="$(make db-up-local ARGS='--database nc_seedcheck')" && make db-reset ARGS=--yes && make seed

# 운영 셸(새로 연 터미널): APP_ENV=production, 호스트 DSN, NC_CONFIG_PATH export 상태
# compose는 셸 환경을 비우고 부른다 (아래 첫 bullet)
C() { env -i HOME="$HOME" PATH="$PATH" docker compose --env-file .env -f infra/docker-compose.yml "$@"; }
# 되돌릴 수 없는 체인의 맨 앞에 두는 대상 확인 (아래 둘째 bullet)
prod_db() { [ "$APP_ENV" = production ] && [ "$DATABASE_URL" = "postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>" ] || { echo "STOP: DATABASE_URL이 운영 DSN이 아니다. 아무것도 실행하지 않았다." >&2; return 1; }; }

prod_db \
  && C stop backend worker \
  && make db-backup ARGS="--pg-bin <PG_BIN>" \
  && C exec -T postgres sh -c \
       'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  && echo reset

make db-migrate ARGS="--pg-bin <PG_BIN>"   # 빈 DB라 pending이 있으므로 빈 DB 백업이 하나 더 생긴다
make create-user ARGS="--login-id <id>"
make seed
make prompts ARGS="--provider openai --model gpt-4o-mini"
C up -d --no-deps backend worker
```

-   **compose를 `C="docker compose ..."` 변수로 부르면 실패한다(실검증에서 재현).** compose는
    파일을 채울 때 **셸 환경변수를 `--env-file`보다 우선**한다. 운영 셸에는 호스트 DSN
    (`127.0.0.1:5432`)이 export 되어 있으므로 `$C up -d backend worker`는 컨테이너에 그 DSN을 넘기고,
    컨테이너 안의 `127.0.0.1`은 자기 자신이라 backend의 health database가 `down`이 된다. 조용히
    틀리는 방향이다(명령은 성공한다). `env -i`로 셸 환경을 비우면 `.env`의 값만 쓰인다. 운영 문서
    (`infra/DEPLOY.md` 2.3)는 모든 compose 명령을 이 함수로 부르고, `C config | grep -c '@postgres:5432/'`로
    컨테이너 DSN의 host를 확인한다. Makefile의 `COMPOSE`(`make db-up` / `make db-down`)도 같은 성질이라
    운영에서 쓰지 않는다.
-   **체인 맨 앞의 `prod_db`가 백업 대상을 DROP 전에 확인한다(보안 게이트 지적으로 추가).** `&&` 체인은
    "**어떤** DB의 백업이 성공했다"까지만 보장한다. 백업은 셸의 `DATABASE_URL`을 따르고 DROP은 compose의
    postgres를 겨냥하므로 둘이 같은 DB라는 보장이 체인에 없었다. 개발 DSN이 남은 터미널(예: 0단계의
    `export`를 한 터미널 재사용)에서 실행하면 백업이 **개발 DB를** 백업하고 성공한 뒤 운영 DB가 지워진다.
    운영 DB의 초기화 직전 백업은 없고, 그 개발 DB 백업이 rotation으로 가장 오래된 운영 백업 하나를
    밀어낸다. 백업 명령이 출력하는 대상 줄을 읽는 것으로는 막지 못한다 --- 읽을 때는 DROP이 이미 실행된
    뒤다. `prod_db`는 셸의 `APP_ENV`와 DSN이 운영 셸의 값과 글자 그대로 같지 않으면 실패해 체인 전체를
    멈춘다(함수가 없는 터미널에서도 `command not found`로 멈춘다). 운영 문서의 실제 복원 절차
    (`infra/DEPLOY.md` 10.2)도 같은 형태이며, 거기서는 복원할 파일의 존재·목차 확인도 DROP 앞 체인 안에
    두고 `pg_restore --single-transaction`으로 복원 실패 시 반쯤 복원된 DB가 남지 않게 한다. 안전 백업은 시도마다
    새 디렉터리(`data/backups/pre-restore/<UTC>/`, 체인 안에서 "아직 없음"을 확인)에 쓰고, 되돌릴 때는 "가장 최근
    파일"이 아니라 그 시도가 출력한 `backup written:` 경로를 쓴다. 복원 실패 뒤 체인을 다시 실행하면 이미 DROP된
    빈 DB가 새 안전 백업이 되기 때문이다.
-   **DROP/CREATE는 `docker compose exec postgres` 안에서 한다.** compose 서비스만 겨냥할 수
    있으므로 결정 1의 조용한 실패(개발 DB DSN)가 이 단계에서는 구조적으로 불가능하다. DB 이름과
    사용자도 컨테이너 환경에서 오므로 손으로 치지 않는다. 작은따옴표는 변수가 호스트 셸이 아니라
    컨테이너 셸에서 풀리게 하려는 것이다.
-   `--force`는 잊힌 연결(열어 둔 psql 등)을 끊는다. backend/worker는 이미 멈춰 있다.
-   초기화 뒤에는 `auth_sessions`가 비므로 브라우저는 401을 받고 다시 로그인한다. 기술 검증
    기간에 생성된 문장과 학습 기록은 사라진다. 의도한 결과다.
-   초기화 직전 백업은 보관 개수 7 안에서 이후 백업 6개가 더 쌓일 때까지 남는다. 검증 기간의
    데이터는 버리기로 한 데이터이므로 따로 보존하지 않는다.

### 버린 대안

-   **명시적 확인이 있는 production 초기화 경로**(예: `db_reset.py --allow-production <db>`,
    내부에서 백업 강제). 백업 선행을 코드로 강제한다는 이점이 있다. 버린 이유:
    -   필요한 것은 **한 번**이고, 경로는 **영구히** 남는다. 본 사용이 시작된 뒤 그 경로가 실수로
        실행되면 몇 달치 학습 기록이 사라진다. 되돌릴 수 없는 작업일수록 편한 경로가 없는 쪽이
        안전하다. 마찰이 곧 방어다.
    -   `Secure` 끄는 스위치(ADR-004)와 password 하한 스위치(ADR-006)를 만들지 않은 것과 같은
        판단이다. 안전장치를 낮추는 플래그를 새로 만들지 않는다.
    -   백업은 결정 2의 백업 명령이 이미 하고, 그 명령은 검증까지 한다. 강제는 `&&` 체인으로
        충분하다.
-   **셸에서 `APP_ENV=local make db-reset ARGS=--yes`를 운영 DSN으로 실행.** 코드는 한 줄도
    안 늘지만 production 거부를 **환경변수 위조로 우회하는 절차**를 문서화하게 된다. 그 절차가
    한 번 문서에 실리면 거부의 의미가 없어진다. 대상도 DSN이라 결정 1의 조용한 실패에 노출된다.
-   **`data/postgres`를 지우고 클러스터 재초기화.** 파일이 컨테이너 uid 소유라 root가 필요하고,
    DB 하나가 아니라 클러스터 전체(role 포함)를 지운다. DB DROP이 더 좁다.

### 한계

백업 선행 강제와 대상 확인은 **절차 수준**이다. 체인을 끊어 DROP 줄만 따로 실행하는 것은 막지 못한다.
`prod_db`가 비교하는 DSN은 운영자가 셸에 적은 문자열이다. 운영 셸의 `export` 줄 자체를 틀리게 적으면
(둘이 같이 틀리면) 확인은 통과한다. 그 경우에도 결정 1의 시끄러운 실패(호스트 `postgres` 미해석 등)나
백업 출력의 대상 줄로 드러난다. 스크립트가 백업 대상과 compose DB의 동일성(`system_identifier` 등)을
직접 비교하는 코드는 두지 않았다(결정 2의 (c)에서 적은 비용).

---

## 결정 8 --- 재부팅 후 기동은 docker에 맡기고, 정기 백업은 crontab 한 줄

-   compose의 세 서비스는 이미 `restart: unless-stopped`다. `docker`와 `containerd`는
    `enabled`다(확인됨). 재부팅 뒤 docker가 컨테이너를 다시 띄운다. cloudflared 서비스도 이미
    `enabled`다. **이 앱을 위한 systemd unit을 추가하지 않는다.**
-   재부팅 후 자동 기동은 명세 요구가 아니다(`13_ACCEPTANCE_CRITERIA.md`의 `restart 후 state
    유지`는 재부팅을 제외한다). 따라서 이 결정은 기준을 만족시키기 위한 것이 아니라 편의다.
-   `unless-stopped`의 귀결: `docker compose stop`으로 멈춘 상태(결정 7, migration 중)에서
    재부팅하면 **멈춘 채로 남는다.** 멈춤 의도를 보존하는 동작이므로 받아들인다.
-   정기 백업은 `spec/04_SECURITY_AND_DATA.md`가 "정기"를 요구하므로 호스트 사용자 crontab에 한
    줄을 둔다.

``` text
17 4 * * * cd <REPO> && APP_ENV=production DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB> <UV 절대경로> run --no-sync python scripts/<백업 명령> --pg-bin <PG_BIN> >> <REPO>/data/backup.log 2>&1
```

-   password는 이 줄에 없다(`~/.pgpass`). docker 그룹도 필요 없다(호스트 바이너리).
-   cron의 PATH는 최소라서 `uv`는 절대경로로 쓴다. crontab에서 `%`는 줄바꿈이므로 이 줄에
    `date +%...`를 넣지 않는다(파일명 시각은 스크립트가 만든다).
-   `--no-sync`: 새벽 작업이 `.venv`를 바꾸지 않게 한다. sync가 돌면 백업 도중 pgserver 번들이
    교체될 수 있다.
-   서비스가 살아 있는 채로 dump한다. pg_dump는 한 트랜잭션 스냅샷이므로 파일은 일관적이다.
    **API·worker를 멈추라는 요구는 restore 검증에만 있다**(원본과 비교하기 때문이다).
-   로그는 `data/backup.log`(`*.log`로 Git 제외)이고 `data/backups/` 안에 두지 않는다. rotation이
    세는 디렉터리에 다른 파일을 섞지 않기 위해서다.
-   시각 04:17(호스트 시간대)은 학습하지 않는 시간대이면서 정각을 피한 값이다.

### 버린 대안

-   **systemd service + timer.** 실패 상태가 `systemctl`에 남는 이점이 있지만 unit 두 개와 sudo
    설치 절차가 생긴다. 한 줄로 되는 일에 쓰지 않는다.
-   **compose 안의 백업 컨테이너(cron 이미지).** 컨테이너가 하나 늘고, 백업 파일이 컨테이너 uid로
    생기며, 결정 2의 한 형태가 깨진다.

---

## 결정 9 --- 에이전트의 compose 검증 방식

docker가 설치되었으므로 에이전트가 **이 머신에서 compose 구성을 실제로 띄워 검증할 수 있다.**
이 머신은 사용자의 실제 운영 호스트이므로 검증은 운영 배포와 어떤 자원도 공유하지 않는다.

### docker 호출

-   에이전트 세션은 `docker` 그룹 추가 이전에 시작되어 그룹이 적용되지 않았다. **에이전트는
    `sg docker -c "..."` 형태로 docker와 compose를 부른다.** 사용자의 셸은 재로그인 뒤 그냥
    `docker`로 쓴다.
-   `sg`는 문자열을 `sh -c`로 넘기므로 중첩 따옴표가 깨지기 쉽다. 여러 명령은 scratchpad에 셸
    스크립트로 적고 `sg docker -c "bash <scratchpad>/verify.sh"`로 실행한다.

### 격리 규칙

``` text
project 이름    -p nc-verify   (운영은 기본 project 이름 "infra". -p 없이 실행하지 않는다)
env             --env-file <scratchpad>/verify.env   (repo의 .env를 만들지도 읽지도 않는다)
override        -f infra/docker-compose.yml -f <scratchpad>/verify.override.yml
Makefile        make db-up / db-down 을 쓰지 않는다 (COMPOSE에 --env-file .env가 박혀 있다)
정책 파일       NC_CONFIG_PATH=<scratchpad>/config.yaml (절대경로, default.yaml 사본)
                /etc/nihongo-context/ 는 건드리지 않는다
백업 디렉터리   scratchpad (운영 data/backups/ 의 rotation을 건드리지 않는다)
손대지 않는 것  .env, /etc/nihongo-context/, ~/.cloudflared/, crontab, data/postgres, data/backups
```

**postgres data와 port는 override로 반드시 바꾼다.**

``` yaml
services:
  postgres:
    volumes: !override
      - nc_verify_pgdata:/var/lib/postgresql/data
    ports: !override
      - "127.0.0.1:55432:5432"
  backend:
    ports: !override
      - "127.0.0.1:58000:8000"
volumes:
  nc_verify_pgdata:
```

-   **`data/postgres`를 쓰면 안 되는 이유**: base compose는 `../data/postgres`를 **bind mount**한다.
    `down -v`는 named/anonymous volume만 지우고 bind mount 내용은 지우지 않는다. 검증이 그 디렉터리에
    검증용 `POSTGRES_USER`/`POSTGRES_PASSWORD`로 클러스터를 만들면 운영 첫 기동은 클러스터가 이미
    있다고 보고 초기화를 건너뛴다. 운영 `.env`의 password는 조용히 무시되고, 파일은 컨테이너 uid
    소유라 지우는 데 root가 필요하다. named volume으로 바꾸면 `down -v`가 지운다.
-   **port를 바꾸는 이유**: 운영이 아직 안 떴어도 검증이 5432/8000을 잡은 채 끝나지 않으면 운영
    기동이 막힌다. 반대로 운영이 떠 있으면 검증이 실패한다. 검증은 항상 운영과 다른 loopback port를
    쓴다. publish가 loopback인지는 `backend/tests/test_infra_compose.py`가 이미 지킨다.
-   `!override`는 Compose 2.24.4 이상에서 동작한다(설치본 v5.5.1). **`up` 전에
    `docker compose ... config`로 병합 결과를 출력해** postgres volume에 `data/postgres`가 없고 port가
    55432/58000인지 확인한다. 확인되지 않으면 `up`하지 않는다.
-   port 확인: `ss -ltn '( sport = :55432 or sport = :58000 )'`의 출력이 헤더뿐이어야 한다. 사용
    중이면 **다른 프로세스를 멈추지 않고** override의 port 번호를 바꾼다. pgserver는 TCP를 열지 않으므로
    (`-h ""`) 충돌 대상이 아니다.

### 검증 항목

``` text
build          두 이미지가 빌드된다 (네트워크: postgres:16, python:3.12-slim,
               ghcr.io/astral-sh/uv:0.12.13, PyPI)
postgres       초기화 후 호스트 DSN(127.0.0.1:55432)으로 연결된다
migration/CLI  호스트 uv run으로 migration → create-user → seed → prompts가 검증 DB에 적용된다
               (검증 DB의 password는 일회용이므로 검증 DSN에 넣어도 된다)
백업           결정 2의 형태(--pg-bin pgserver 번들)로 검증 DB를 scratchpad에 백업·검증한다
API            http://127.0.0.1:58000/api/health 가 응답하고 database가 ok,
               APP_ENV=production 에서 /docs 가 닫혀 있다
worker         LLM_PROVIDER를 비워 둔다. worker가 부팅을 거부하고(non-zero, 로그에 거부 사유)
               restart 정책으로 재시작을 반복하는 것이 정상이다 (fail-closed 확인).
               /api/health의 worker는 unknown이다
정책 mount     NC_CONFIG_PATH를 없는 절대경로로 두면 컨테이너 생성이 실패하고
               호스트에 그 경로의 디렉터리가 생기지 않는다 (create_host_path: false 확인).
               NC_CONFIG_PATH를 비우면 compose가 아무것도 띄우지 않는다 (:? 확인)
data 루트      아래 "data/postgres의 .gitkeep" 항목
```

실제 OpenAI 키는 쓰지 않는다. `LLM_API_KEY`도 비운다.

### data/postgres의 `.gitkeep` --- 확인된 결함과 해결

**결함 (재현됨).** 운영 `data/postgres/`에는 Git이 추적하는 `.gitkeep`이 있다. `.gitkeep` 하나만 든
scratchpad 디렉터리를 bind로 주고 `PGDATA` 없는 base compose 그대로 띄우자 postgres가 무한 재시작했다.

``` text
initdb: error: directory "/var/lib/postgresql/data" exists but is not empty
        ... dot-prefixed/invisible file
```

실패가 postgres에서 끝나지 않는다. entrypoint가 bind 루트와 `.gitkeep`의 소유자·권한을 `999`/`700`으로
바꿔 놓아, 호스트 사용자는 `ls data/postgres`를 못 하고 `git status`가 그 디렉터리에서 Permission
denied를 낸다. 되돌리려면 root가 필요하다.

**해결 (채택, 검증됨).** postgres 서비스에 `PGDATA=/var/lib/postgresql/data/pgdata`를 둔다. initdb는 빈
하위 디렉터리 `pgdata/`에만 쓰고 bind 루트는 건드리지 않는다. 수정한 base compose를 `.gitkeep`이 있는
bind로 띄워 `init process complete`, 재시작 0회, bind 루트 `user:user 775` 유지, `.gitkeep` 유지, 재기동 시
`Skipping initialization`을 확인했다. `infra/docker-compose.yml`에 반영되었고
`backend/tests/test_infra_compose.py::test_postgres_cluster_lives_below_the_bind_root`가 지킨다. `.gitignore`의
`data/postgres/*` 규칙과 기존 volume 경로는 그대로다.

`.gitkeep`을 지우는 대안은 버렸다. 디렉터리의 존재를 Git이 보장하지 않게 되고, 누군가 다시 넣으면 같은
결함이 조용히 돌아온다.

### 실검증 결과

위 검증 항목을 포함한 **19개 항목이 모두 통과했다.** 이 ADR의 판단에 영향을 준 결과는 다음이다.

``` text
.gitkeep        결함 재현 → PGDATA 하위 디렉터리로 해결 (위 절)
셸 환경 누수    호스트 DSN을 export한 셸에서 compose를 부르면 backend가 127.0.0.1 DSN을 받아
                health database가 down (결정 7의 wrapper로 수정)
.env의 $        compose interpolation이 $를 변수로 읽어 password에서 조용히 지운다. 경고만 나고
                기동은 계속되어 DB가 모르는 password로 초기화된다 → 운영 문서가 영숫자 password를 요구한다
정책 mount      없는 경로: invalid mount config for type "bind": bind source path does not exist, exit 1.
                호스트에 디렉터리가 생기지 않는다. 단 실패 전에 network(검증 구성에서는 volume도)는 만들어진다
                비운 값: compose가 아무것도 띄우지 않는다
정책 파일 변경  sed -i 뒤 재시작 전까지 컨테이너는 옛 내용(옛 inode)을 본다. compose restart로 새 내용이
                보인다. force-recreate도 같다 → 결정 3의 "worker만 재시작"으로 충분하다
정책 파일 권한  컨테이너는 uid 10001로 돌며 0644 파일을 읽는다 (결정 3의 0644 근거)
worker 부팅거부 LLM_PROVIDER 비움: ps에 Restarting, 로그 ProviderConfigError: unknown LLM provider '',
                알림 없이 backoff 재시작만 반복한다
틀린 키         가짜 키 worker는 재시작 0회로 뜨고 health worker ok, 기동 로그 없음. 키 오류는 첫
                generation job 실패로만 드러난다 → 운영 문서가 기동 전 키 확인 단계를 둔다
pg_dump 버전    호스트 16.2 → 서버 16.15 백업과 restore 검증 여섯 항목 통과
                (21 tables, 19 sequences, 94 constraints, 50 indexes, 음성 대조군 auth_sessions)
postgres 재시작 backend 재시작 없이 health ok, /me 200 (pool_pre_ping). 이전 cookie 유효, history 동일
Origin          Origin 없는 로그인 403, 틀린 Origin 403
```

### 정리

``` sh
docker compose -p nc-verify ... down -v --rmi local --remove-orphans
docker ps -a     --filter label=com.docker.compose.project=nc-verify   # 비어 있어야 한다
docker volume ls --filter label=com.docker.compose.project=nc-verify   # 비어 있어야 한다
```

검증이 중간에 실패해도 정리는 실행한다(스크립트의 `trap`).

---

## 뒤따르는 구현 작업에 넘기는 값

``` text
정책 파일          /etc/nihongo-context/config.yaml  (호스트 = 컨테이너, ro, create_host_path: false)
compose            backend·worker 양쪽에 같은 long-syntax bind, source/target = ${NC_CONFIG_PATH:?}
                   environment의 NC_CONFIG_PATH: ${NC_CONFIG_PATH} 는 그대로 (기존 테스트)
                   postgres environment PGDATA=/var/lib/postgresql/data/pgdata (결정 9, 반영됨)
운영 compose 호출  env -i HOME PATH docker compose --env-file .env -f infra/docker-compose.yml (결정 7)
호스트 DSN         postgresql+psycopg://<POSTGRES_USER>@127.0.0.1:5432/<POSTGRES_DB>, password는 ~/.pgpass
운영 셸 export     APP_ENV=production, DATABASE_URL=<호스트 DSN>, NC_CONFIG_PATH=/etc/nihongo-context/config.yaml
백업 명령 인터페이스 DATABASE_URL(env), --pg-bin DIR(필수), 보관 개수 인자(기본 7),
                   백업 디렉터리 기본 data/backups/ (테스트·검증은 다른 디렉터리를 줄 수 있어야 한다)
                   작업 전 가린 DSN 출력, 클라이언트/서버 버전 출력, 파일 0600으로 생성
운영 PG_BIN        <REPO>/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin
cloudflared        ~/.cloudflared/config.yml, <TUNNEL_SERVICE>, service http://127.0.0.1:8000
infra 예시         infra/cloudflared/ 에 자리표시자만 쓴 ingress 조각 (호스트 파일 복사 금지)
frontend           VITE_API_BASE_URL은 빌드 셸 env, 산출물 grep 두 개 통과 후 npx wrangler@<고정> deploy
cron               사용자 crontab 한 줄, 로그 data/backup.log
에이전트 docker    sg docker -c "...", -p nc-verify, scratchpad env/override, 55432/58000
.env.example       NC_CONFIG_PATH 설명을 compose 필수값 기준으로 고친다
```

스크립트 파일 이름과 Makefile 타깃 이름은 구현이 정한다.

## 한계

-   **compose 구성은 실검증을 거쳤지만 운영 기동 그 자체는 아니다.** 결정 9의 검증은 19개 항목을
    통과했고, 그 과정에서 `.gitkeep` 결함(→ `PGDATA`)과 셸 환경 누수(→ 결정 7의 wrapper)를 재현해
    고쳤다(`실검증 결과`). 검증 형태가 운영과 다른 점은 다음이며, 이 부분은 운영 첫 기동에서 처음 실행된다.

    ``` text
    postgres data   검증은 named volume (.gitkeep 재현과 PGDATA 확인만 scratchpad bind). 운영은 data/postgres bind
    worker network  검증은 외부 통신이 없는 internal network. 운영은 OpenAI에 실제로 나간다
    password 파일   검증은 PGPASSFILE로 scratchpad 파일을 가리켰다. 운영은 ~/.pgpass
    정책 파일       검증은 scratchpad의 사본. 운영은 root 소유 /etc/nihongo-context/config.yaml
    port            검증은 55432/58000. 운영은 5432/8000
    ```

    실제 키·실제 터널·실제 도메인을 쓰는 첫 운영 기동은 사용자가 `infra/DEPLOY.md`로 한다.
-   **백업이 DB와 같은 디스크에 있다.** 그 디스크를 잃으면 DB와 7개 백업을 함께 잃는다.
    명세의 "가능하면 다른 물리 디스크/위치"는 사용자 결정으로 지금 하지 않는다. 결정 2 덕분에 백업
    파일은 호스트 사용자 소유의 일반 파일이라, 나중에 다른 위치로 복사하는 일은 이 구조를 바꾸지 않는다.
-   **기존 터널을 재시작하면 같은 터널의 다른 서비스가 잠깐 끊긴다.** 설정 오류가 있으면 그 서비스들도
    함께 안 뜬다. 그래서 재시작 전에 `ingress validate`와 `ingress rule`을 거치고 `.bak`을 남긴다.
-   **gpt-4o-mini의 structured output 호환성은 검증되지 않았다.** 기술 검증 기간(한도 30/60000)의 첫
    generation job이 드러낸다. 맞지 않으면 job은 retry 뒤 `failed`로 끝나고 학습 세션은 Ready Pool로
    계속된다(`09_BACKGROUND_JOBS.md`).
-   pgserver 번들은 16.2에 고정되어 이후 minor의 pg_dump 수정을 받지 못한다(결정 2의 전환 조건).
-   `make db-reset`의 production 거부는 **호출한 셸의 `APP_ENV`**에 기댄다. 운영 DSN과
    `APP_ENV=production`을 한 줄로 export하는 운영 규칙이 그 간극을 메운다.
-   결정 7의 백업 선행 강제는 절차(`&&` 체인)이지 코드가 아니다.
-   cron 백업의 실패는 `data/backup.log`에만 남는다.
-   config 없는 `wrangler deploy`가 `workers.dev`를 다시 켜는지 확인하지 않았다(결정 5의 전환 조건).
-   도메인 자리표시자는 저장소를 통한 노출만 막는다. API 호스트는 공개 번들에 있다(결정 6).
