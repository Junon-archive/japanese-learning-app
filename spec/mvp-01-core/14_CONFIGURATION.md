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
content:
  translation_default_visible: false
  reading_default_visible: false
llm:
  public_demo_generation_enabled: false
  daily_request_limit: configurable
  daily_token_limit: configurable
```

초기 승인값이지 영구적인 학습 법칙이 아니다.
