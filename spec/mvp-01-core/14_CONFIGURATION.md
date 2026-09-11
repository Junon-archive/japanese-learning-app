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
  mastery_probe_target_per_session_min: 2
  mastery_probe_target_per_session_max: 4

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

llm:
  # Public Demo는 static frontend fixture이므로 API/worker를 사용하지
  # 않는다. 이 flag는 구조적 분리에 더한 안전장치이며 true로 바꾸지 않는다.
  public_demo_generation_enabled: false
  # null = limit disabled. production에서 필요 시 integer를 설정한다.
  daily_request_limit: null
  daily_token_limit: null
```

초기 승인값이지 영구적인 학습 법칙이 아니다.

`reading_default_visible`은 항상 `false`를 유지한다. furigana 상시 표시
금지는 UI 규칙이며(`03_UI_UX_SPEC.md`) 이 키는 reading reveal 기본
상태를 뜻한다.

비율 키(`review_ratio`, `new_ratio`, `exploration_ratio`)의 합은 1.0이어야
하며 config 로드 시 검증한다.
