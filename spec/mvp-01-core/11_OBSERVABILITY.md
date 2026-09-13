# Observability

App: sessions/day, study minutes, sentences, clicks, self-report,
probes, reviews, meaningful exposures, flags.

LLM: calls/task, input/output/cached tokens, cost, failures, validation
failures, retry, pool size, queue length.

Cost efficiency: cost/session, cost/generated sentence, cost/learned
item, tokens/learning minute.

Ops: FastAPI/worker/Postgres health, disk, backup success. secret/auth
token log 금지.

MVP는 거대한 analytics stack을 만들지 않지만, 개인 사용 중 문제와 비용을
추적할 수 있어야 한다. secret, password, raw auth token을 log하지 않으며
LLM debugging에 필요한 provenance는 content/job id 중심으로 추적한다.

## MVP 필수 범위

MVP에서 반드시 수집하는 것은 다음으로 제한한다.

``` text
job count
provider call count
input/output tokens
estimated cost if available
failure/retry count
ready pool size
```

앱 지표(sessions/day, study minutes, sentences, clicks, self-report,
probes, reviews, meaningful exposures, flags)는 `learning_events`와
`item_exposures`에서 집계할 수 있으면 충분하며 별도 대시보드를 만들지
않는다.

### 저장 위치 (MVP 확정)

**metrics 전용 테이블을 만들지 않는다.** 위 항목은 전부 기존 테이블에서
읽는다.

``` text
job count / status         generation_jobs
provider call count        generation_jobs.result_ref.usage.provider_calls
input/output tokens        generation_jobs.result_ref.usage.*_tokens
estimated cost             generation_jobs.result_ref.usage.estimated_cost_usd
failure / retry count      generation_jobs.status / retry_count / last_error
validation failure 사유    generation_jobs.result_ref.rejected + 로그
                           (사유 코드 집합은 08_LLM_SPEC.md가 canonical)
ready pool size            user_sentence_candidates의 status = ready 건수
queue length               generation_jobs의 status IN ('queued','retry') 건수
worker liveness            worker_heartbeats.last_heartbeat_at (05_API_SPEC.md)
```

`usage` 기록 규칙과 집계의 **UTC 일 경계**는 `09_BACKGROUND_JOBS.md`의
`usage 기록과 일 경계`가 canonical이다. 그 규칙에 따라 `usage.*_tokens`는
`null`일 수 있고 **`null`은 0이 아니다**. 필수 수집 항목이므로 로그의 token
필드는 값이 `null`이어도 싣는다. 또 daily ceiling으로 생성을 멈춘 것이 한도
자체가 아니라 unknown token 때문일 수 있으므로, **멈춤 로그에 token이 `null`인
job 수를 함께 싣는다.**

`cached tokens`는 **MVP 필수가 아니다.** 위 `MVP 필수 범위` 목록이 닫힌
집합이고 거기에 없다. MVP는 기록하지 않으며 `usage` 구조에 키를 추가하지
않는다(`04_DB_SPEC.md`의 `result_ref 구조`가 MVP 확정이다). 문서 맨 위
`LLM:` 줄의 `cached tokens`는 장기 지표 쪽이고, prompt caching 최적화 자체도
MVP 의무가 아니다(`spec/06_LLM_ENGINEERING_PRINCIPLES.md`). 필요해지면
`result_ref 구조`를 먼저 고친다.

## MVP-02 추가: 후리가나 계산 결과

위 `MVP 필수 범위`의 닫힌 집합과 `04_DB_SPEC.md`의 `result_ref 구조`는 **바꾸지 않는다.** 이
절은 그 집합에 항목을 더하는 것이 아니라 별도 절이다. metrics 전용 테이블을 만들지 않는다는
규칙도 그대로다.

후리가나(ruby)를 계산하는 네 곳이 각자의 **로그와 출력**에 계산 결과를 남긴다.

``` text
seed 적재               적재 명령의 stdout 요약
worker 생성 파이프라인   구조화 로그 이벤트 (아래)
기존 문장 backfill       스크립트 stdout 요약 (dry-run 포함)
demo fixture 생성        스크립트 stdout 요약
API 표시 시점            저장값 무효 로그 (아래)
```

로그 이벤트:

``` text
worker  ruby.computed              info     sentence_id, algorithm_version, spans, omitted_tappable_boundary,
                                            omitted_numeric, omitted_no_reading,
                                            corrected_explanation_tokens, corrected_table_rules
        ruby.failed                warning  sentence_id, error
        ruby.reading_mismatch      info     sentence_id, sentence_item_id
        ruby.explanation_override  info     sentence_id, sentence_item_id
API     ruby.invalid_stored        warning  sentence_id   (저장값이 검증을 통과하지 못함)
```

-   **문장 텍스트와 읽기 문자열은 로그에 남기지 않는다**(생성 콘텐츠 원문을 로그에 싣지 않는 기존 규칙).
-   분석기·사전 버전은 로그가 아니라 `sentences.ruby_json` 안에 남는다(`04_DB_SPEC.md`의 `ruby_json`).
    로그에는 `algorithm_version`만 싣는다.

CLI stdout 요약(seed·backfill·fixture 생성 공통):

``` text
ruby: algorithm_version=2 sentences=N computed=N failed=N omitted_tappable_boundary=N
      omitted_numeric=N omitted_no_reading=N corrected_explanation_tokens=N
      corrected_table_rules=N reading_mismatches=N explanation_overrides=N
rule 私->わたし hits=N          (교정 표 규칙 순서대로 한 줄씩, 0이어도 출력)
mismatch kind=<reading_mismatch|explanation_override> sentence=<seed_id 또는 id>
         item=<sentence_item_id> surface=<표면형> explanation=<설명 읽기> analyzer=<분석기 읽기>
```

CLI 출력은 운영자 터미널 출력이고 로그 파일이 아니므로 표면형과 읽기를 싣는다. **설명 읽기처럼 LLM에서 온
문자열은 제어문자(개행, ESC 등)를 이스케이프해 출력한다.** 터미널 제어 시퀀스가 실행되거나 한 항목이 여러
줄로 갈라져 목록을 위조하지 않게 하기 위해서다. 생략 비율 판정의 분모인
"한자를 포함한 토큰 수"도 요약에 함께 낸다.

미계산 잔량: `SELECT count(*) FROM sentences WHERE ruby_json IS NULL`. 새 테이블이 없다.

-   **생략 비율**은 "경계 때문에 생략한 토큰 수 / 한자를 포함한 토큰 수"다. 판정 샘플은 seed
    전체 문장이다. 이 비율이 5%를 넘으면 한자 run 정렬로 tappable span 경계를 지킬 수 없는 경우가
    흔하다는 뜻이므로 구현을 멈추고 보고한다. 이 5%는 MVP-02 진행 판정 기준이며 학습 정책값이
    아니다.
-   **`explanation.reading` 불일치**는 한자를 포함한 tappable item만 비교한다. 설명 읽기는 NFKC 뒤 모든
    공백을 없애고 가타카나를 히라가나로 바꾼다. 분석기 읽기는 교정 계층 1(설명 읽기 우선)을 뺀 계산(교정
    표는 포함)으로 그 item의 span에 대해 낸 읽기다. 보고는 두 종류다.

    ``` text
    reading_mismatch      설명 읽기로 정렬이 성립하지 않았고 두 읽기가 다르다 -> 저장된 ruby는 분석기 읽기
    explanation_override  설명 읽기로 정렬이 성립했고 두 읽기가 다르다     -> 저장된 ruby는 설명 읽기
    ```

    `explanation_override`를 따로 보는 이유는 생성 문장의 설명 읽기가 LLM 출력이고 읽기의 정확성은 검증하지
    않기 때문이다. 결과는 **stdout과 로그로만** 낸다. DB에 저장하지 않고 설명 데이터를 자동으로 고치지
    않는다(`03_UI_UX_SPEC.md`의 `후리가나와 item 설명 reading의 관계`).
-   계산 실패는 문장 채택을 막지 않는다(`10_ERROR_HANDLING.md`의 `후리가나 계산 실패 (MVP-02)`).
    그래서 실패는 이 관측으로만 드러난다.
-   **frontend 관측은 없다.** 후리가나 토글, 가나 학습, demo 진행은 수집하지 않는다. 공개 화면은
    서버 요청이 0건이고(불변식 13), 이 동작들은 학습 신호가 아니다(`02_LEARNING_POLICY.md`의
    `학습 신호가 아닌 것 (MVP-02)`).

-   `ruby.*` 이벤트는 기존 worker 로그 이벤트에 더하는 **별도 이름공간**이다. 기존 이벤트의 이름과 필드를
    바꾸지 않는다. 정의의 canonical은 ADR-021이다.

## Future

위의 Cost efficiency 지표 중 `cost/learned item`, `tokens/learning
minute` 같은 고급 지표는 **장기 지표**다. "learned item"의 정의가 실제
사용 데이터로 확정되기 전까지 MVP 합격 조건으로 쓰지 않는다.

대시보드, 고급 analytics, admin UI는 Future다
(`spec/future/ADMIN_AND_DATA.md`).

**로그인 실패 시도 로그와 알림도 Future다.** MVP는 실패마다 로그를 남기지
않는다. 온라인 추측 공격 상황에서는 초당 수십 건이 들어와 로그 자체가 디스크
압박이 되기 때문이다. 근거는 `spec/04_SECURITY_AND_DATA.md`의
`온라인 무차별 대입 방어 (MVP 확정)`.
