# ADR-002 --- Local Dev Database

Status: Accepted

Decision: 로컬 개발/테스트 DB는 PyPI `pgserver` 0.1.4(번들 PostgreSQL
16.2, unix socket, userspace 기동), 배포는 `infra/docker-compose.yml`의
`postgres:16`. 둘 다 PostgreSQL 16이므로 ADR-001의 스택 결정은 유지된다.

이 개발 머신에는 docker도, passwordless sudo도, 시스템 postgres 바이너리도
없다. `pgserver`는 root 없이 기동되며 `select version()`으로
"PostgreSQL 16.2 on x86_64-pc-linux-gnu"를 확인했다.

## 원칙

-   **애플리케이션 코드는 두 경로를 분기하지 않는다.** 차이는 연결
    문자열(DSN) 하나뿐이다. `pgserver` import는 테스트 fixture와 로컬
    개발 스크립트에만 존재하고 `backend/app/` 아래에는 들어가지 않는다.
-   테스트 fixture가 `pgserver`를 띄우고 DSN을 설정에 주입한다. 운영은
    환경변수로 docker compose의 DSN을 준다.
-   pgserver data 디렉터리는 `data/pgdata/`이며 Git에서 제외한다
    (`spec/04_SECURITY_AND_DATA.md`, `.gitignore`에 이미 존재).
-   `make db-up` / `make db-reset`은 두 백엔드 중 어느 쪽이든 같은 DSN
    계약으로 동작해야 한다.

## 재현성

DB 엔진 선택은 테스트 결정론에 영향을 주지 않는다. 비결정성의 실제
원인은 애플리케이션 쪽이다. FSRS `enable_fuzzing`은 ADR-003에서 끄고,
시각 의존 로직은 fixture에서 주입된 시각을 쓴다.
