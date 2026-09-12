# ADR-015 --- Wave 3 LLM/worker 모듈 경계

Status: Accepted

ADR-007을 Wave 3으로 확장한다. 계층표와 guard 번호는 그 문서를 잇는다.

Decision:

1.  `app/llm/`은 **DB를 모르는 L1**이다. provider 호출과 deterministic
    validation이 여기 있고, session도 ORM 모델도 보지 않는다.
2.  `app/services/render.py`를 `app/render.py`로 옮기고 `app/normalization.py`를
    신설한다. 둘 다 L0다.
3.  provider abstraction의 상한은 **Protocol 1개 + 메서드 1개 +
    `build_provider()` 1개 + 구현체 1개**다. registry / plugin / capability
    negotiation / model router를 만들지 않는다. **`StubProvider`를 `app/`에
    두지 않는다.**
4.  guard G11 / G12 / G13을 추가하고 G7의 commit allowlist를 `app/jobs/`로
    확장한다.
5.  provider 호출 중에 DB 트랜잭션을 열어 두지 않는다. commit은
    `jobs/queue.py`와 `jobs/persistence.py`에만 있다.

## 계층

``` text
L0  models config settings clock db  render  normalization    app 내부 의존 없음
L1  srs/*   learning/*   llm/*        L0만. 서로 import 금지
L2  services/*   jobs/*               L0 + L1 + L2
L3  api/*                             L0 + L2 + schemas. L1 금지
```

`llm/`을 `learning/`·`srs/`와 같은 줄에 두는 이유는 같은 모양이기 때문이다.
정책 판단과 외부 생성은 **둘 다 트랜잭션을 모르는 계산**이고, DB를 읽어 값을
먹이고 결과를 저장하는 일은 `services/`와 `jobs/`가 한다. deterministic
validation 12항목 중 1\~10은 문자열·span·config만 보므로 DB 없이 단위 테스트된다.
11·12(duplicate)는 `jobs/`가 corpus를 읽어 순수 비교 함수에 넘긴다 ---
`near_original` 예외도 DB 조회가 아니라 인자다.

Wave 3이 추가하는 모듈은 이렇다.

``` text
app/llm/provider.py      Protocol + build_provider + OpenAIProvider
app/llm/prompts.py       task별 프롬프트 조립. 모델명 없음
app/llm/schema.py        structured output 스키마와 파싱
app/llm/validation.py    validation 1~10 + 11·12용 순수 비교 함수

app/jobs/replenishment.py  enqueue만 (기존)
app/jobs/queue.py          claim / 상태 전이 / backoff      commit
app/jobs/runner.py         job 1개 실행. provider 호출 지점  commit 없음
app/jobs/persistence.py    생성 결과 저장 + completed       commit
app/jobs/worker.py         loop. 시각과 provider를 인자로 받는다 (env를 읽지 않는다)
scripts/run_worker.py      프로세스 진입점. env를 읽어 provider를 만들어 주입한다
```

## L0로 옮기는 것

-   **`render.py`.** validation 6\~8(surface 일치, span boundary, overlap)이
    검사해야 하는 것이 정확히 `build_render_segments`가 이미 거부하는 것이다.
    복제하면 worker가 Ready로 선언한 문장을 request 경로의 렌더러가 500으로
    거절하는 형태로 갈라진다. 그런데 `llm/`(L1)이 `services/`(L2)를 import하면
    계층이 뒤집히므로 순수 모듈을 L0로 올린다. app 쪽 importer는
    `services/presentation.py` 한 곳뿐이다.
-   **`normalization.py`.** `normalized_sentence_text` / `normalized_hash` /
    `similarity_ratio`. `sentences.normalized_hash`를 쓰는 주체가 seed loader와
    generation persistence 둘이 되는데, 규칙이 갈리면 duplicate 검출이 **조용히**
    실패한다. `seed_loader._normalized_hash`가 임시로 정한 NFKC+공백제거 규칙을
    여기로 옮기고 그 자리는 호출로 바꾼다. 유사도는 `difflib`로 충분하다.

두 모듈이 L0로 남아야 G11이 성립한다. 나중에 `render.py`가 `app.models`를
import하면 `llm/`이 그 경로로 DB에 닿는다. 그래서 아래 G11이 두 절을 갖는다.

## provider abstraction의 상한

``` python
class LlmProvider(Protocol):
    def generate_structured(self, *, model: str, ...) -> ProviderResult: ...

def build_provider(name: str, *, api_key: str | None) -> LlmProvider: ...   # "openai" 하나
```

-   **모델명과 provider명은 코드가 아니라 `prompt_versions` 행에서 온다.**
    `provider` / `model`은 이미 NOT NULL이다(`models/jobs.py`). "모델명을
    business logic에 고정하지 않는다"(`08_LLM_SPEC.md`)를 추상화 계층이 아니라
    **데이터**로 만족시킨다. `build_provider`는 그 문자열을 client로 바꾸는
    유일한 지점이자 API key를 **client에 넣는** 유일한 지점이고, 모르는 이름은
    거절한다. 환경변수를 **읽는** 지점은 여기가 아니라 `scripts/run_worker.py`다
    --- `app/llm/`이 `app.settings`를 읽으면 G11(a)를 어기고 테스트가 값을 주입할
    수 없다. 그래서 `api_key`는 인자다(ADR-016의 `개정`).
-   **`StubProvider`를 `app/llm/`에 두지 않는다.** 두 번째 구현체는
    `backend/tests/`의 test double이다. Protocol은 그 주입 지점의 타입 선언이지
    단일 사용처를 위한 추상화가 아니다(CLAUDE.md #2).
    (정정 2026-09-12: 원문은 "키 없이 완주"라는 요구가 명세에 없다고 했으나
    그것은 사실이 아니다 --- `12_TEST_PLAN.md`의 integration 목록과
    `13_ACCEPTANCE_CRITERIA.md`가 실제 키 없이 generation 경로 전체를 실행할 것을
    요구한다. 결론은 바뀌지 않는다. 그 요구는 **진입점 주입**이 만족시키고,
    `app/`에 mock을 두는 것을 요구하지 않는다. `LLM_PROVIDER = stub`은 폐기됐다
    --- ADR-016의 `개정`.)
-   provider는 retry하지 않고 비용도 집계하지 않는다. 둘 다 job queue 소관이다.
    `runner`는 `provider`를 **인자로 받는다** --- 그 자리가 test double이 들어갈
    자리이고, 모듈 전역이나 import 시점 생성이 아니다.

## 정적 guard

``` text
G11  (a) app/llm/* 는 sqlalchemy / app.db / app.models / app.services /
         app.api / app.jobs / app.learning / app.srs 를 import하지 않는다.
         예외는 app.models.enums 하나뿐이다 (enum 정의만 있고 sqlalchemy를
         import하지 않는다).
     (b) app/render.py 와 app/normalization.py 는 app.* 를 import하지 않는다.
G12  (a) app/jobs/ 밖에서 import 가능한 jobs 모듈은 ENQUEUE_MODULES뿐이다.
         ENQUEUE_MODULES = {"jobs/replenishment.py"}
     (b) ENQUEUE_MODULES 의 모듈은 app.llm 을 import하지 않는다.
     (c) BackgroundTasks / add_task / starlette.background 는
         backend/app/ 어디에도 없다.
G13  importlib / __import__ 는 backend/app/ 어디에도 없다.
G7   (확장) app/jobs/ 안의 commit/rollback 은 jobs/queue.py 와
           jobs/persistence.py 에만 있다.
```

G4만으로는 불변식 #1이 지켜지지 않는다. `app/jobs/`는 `app.llm`을 **합법적으로**
import하므로, `services/`가 `app.jobs.runner`를 불러 "pool이 비었으니 지금 한 번
돌리자"를 하면 G4를 그대로 통과한다. G12는 그 통로를 막는다 --- denylist가 아니라
allowlist인 이유는 새 모듈이 조용히 빠져나가지 않게 하기 위해서다.
`scripts/run_worker.py`는 guard 검사 범위 밖이고(별도 프로세스 진입점), 그래서
worker loop를 부를 수 있는 유일한 자리다.

**"enqueue 모듈이 `generation_jobs` INSERT 외에 아무것도 하지 않는다"는 G12에서
뺀다(2026-09-12).** 원문은 이것을 G12의 "추가 조건"으로 적었으나 AST guard로 검사할
수 없는 조건이고, 검사할 수 없는 것을 정적 guard 문구에 두면 guard가 지키는 범위가
실제보다 넓어 보인다. 정적으로 남는 것은 (a)(b)(c)이며 (b)가 그 의도의 검사 가능한
절반이다 --- request 경로에서 불리는 유일한 jobs 모듈이 provider를 못 본다. 나머지
절반은 아래 런타임 테스트가 덮는다.

`BackgroundTasks`는 G12의 import 규칙만으로도 대개 막히지만 함께 금지한다.
응답 후 실행이라도 같은 프로세스·같은 세션이고, "provider는 worker에서만"의
가장 흔한 오답이다. G6(`listening_mastery`)과 같은 식별자 검사다.

## 정적과 런타임의 분담

정적 guard는 **모양**만 본다. `importlib.import_module("app.llm.provider")`는
AST에 보이지 않으므로 G13이 그 동적 import 자체를 없앤다. 남는 것은 런타임이
맡는다: request 경로 테스트(API / Scenario / Core E2E) 중 **단일 커넥션
fixture(`study_api`)를 쓰는 것**은 `no_outbound_network()` 안에서 돌고 끝나면
`assert_no_provider_import()`를 부른다. 소켓이 열려도, provider SDK가 `sys.modules`에
올라오기만 해도 실패한다.

**`no_outbound_network()`를 request를 보내는 모든 테스트에 걸 수는 없다.** 테스트
DSN이 unix socket이고 unix socket 연결도 그 헬퍼가 거부하는 바로 그 호출
(`socket.socket.connect`)을 지나간다. 단일 커넥션 fixture에서 통하는 것은 커넥션이
이미 열려 있어 재사용되기 때문이고, 요청이 새 pooled 커넥션을 여는 다중 커넥션
fixture(`committed_api` --- job → worker → pool을 실제로 밟는 테스트들)는 provider와
무관한 이유로 실패한다. 그러므로 fixture에 의존하지 않는 일반 메커니즘은 **별도
프로세스** 검사다:
`test_a_fresh_api_process_loads_neither_the_provider_module_nor_the_sdk`가 실제 요청을
처리한 프로세스의 `sys.modules`에 `app.llm*`도 provider SDK도 없음을 확인한다. 그래서
`sys.modules[...]`로 우회하는 경로도 죽는다 --- API 프로세스에서는 그 모듈이 애초에
적재되지 않는다.

G12에서 뺀 "INSERT 외의 일을 하지 않는다"를 덮는 것도 이 자리다. request 경로 전체를
밟는 테스트에서 **worker loop와 job runner가 실행되지 않았음**을 관측한다(`runner`의
job 실행 진입점과 `worker`의 loop를 감시하고, 호출되면 실패). 이름은
`test_request_path_never_reaches_the_worker_runner`이고 요구는 `12_TEST_PLAN.md`의
Integration 목록에 있다. 정적으로는 "enqueue 모듈이 runner를 import하지 않는다"까지가
한계이고, "그 함수가 실제로 안 불렸다"는 여기서만 증명된다.

## 트랜잭션 경계

commit 지점은 셋이다.

``` text
claim      queued -> running       queue.py    provider 호출 전
validated  running -> validated    queue.py    provider 응답이 검증을 통과한 직후
outcome    -> completed            persistence.py  콘텐츠 저장과 같은 트랜잭션
           -> queued(backoff) / failed / dead_letter    queue.py
```

-   **provider 호출은 어떤 트랜잭션 안에도 없다.** 수 초짜리 HTTP가 커넥션과
    행 잠금을 붙들면 request 경로가 같은 pool에서 굶는다. `llm/`이 session을
    아예 못 보게(G11) 만든 것이 이 규칙의 구조적 형태다. `runner`는 commit된
    값을 받아 `llm/`에 넘기고, 받은 값을 `persistence`에 넘긴다.
-   `completed`를 콘텐츠 저장과 **같은** 트랜잭션에 둔다. 나누면 저장은 됐는데
    completed가 아닌 job이 재실행되어 콘텐츠를 두 번 만든다.
-   `validated` 별도 commit을 채택하되 **효용을 축소해서 기록한다.** crash
    **재개** 지점이 아니라 **진단** 지점이다. raw provider 응답을 저장하지 않으므로
    `validated`에서 재실행해도 provider를 다시 부른다. 사는 것은 "provider 실패 /
    validation 실패 / 저장 실패"가 `status`+`last_error`로 갈린다는 것뿐이고,
    원칙 10의 retry/failure 지표가 그것을 쓴다. 비용은 job당 commit 한 번이다.
    `09_BACKGROUND_JOBS.md`가 `validated`를 상태 목록에 못박았으므로 접는 선택지도
    없다 --- 트랜잭션 안에서만 존재하는 상태는 상태가 아니다.
-   `retry_count` 증가는 claim commit에 포함한다. 실패 경로에서 올리면 crash한
    job이 영원히 재시도된다.

## 한계

-   **"트랜잭션을 연 채 provider를 부른다"는 정적으로 못 잡는다.** G11이 `llm/`의
    DB 접근을 없애 대부분을 구조로 막지만, `runner`가 `queue`의 세션을 붙든 채
    `llm/`을 부르는 것은 문법적으로 가능하다. runner가 값만 나른다는 것이 유일한
    방어다.
-   **불변식 #2는 여전히 정적으로 안 잡힌다.** G11은 `llm/`이 `learning/`를
    **보지 못하게** 할 뿐, worker가 LLM 응답을 정책 판단에 먹이는 것은 막지
    못한다. validation의 반환 타입을 accept/reject로 좁게 두는 것과 Scenario
    테스트가 그 자리를 메운다.
-   `subprocess`로 프로세스 밖에서 worker를 돌리는 경로는 guard하지 않는다.
    쓰인 적이 없고, 막으면 실익 없는 금지 목록만 는다.
-   worker heartbeat 저장 위치는 `09_BACKGROUND_JOBS.md`가 미결로 둔 그대로다.
    이 ADR에서 정하지 않는다.
