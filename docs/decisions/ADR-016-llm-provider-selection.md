# ADR-016 --- provider 구현 선택과 mock provider

Status: Accepted --- 2026-09-12 개정 (`개정` 절이 아래 본문보다 우선한다)

Decision: 두 축을 분리한다.

``` text
어떤 client 코드를 쓰는가    환경변수 LLM_PROVIDER = openai   (기본값 없음)
provider secret              환경변수 LLM_API_KEY   (worker 프로세스에만 주입)
어떤 모델에 무엇을 보내는가  prompt_versions 행의 provider / model
```

실제 키 없이 generation 경로 전체를 실행하는 수단은 **worker 진입점이
provider를 주입받는 것**이고, 그 자리에 들어가는 mock 구현은 `backend/tests/`의
test double이다. env 값이 아니다. 안전장치는 **fail-closed 부팅 검사**다.

``` text
LLM_PROVIDER 미설정 또는 openai 아님           -> worker 부팅 실패
LLM_PROVIDER = openai 이고 LLM_API_KEY 없음    -> worker 부팅 실패
```

canonical 정의: `spec/04_SECURITY_AND_DATA.md`의
`LLM provider 자격증명 (MVP 확정)`, `spec/mvp-01-core/08_LLM_SPEC.md`의
`Provider 선택과 model 출처`.

## 개정 (2026-09-12) --- stub은 env 값이 아니라 주입되는 test double이다

이 ADR의 원안(`LLM_PROVIDER = openai | stub`, 기본값 `stub`)은
`ADR-015-llm-worker-module-boundaries.md`의 "`StubProvider`를 `app/`에 두지
않는다"와 정면으로 충돌했다. `build_provider`가 `openai` 하나만 만들므로
기본 설정으로 worker를 띄우면 `ProviderConfigError`이고, `LLM_PROVIDER = stub`을
만족시킬 앱 코드가 존재하지 않았다.

두 의도는 양립한다. 원안이 지키려던 것은 **"실제 키 없이 worker loop / claim /
lease / validation / 저장까지 실제 코드로 실행한다"**이고, ADR-015가 지키려던
것은 **"production에서 쓰이지 않는 구현체를 앱 코드에 두지 않는다"**(CLAUDE.md
#2)다. 주입으로 둘 다 만족한다.

``` text
production   scripts/run_worker.py 가 env를 읽어 build_provider()로 만든 것을 주입
test         backend/tests/ 의 test double을 같은 인자로 주입
```

확정 사항은 넷이다.

1.  **`LLM_PROVIDER`의 허용값은 `openai` 하나이고 기본값이 없다.** 미설정이거나
    다른 값이면 worker 진입점이 부팅에 실패한다. 원안의 "기본값 `stub`"이 막으려던
    것(값을 잊은 개발 머신에서 유료 호출이 먼저 일어남)은 기본값 부재가 더 강하게
    막는다 --- 최악의 경우가 "콘텐츠가 생기지 않는다"인 것은 같고, 운영자가
    provider를 의식적으로 고르게 된다. 반대로 기본값을 `openai`로 두면 그 위험이
    되살아나므로 두지 않는다.
2.  **`APP_ENV = production`이면 부팅 실패라는 검사를 없앤다.** 검사할 값 자체가
    없다. mock을 선택하는 경로가 앱 코드에 존재하지 않는 것이 런타임 검사보다
    강한 보장이다(`04_SECURITY_AND_DATA.md`가 Public Demo에 쓴 "structurally
    impossible"과 같은 형태). `APP_ENV`는 배포 표면 제어에만 쓴다는 규칙도 그대로
    유지된다.
3.  **`stub`은 provenance 값으로만 남는다.** `prompt_versions.provider` /
    `provenance_json.provider`가 `stub`인 행은 test double이 만든 콘텐츠다.
    stub 응답도 똑같은 deterministic validation을 통과해야 저장된다는 규칙은
    바뀌지 않는다 --- 오히려 그것이 test double을 두는 유일한 이유다.
4.  **`build_provider`는 `api_key`를 인자로 받는다.** `app/llm/`이 `app.settings`를
    읽으면 G11(a)를 어기고 테스트가 값을 주입할 수 없다. 환경변수를 읽는 유일한
    지점은 worker 진입점이고, `build_provider`는 **key를 client에 넣는** 유일한
    지점이다. 원안의 "API key를 읽는 유일한 지점"이라는 표현을 이렇게 정정한다.

아래 `왜 stub을 명세에 넣는가` / `왜 기본값이 stub인가` 두 절은 **대체되었다.**
근거의 흐름을 남기기 위해 지우지 않는다.

## 문제

`02_ARCHITECTURE.md`와 `04_SECURITY_AND_DATA.md`는 "OpenAI key"만 말하고
env 변수명도, 모델명을 어디서 읽는지도 정하지 않았다. 한편
`06_LLM_ENGINEERING_PRINCIPLES.md` 8번은 "모델명 hard-code 금지", 15번은
"provider abstraction 유지"를 요구한다. 구현자는 모델명을 코드·config
YAML·env 중 어디에 둘지 알 수 없었다.

동시에 Wave 3은 **실제 provider 키 없이 완주**해야 한다. 그러려면 provider
호출을 대체하는 구현이 있어야 하고, 그것을 "테스트에서만 monkeypatch하는
물건"으로 두면 worker loop / claim / lease / validation / 저장까지 이어지는
경로가 실제 코드로는 한 번도 실행되지 않는다.

## 왜 stub을 명세에 넣는가

**(개정으로 대체됨. 아래 세 가지 요구는 test double의 계약을 `08_LLM_SPEC.md`와
`12_TEST_PLAN.md`에 두는 것으로 그대로 만족한다.)**

`04_SECURITY_AND_DATA.md`는 이미 Public Demo에 대해 "paid LLM call =
structurally impossible"을 구조로 보장한다. mock provider는 같은 성질을
개발·테스트 환경으로 확장한다. 명세에 없는 채로 구현에만 존재하면 세 가지가
생긴다.

-   테스트가 의존하는 물건의 계약(무엇을 돌려주는가, validation을 거치는가)이
    아무 데도 없다.
-   "production에서 절대 선택되면 안 된다"는 제약을 강제할 근거가 없다.
-   stub이 만든 콘텐츠와 실제 콘텐츠를 사후에 구분하는 규칙이 없다.

그래서 세 가지를 함께 못박았다. stub 응답도 **똑같은 deterministic
validation을 통과해야** 저장되고, `provenance_json.provider = "stub"` /
`model = "stub"`으로 기록되며, production에서는 부팅이 실패한다.

## 왜 기본값이 stub인가

**(개정으로 대체됨. 결론은 "기본값을 두지 않는다"이며 막으려는 위험은 같다.)**

값을 잊은 환경에서 기본값이 `openai`이면, 키가 어쩌다 존재하는 개발 머신이
곧바로 유료 호출을 시작한다. 기본값이 `stub`이면 최악의 경우가 "콘텐츠가
생기지 않는다"이고, production은 위 부팅 검사 때문에 값을 반드시 명시해야
하므로 조용히 stub으로 도는 production은 존재할 수 없다.

## 버린 대안

**(a) 모델명을 `14_CONFIGURATION.md`에 둔다.** 그 파일은 학습 정책값의
자리이고 `APP_ENV` / cookie 수명 / password 하한을 이미 같은 이유로
제외했다. 게다가 모델을 바꾸면 **그 모델로 만든 콘텐츠의 provenance**가
바뀌는데, config YAML에는 그 이력이 남지 않는다. `prompt_versions`는 행이
쌓이므로 남는다.

**(b) 모델명을 env(`LLM_MODEL`)에 둔다.** (a)와 같은 provenance 문제에
더해, prompt 본문과 모델이 따로 논다. prompt는 특정 모델을 전제로 쓰이므로
같은 행에 있어야 한다.

**(c) stub 없이 테스트에서만 provider client를 monkeypatch한다.** worker
경로가 실제로 실행되지 않는다. (개정 주: 반대는 monkeypatch에 대한 것이지
test double 자체에 대한 것이 아니었다. **진입점 주입**은 monkeypatch가 아니라
정식 인자이므로 worker 경로가 실제 코드로 끝까지 실행된다 --- 이 반대는 주입으로
해소되고 env 값 `stub`을 요구하지 않는다.) `12_TEST_PLAN.md`의 integration 목록이
요구하는 "job을 끝까지 실행하면 candidate가 만들어진다"를 검증할 수 없다.

**(d) `APP_ENV`로 provider를 자동 선택한다** (production이면 openai,
아니면 stub). 변수 하나가 줄지만 `APP_ENV`는 **배포 표면 제어에만** 쓰기로
이미 정했다(`04_SECURITY_AND_DATA.md`의 `배포 환경 구분`). 기능 동작을
환경으로 분기시키는 순간 그 규칙이 깨지고, 실제 키로 개발 환경에서 한 번
돌려보는 일도 불가능해진다.

## 수용된 위험

stub이 만든 콘텐츠가 실제 DB에 남는다. (개정 후: test double은 테스트에서만
주입되므로 stub 콘텐츠는 테스트 DB에만 생긴다. 아래는 그럼에도 섞였을 때의
식별 수단으로 유효하다.) 개발 DB와 production DB가 같은 일은
없어야 하지만, 섞이더라도 `provenance_json.provider = "stub"`으로 골라낼 수
있다. stub 콘텐츠를 자동으로 지우는 정리 job은 만들지 않는다 --- MVP의
job_type 목록에 maintenance가 없고, 필요해지면 그 목록을 먼저 고친다.
