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
  # null = limit disabled. production에서 필요 시 integer를 설정한다.
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

`reading_default_visible`은 항상 `false`를 유지한다. furigana 상시 표시
금지는 UI 규칙이며(`03_UI_UX_SPEC.md`) 이 키는 reading reveal 기본
상태를 뜻한다.

`content.translation_default_visible`과 `content.reading_default_visible`을
**frontend가 읽는 경로는 없다.** 두 값이 기술하는 것은 API 구조가 이미 강제하고
있다 --- presentation payload에는 `korean_translation` 필드도 reading 필드도
존재하지 않으므로(`05_API_SPEC.md`의 `Sentence Presentation Payload`,
`Interaction`) 번역과 reading은 각각 `/translation/reveal`과 `/click`을 거쳐야만
나온다. 따라서 **이 두 키를 `true`로 뒤집어도 화면은 달라지지 않는다.** 값을 넘길
endpoint를 만들면 숨김 규칙의 source of truth가 둘이 되고, 그중 하나가 뒤집히는
사고가 가능해진다. 두 키는 "기본 노출 상태는 hidden이다"라는 정책 기록으로만
남기고 소비처를 만들지 않는다.

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

`daily_token_limit`이 integer일 때, 그날 token 총량을 **모르는** job이 하나라도
있으면 한도는 도달한 것으로 본다(fail-closed). 이는 `null = limit disabled`와
모순되지 않는다 --- `null`은 판정 자체를 하지 않는다는 뜻이고 fail-closed는
한도를 **켜 둔** 경우에만 적용된다. `daily_request_limit`은 영향받지 않는다.
근거와 판정식은 `09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`가 canonical이다.

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
