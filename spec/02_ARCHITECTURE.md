# Architecture

``` text
iPhone / Browser PWA
  ├─ Static → Cloudflare Workers Static Assets
  └─ API → Cloudflare Tunnel → Research Server
                               ├─ FastAPI
                               ├─ Worker
                               └─ PostgreSQL
                                     ↕
                                  OpenAI API
```

## 결정

-   Frontend: installable PWA, MVP offline 없음
-   Backend: Python + FastAPI
-   DB: PostgreSQL
-   ORM/Migration: SQLAlchemy + Alembic
-   Jobs: Postgres-backed worker, MVP Redis/Celery 없음
-   PostgreSQL은 인터넷 직접 노출 금지
-   Public Demo는 **static frontend fixture**이며 backend API/DB/provider를
    사용하지 않는다(`04_SECURITY_AND_DATA.md`)
-   모든 외부 LLM provider 호출은 **background worker에서만** 발생한다.
    FastAPI request handler는 provider를 synchronous 호출하지 않는다
    (`mvp-01-core/08_LLM_SPEC.md`)
-   provider **구현 선택**은 환경변수 `LLM_PROVIDER`(MVP 허용값 `openai`
    하나, 기본값 없음)이고 **모델명**은 `prompt_versions` 행에서 온다. 모델명을 코드나 config
    YAML에 고정하지 않는다(`mvp-01-core/08_LLM_SPEC.md`의
    `Provider 선택과 model 출처`, `04_SECURITY_AND_DATA.md`, ADR-016)
-   **MVP-02:** 선택 홈과 가나 학습도 Public Demo와 같이 backend API를 쓰지 않는 **공개 화면**이다
    (`04_SECURITY_AND_DATA.md`의 `공개 화면 셋으로 확장 (MVP-02 확정)`, ADR-022)
-   **MVP-02: 형태소 분석기(SudachiPy + SudachiDict-core)는 worker 이미지와 호스트 CLI(`uv run`)에만
    있다.** API 이미지와 API 요청 경로에는 없다. 의존성은 dependency group `furigana`로 두고,
    API 이미지는 기본 group 없이, worker 이미지는 `furigana` group을 더해 sync한다. 호스트는 기본 group
    전부(dev + furigana)다. 두 Dockerfile의 sync 명령은 함께 바꾸고 테스트로 고정한다. API는 저장된 ruby를
    읽기만 한다(`mvp-01-core/05_API_SPEC.md`의 `render_segments[].ruby`, ADR-021)

## Future-safe providers

`ContentProvider = Generated[MVP] | YouTube[Future] | ManualText[Future]`

Demo는 backend content provider가 아니라 frontend static fixture이므로
이 추상화에 포함하지 않는다. YouTube/ManualText는 Future 방향 표시이며
MVP에서 스텁을 선제 구현하지 않는다.

구현 시 repo는 `frontend/ backend/ infra/ scripts/ data/`로 확장한다.

``` text
frontend/
backend/
  app/{api,models,schemas,services,learning,srs,llm,jobs}/ main.py
  migrations/
  tests/
infra/
  docker-compose.yml
  Dockerfile.backend
  Dockerfile.worker
  cloudflared/
scripts/
data/
  postgres/
  backups/
```

`data/postgres`, `data/backups`, `.env`는 Git에 포함하지 않는다.

### MVP-02에서 더한 모듈 위치

``` text
backend/app/render.py         L0 pure (기존). ruby 검증과 segment 분할(RubySpan, RubyPart)을 더한다.
                              분석기를 모른다
backend/app/furigana.py       L1 (신규). 분석기 어댑터, 한자 run 정렬, 교정 계층, ruby_json 조립,
                              explanation.reading 불일치 판정. render와 sudachipy만 import한다
                              import 가능한 곳: services/seed_loader.py, jobs/persistence.py, scripts/
scripts/backfill_ruby.py      기존 문장 ruby backfill (mvp-01-core/04_DB_SPEC.md)
scripts/build_demo_fixture.py seed/ -> demo fixture 생성 (mvp-01-core/03_UI_UX_SPEC.md의 Demo)
scripts/run_worker.py         (기존) 부팅에서 분석기를 적재한다

frontend/src/main.ts          부팅. 공개 라우터 시작. 로그인 영역 동적 import가 여기 한 곳에만 있다
frontend/src/routes.ts        공개 route 표, navigate, hashchange를 듣는 유일한 곳
frontend/src/private.ts       로그인 영역 진입(fetchMe -> 학습 | 401 -> 로그인). API 모듈은 여기서부터만 닿는다
frontend/src/home/            선택 홈
frontend/src/demo/            demo 화면, 생성된 fixture, demo 전용 상수
frontend/src/kana/            가나 데이터·퀴즈·진도·화면
frontend/src/local-store.ts   localStorage 단일 모듈
frontend/src/ui/screen.ts     화면 교체
frontend/src/ui/sheet.ts      바텀시트
frontend/src/ui/topbar.ts     상단바 레이아웃
frontend/src/ui/furigana.ts   후리가나 설정과 토글
```

-   backend 계층과 import guard(G14)는 ADR-015의 계층표와 ADR-021이 canonical이다.
-   frontend 격리 경계와 검사는 `04_SECURITY_AND_DATA.md`의 `공개 화면 셋으로 확장 (MVP-02 확정)`과
    ADR-022가 canonical이다. 기존 `ui/login.ts`, `ui/study.ts`, `ui/history.ts`, `ui/logout.ts`는 자리를 옮기지
    않고 `private.ts`에서만 닿는다.
