# ADR-017 --- worker heartbeat를 어디에 저장하는가

Status: Accepted

Decision: **전용 테이블 `worker_heartbeats(worker_name PK,
last_heartbeat_at)`를 만든다.** worker는 loop를 돌 때마다(최소
`jobs.heartbeat_interval_seconds` 간격) **처리할 job이 없어도** 이 행을
upsert하고, 그 write는 job 트랜잭션과 분리해 즉시 commit한다.
`GET /api/health`는 `last_heartbeat_at`의 최대값 하나를 읽어
`unknown | ok | stale`을 판정한다. 임계값은
`jobs.heartbeat_stale_seconds`다.

canonical 정의: `spec/mvp-01-core/04_DB_SPEC.md`의 `worker_heartbeats`,
`spec/mvp-01-core/09_BACKGROUND_JOBS.md`의 `Worker Heartbeat`,
응답 표현은 `spec/mvp-01-core/05_API_SPEC.md`.

## 문제

`05_API_SPEC.md`의 `/api/health`는 `components.worker.status`를
`unknown | ok | stale`로 정의해 두고 저장 위치는 "Wave 3 시점에
확정"이라고 두 번 미뤘다. `09_BACKGROUND_JOBS.md`에도 `미결` 절이 있었고,
구현은 `unknown` 고정이다. Wave 3에서 worker가 실제로 도는 이상 이 값이
계속 `unknown`이면 health check가 worker에 대해 아무 말도 하지 않는다.
개인 서버에서 worker만 죽는 사고는 조용히 일어난다 --- 학습 세션은 Ready
Pool로 계속 돌아가므로 사용자 화면에는 아무 증상이 없고, pool이 마른 뒤에야
드러난다.

## 버린 대안

**(a) `generation_jobs`의 최근 활동으로 추론한다.**
`max(started_at)` 또는 `max(finished_at)`이 임계값 안이면 `ok`로 본다.
새 테이블이 없다는 것이 유일한 장점인데, 이 앱에서는 **하루 종일 job이
0건인 것이 정상**이다(seed와 기존 pool만으로 세션이 굴러가는 날). 그때
"일이 없다"와 "worker가 죽었다"가 같은 관측이 된다. 임계값을 짧게 잡으면
멀쩡한 worker가 매일 `stale`이고, 길게 잡으면 죽은 worker를 며칠 못
잡는다. heartbeat가 가장 필요한 조용한 날에 판정이 항상 틀리므로 이
신호는 쓸모가 없다.

**(b) `generation_jobs`에 heartbeat 전용 row를 하나 넣는다.**
`job_type`에 값을 추가해야 하는데 그 목록은 `08_LLM_SPEC.md`의 provider
task와 1:1로 유지하기로 이미 결정했다(`04_DB_SPEC.md`의 `job_type
허용값`). 생존 신호는 provider task가 아니다. 축을 섞는 대가가 전용
테이블 하나보다 크다.

**(c) 파일이나 프로세스 메모리에 둔다.** API와 worker는 별도
프로세스이며 컨테이너도 다르다(`Dockerfile.backend`,
`Dockerfile.worker`). 공유 상태는 PostgreSQL이라는 원칙(LLM Engineering
Principles 1)을 여기서만 깨야 하고, 컨테이너 파일시스템을 공유하는
배포 가정을 새로 만들게 된다.

**(d) 아무것도 하지 않고 `unknown`을 유지한다.** `/api/health`의 계약에
이미 `ok | stale`이 있으므로 명세가 스스로와 어긋난 채로 남는다. 미루기를
세 번째 반복하는 선택이기도 하다.

## 비용과 그 정당화

새 테이블 하나 + 컬럼 둘 + Wave 3 migration 하나. `worker_heartbeats`는
파생값이 아니라 **다른 어디에도 존재하지 않는 사실**(프로세스가 살아
있음)을 담으므로, "파생 가능한 컬럼만 가진 테이블을 만들지 않는다"는
기존 판단 기준(`mastery_probes`를 거부한 기준)에 걸리지 않는다.

`worker_name`을 PK로 두는 것은 MVP에서 과잉으로 보일 수 있다. 행이 하나뿐
이기 때문이다. 그래도 두는 이유는 upsert에 대상 키가 필요하고, worker가
둘이 되는 날 migration 없이 행만 늘면 되기 때문이다. 대안인 "id = 1 고정
단일 행"은 같은 비용에 확장 여지만 없앤다.

## 수용된 한계

-   heartbeat는 "프로세스가 loop를 돌고 있다"만 말한다. worker가 살아
    있지만 특정 job에서 영원히 막혀 있는 상태는 이 신호로 잡히지 않는다.
    그것을 잡는 것은 `claim_lease_seconds` 기반의 stale `running` 회수다
    (`09_BACKGROUND_JOBS.md`).
-   DB에 접속할 수 없으면 worker 상태도 `unknown`이다. worker 상태만을
    위해 별도 연결을 만들지 않는다.
