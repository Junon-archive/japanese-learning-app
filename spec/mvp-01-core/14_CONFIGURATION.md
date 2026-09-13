# Configuration

실사용 후 바뀔 값은 hard-code하지 않는다.

``` yaml
learning:
  default_session_minutes: 12
  extra_session_minutes: 5
  review_ratio: 0.70
  new_ratio: 0.20
  exploration_ratio: 0.10
  preferred_new_items_per_sentence: 1
  max_new_items_per_sentence: 2
  minimum_meaningful_exposures: 5
  # probe budget. min은 관측 목표이고 엔진이 강제하지 않는다.
  # 강제 조건은 max와 아래 간격뿐이다 (06_LEARNING_ENGINE.md의 Probe Pacing).
  mastery_probe_target_per_session_min: 2
  mastery_probe_target_per_session_max: 4
  # 세션 내 probe 최소 간격 (presentation 수, 06_LEARNING_ENGINE.md)
  probe_min_gap_presentations: 3

  # mastery 갱신 (02_LEARNING_POLICY.md)
  mastery_ema_alpha: 0.4

  # 무신호 passive review 후 단기 재노출 방지 (07_SRS_SPEC.md)
  passive_review_deferral_hours: 12

  # probe 대상 선정 (02_LEARNING_POLICY.md)
  passive_exposures_before_probe: 3
  probe_skip_cooldown_days: 7

  # backlog 제어 (06_LEARNING_ENGINE.md)
  backlog_threshold: 50
  backlog_review_ratio: 0.85
  backlog_new_ratio: 0.05
  backlog_exploration_ratio: 0.10

  # review 슬롯 내부 reason 선택 (06_LEARNING_ENGINE.md)
  reinforcement_min_share_of_review: 0.2

  # exploration 대상 선정 (06_LEARNING_ENGINE.md)
  exploration_recent_days: 14

  # Ready Pool 생성 1회 실행당 role별 상한 (06_LEARNING_ENGINE.md의
  # Candidate Materialization). 없으면 첫 세션에서 seed 전체가 복제된다.
  candidate_materialization_batch_size: 20

srs:
  # FSRS 결정론 (ADR-003, 07_SRS_SPEC.md)
  # 대규모 덱용 jitter이므로 MVP에서는 끄고 테스트 재현성을 택한다.
  fsrs_enable_fuzzing: false

session:
  # 23_ 결정
  study_session_idle_timeout_minutes: 30
  active_time_idle_gap_seconds: 120

user:
  user_timezone: "Asia/Seoul"

content:
  translation_default_visible: false
  reading_default_visible: false
  # deterministic validation (08_LLM_SPEC.md)
  max_sentence_length_chars: 60
  duplicate_similarity_threshold: 0.90

jobs:
  # 22_ 결정
  max_job_attempts: 3
  retry_backoff_base_seconds: 60
  # worker loop (09_BACKGROUND_JOBS.md)
  poll_interval_seconds: 5
  # running에 갇힌 job을 회수하는 임계값 (stale running 회수)
  claim_lease_seconds: 300
  # 생존 신호 쓰기 간격과 /api/health의 stale 판정 임계값 (Worker Heartbeat)
  heartbeat_interval_seconds: 30
  heartbeat_stale_seconds: 120

llm:
  # Public Demo는 static frontend fixture이므로 API/worker를 사용하지
  # 않는다. 이 flag는 구조적 분리에 더한 안전장치이며 true로 바꾸지 않는다.
  public_demo_generation_enabled: false
  # null = limit disabled. production은 두 키 모두 integer를 설정한다
  # (아래 production override).
  # 판정은 UTC 일 경계다 (09_BACKGROUND_JOBS.md의 usage 기록과 일 경계).
  daily_request_limit: null
  daily_token_limit: null
  # generation batch 1회가 요청하는 문장 수이자 대상 item 수 상한
  # (08_LLM_SPEC.md의 GENERATE_SENTENCE_BATCH 대상 선정)
  sentences_per_batch: 5
  # 프롬프트에 싣는 item당 기존 문장 예시 수 (08_LLM_SPEC.md의 요청 context)
  avoid_examples_per_item: 3
```

초기 승인값이지 영구적인 학습 법칙이 아니다.

`reading_default_visible`은 항상 `false`를 유지한다. 이 키는 **item 설명의
reading** reveal 기본 상태를 뜻한다(`03_UI_UX_SPEC.md`의 `Explanation`).

**MVP-02의 후리가나와는 다른 것이다.** 후리가나(학습 문장 속 한자의 읽기)의 켬/끔은 사용자가
브라우저에서 고르는 표시 설정이고, 기본은 끔이며, 브라우저 localStorage에만 있다
(`03_UI_UX_SPEC.md`의 `Translation/Furigana`, `spec/04_SECURITY_AND_DATA.md`의
`localStorage 사용 범위 (MVP-02 확정)`). 이 파일의 키가 아니고 서버가 읽지도 않는다. 이 키로
후리가나 기본값을 바꾸지 않으며, 후리가나 설정 키를 이 파일에 새로 두지 않는다. MVP-01 명세의
"furigana 상시 표시 금지"는 MVP-02에서 "기본 끔, 사용자가 켤 수 있음"으로 바뀌었고 이 키의 뜻은
그대로다.

`content.translation_default_visible`과 `content.reading_default_visible`을
**frontend가 읽는 경로는 없다.** 두 값이 기술하는 것은 API 구조가 이미 강제하고
있다 --- presentation payload에는 `korean_translation` 필드도 **item 설명의 reading** 필드도
존재하지 않으므로(`05_API_SPEC.md`의 `Sentence Presentation Payload`,
`Interaction`) 번역과 item 설명의 reading은 각각 `/translation/reveal`과 `/click`을 거쳐야만
나온다. 따라서 **이 두 키를 `true`로 뒤집어도 화면은 달라지지 않는다.** 값을 넘길
endpoint를 만들면 숨김 규칙의 source of truth가 둘이 되고, 그중 하나가 뒤집히는
사고가 가능해진다. 두 키는 "기본 노출 상태는 hidden이다"라는 정책 기록으로만
남기고 소비처를 만들지 않는다.

MVP-02에서 presentation payload에는 **문장 ruby**(`render_segments[].ruby`)가 실린다
(`05_API_SPEC.md`의 `render_segments[].ruby`). 이것은 위 문단이 말하는 item 설명의 reading이 아니다.

``` text
item 설명의 reading   sentence_item_explanations.reading. /click 응답에만 있다. 변경 없음
                      reading_default_visible: false 는 이 설명 패널 reading의 기본 상태다
문장 ruby             sentences.ruby_json에서 온 render_segments[].ruby. 문장 전체 한자의 표시 보조.
                      토글과 무관하게 항상 payload에 있다. event를 만들지 않는다
후리가나 토글          브라우저 localStorage. 기본 끔. 서버·config에 없다
```

-   ruby는 학습 신호가 아니다. 후리가나를 켜면 tappable 표현의 읽기가 탭 전에 보일 수 있지만 어떤 정책도
    "읽기를 보았는가"를 입력으로 쓰지 않으므로 `item_clicked`·`explanation_revealed`의 의미는 그대로다
    (`02_LEARNING_POLICY.md`의 `학습 신호가 아닌 것 (MVP-02)`).
-   **후리가나 토글 기본값을 config 키로 두지 않는다.** 서버가 소비하지 않는 값이고, 두면 기본값의 source
    of truth가 둘(config와 frontend)이 된다.

비율 키(`review_ratio`, `new_ratio`, `exploration_ratio`)의 합은 1.0이어야
하며 config 로드 시 검증한다.

backlog 모드의 비율 키(`backlog_review_ratio`, `backlog_new_ratio`,
`backlog_exploration_ratio`)도 **동일하게 합 1.0을 검증한다.** backlog
모드는 세 ratio를 이 세트로 통째로 교체하며 같은 deficit 계산에 그대로
들어가기 때문이다(`06_LEARNING_ENGINE.md`의 `Backlog`).

`reinforcement_min_share_of_review`는 category 비율이 아니라 review 슬롯
**내부** 지분이므로 어느 합 검증에도 포함되지 않는다. 허용 범위는
`[0.0, 1.0]`이며 0.0이면 최소 지분 규칙이 꺼진다.

`mastery_probe_target_per_session_min`은 **엔진 제약이 아니라 관측
목표**다. 엔진이 강제하는 것은 `mastery_probe_target_per_session_max`와
`probe_min_gap_presentations`뿐이며, min을 채우려고 cooldown이나 대상
우선순위를 깨지 않는다. 이유는 `06_LEARNING_ENGINE.md`의
`Probe Pacing`에 있다. probe가 너무 드물면 min을 올리는 것이 아니라
`probe_min_gap_presentations`를 줄인다.

`probe_min_gap_presentations`와 `candidate_materialization_batch_size`는
양의 정수다.

`preferred_new_items_per_sentence`는 **생성 프롬프트에 싣는 선호값**이지
강제 상한이 아니다. 유일한 소비처는 `GENERATE_SENTENCE_BATCH`의 요청
context다(`08_LLM_SPEC.md`의 `요청 context`). 강제되는 값은
`max_new_items_per_sentence` 하나이며 그것을 검사하는 곳은 생성 validation
**5번과 10번** 그리고 materialization의 target 부착 규칙이다
(`06_LEARNING_ENGINE.md`). 5번은 문장의 target 전부를, 10번은 그중 신규 item만
세며 MVP에서는 두 상한이 이 키 하나에서 오므로 10번이 구조적으로 발화하지
않는다(`08_LLM_SPEC.md`의 `target 수 상한의 출처와 검사 10의 지위`).
선호값을 어겼다는 이유로 생성된 문장을 버리지 않는다 --- 버리면 비용을 치른
자연스러운 문장을 숫자 하나 때문에 폐기하게 된다.

`jobs`의 새 키(`poll_interval_seconds`, `claim_lease_seconds`,
`heartbeat_interval_seconds`, `heartbeat_stale_seconds`)와 `llm`의
`sentences_per_batch` / `avoid_examples_per_item`은 모두 **양의 정수**다.
추가로 다음을 config 로드 시 검증한다.

``` text
heartbeat_stale_seconds > heartbeat_interval_seconds
```

임계값이 쓰기 간격보다 작거나 같으면 정상 동작 중인 worker가 주기적으로
`stale`로 보고된다. `claim_lease_seconds`는 job 하나의 최대 실행 시간보다
넉넉해야 하며(짧으면 살아 있는 job을 회수한다) 그 관계는 코드로 검증할 수
없으므로 운영 판단이다.

**운영 판단 대상으로 기록하는 사실:** 현재 provider client는 SDK 기본값으로 돌며,
그 기본값은 요청 timeout 600초에 자동 재시도 2회다. 따라서 provider 호출 하나가
**30분을 넘길 수 있고** 이는 기본 `claim_lease_seconds`(300초)보다 길다. 즉 위
"lease는 job 하나의 최대 실행 시간보다 넉넉해야 한다"는 관계가 **기본값에서 성립하지
않는다.** 어느 쪽을 맞출지는 결정하지 않았다.

`daily_token_limit`이 integer일 때, 그날 token 총량을 **모르는** job이 하나라도
있으면 한도는 도달한 것으로 본다(fail-closed). 이는 `null = limit disabled`와
모순되지 않는다 --- `null`은 판정 자체를 하지 않는다는 뜻이고 fail-closed는
한도를 **켜 둔** 경우에만 적용된다. `daily_request_limit`은 영향받지 않는다.
근거와 판정식은 `09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`가 canonical이다.

**알려진 공백 --- 두 사용량 한도의 허용 범위:** `daily_request_limit`과
`daily_token_limit`은 `null` 또는 integer인데, 위 다른 정수 키와 달리 integer일 때의
**허용 범위가 정해져 있지 않다.** 로더도 범위를 검사하지 않는다. 한도 판정이 "오늘
사용량 `>=` 한도"이므로 **0이나 음수를 넣으면 매 판정이 도달로 끝나 생성이 영구히
멈춘다** --- UTC 날짜가 바뀌어도 풀리지 않는다. 한도를 끄는 방법은 `null`이며 0은 끄는
방법이 아니다. 허용 범위는 결정하지 않았다.

`srs`, `session`, `user`, `content`, `jobs`, `llm` 섹션의 키는 비율 합
검증 대상이 아니다.

`context_stage` progression ladder(`anchor -> near_original -> varied ->
new_context`)의 전이 조건도 **이 파일에 두지 않는다.** 조정 대상이 될 만한
값은 "한 stage에 몇 번 머무는가"인데, 그것을 키로 두려면 *현재 stage에서 몇 번
노출했는가*를 저장할 새 컬럼이 필요하고 MVP는 새 컬럼을 만들지 않는다. ladder
변경은 config 변경이 아니라 `07_SRS_SPEC.md`의 `전이 규칙` 변경이다. 노출
총량을 조절하는 키는 `minimum_meaningful_exposures` 하나다.

인증 session cookie의 이름·속성·수명은 **이 파일에 두지 않는다.** 학습
정책이 아니라 배포·보안 설정이므로 `APP_ENV`와 같은 취급이다. canonical
정의는 `spec/04_SECURITY_AND_DATA.md`의 `Session Cookie (MVP 확정)`이고,
수명은 환경변수 `AUTH_SESSION_TTL_DAYS`(양의 정수, 기본 30)다.

password 최소 길이도 **이 파일에 두지 않는다.** 환경변수도 아니며 코드에
고정한다(낮추는 스위치를 만들지 않는다). canonical 정의는
`spec/04_SECURITY_AND_DATA.md`의 `Password 요구사항 (MVP 확정)`이다.

백업 주기와 보관 개수도 **이 파일에 두지 않는다.** 학습 정책이 아니라 운영값이고
API·worker가 쓰지 않는다. canonical 정의는 `spec/04_SECURITY_AND_DATA.md`의
`주기와 보관 개수 (MVP 확정)`이다.

MVP-02의 demo 전용 상수(`DEMO_REVIEW_AFTER_SENTENCES`, `DEMO_PROBE_EVERY_SENTENCES`)와 가나
학습의 라운드 규칙도 **이 파일에 두지 않는다.** 학습 정책값이 아니라 static fixture 체험 흐름의
간격이고 서버가 쓰지 않는다. canonical 정의는 `03_UI_UX_SPEC.md`의 `Demo`와 `가나 학습`이다.

MVP-02 후리가나 계산의 **교정 표(`CORRECTION_RULES`)와 `algorithm_version`도 이 파일에 두지 않는다.**
실사용 후 튜닝하는 학습 정책값이 아니라 읽기의 사실 교정이며, demo fixture 일치 테스트에 묶인 알고리즘의
일부라서 `backend/app/furigana.py`의 코드 상수로 같은 커밋에서 바뀐다. 이 파일에 두면 production의 전체
사본과 어긋날 수 있고 운영자가 표를 바꿔도 버전이 오르지 않는다. canonical 정의는 ADR-021이다.

## production override (MVP 확정)

repo의 `config/default.yaml`에서 `daily_request_limit`과 `daily_token_limit`은
**`null`로 유지한다.** production은 두 한도를 **둘 다** integer로 켠다. 값은 이 명세가
정하지 않고 운영자가 정한다. `null = limit disabled`의 의미는 바꾸지 않는다.

``` text
repo 기본값   config/default.yaml                두 한도 null
production    NC_CONFIG_PATH -> 전체 파일 사본   default.yaml과 두 한도 줄만 다르다
```

-   **부분 override는 없다.** 로더가 누락 키와 모르는 키를 모두 거부하므로 override
    파일은 `default.yaml`의 **전체 사본**이어야 한다. 두 키만 담은 파일로는 기동하지
    못한다. `NC_CONFIG_PATH`의 정의는 `spec/04_SECURITY_AND_DATA.md`의
    `학습 정책 파일 경로 (MVP 확정)`이다.
-   **사본은 `default.yaml`과 사용량 한도 두 줄만 달라야 한다.** production에서 학습
    정책값을 따로 튜닝하는 통로로 쓰지 않는다. 승인값은 `default.yaml` 한 곳이다.
-   **override 파일은 Git에 넣지 않는다.** 저장소 작업 트리 밖에 둔다 --- 트리 안에
    두면 커밋되지 않는 것이 무시 규칙 하나에 기댄다.

### 전체 사본이 만드는 두 가지 실패

-   **`default.yaml`에 키가 추가되면 production 기동이 실패한다**(키가 삭제되어
    사본에만 남아도 같다). 로더가 거부하기 때문이다. 시끄러운 실패이므로 받아들인다.
-   **승인값이 바뀌어도 production에는 반영되지 않는다.** `default.yaml`의 기존 키
    값이 바뀌면 사본은 옛 값을 가진 채 정상 기동한다. 조용한 실패다.
-   그래서 **업데이트할 때마다 `default.yaml`과 사본을 diff 한다.** 기대하는 차이는
    사용량 한도 두 줄뿐이다. 그 밖의 차이가 나오면 새 `default.yaml`을 다시 복사하고
    두 줄만 다시 고친다.

### 운영자가 알아야 하는 동작

-   **config는 프로세스가 시작한 뒤 한 번 읽고 다시 읽지 않는다.** 한도를 바꾸면
    **worker를 재시작해야** 반영된다. 두 한도를 쓰는 것은 worker뿐이므로 한도만
    바꿨다면 worker 재시작으로 충분하다. API도 같은 파일을 한 번 읽으므로, diff에서
    다른 차이가 나와 사본을 다시 만든 경우는 API와 worker를 둘 다 재시작한다.
-   **하루는 UTC 기준이라 한도는 한국시간 오전 9시에 리셋된다.** 한도에 걸려 생성이
    멈추면 한국시간 자정이 아니라 그다음 오전 9시에 다시 돈다. 멈춘 동안에도 학습
    세션은 Ready Pool로 계속된다. 판정 규칙은 `09_BACKGROUND_JOBS.md`의
    `usage 기록과 일 경계`가 canonical이다.
-   **두 키를 모두 설정한다.** 하나만 설정하면 나머지는 꺼진 한도이고, 실제 키로 도는
    worker는 기동할 때마다 `cost.guard_disabled` 경고를 남긴다. 그 경고가 늘 뜨는
    상태를 정상으로 두면 정말로 한도가 꺼진 배포를 구분할 수 없게 된다.
-   `daily_token_limit`을 켜면 그날 token 수를 모르는 호출이 하나라도 있을 때 생성이
    멈춘다(위 fail-closed). 멈춤 로그의 token이 `null`인 job 수로 한도 도달과
    구분한다.
-   0이나 음수는 한도를 끄는 값이 아니며 생성을 영구히 멈춘다(위 `알려진 공백`).
