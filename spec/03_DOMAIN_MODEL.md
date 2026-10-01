# Domain Model

## Language

학습 대상 언어다. MVP 값은 `ja | en` 둘이며 **콘텐츠 엔티티의 축**이다
(`docs/decisions/ADR-023-multilingual-content-model.md`).

``` text
언어를 갖는 것      LearningItem, Sentence, StudySession, PromptVersion, GenerationJob
언어를 갖지 않는 것  UserMastery, ReviewState, UserItemLearningState, ItemExposure,
                    Candidate, Presentation, LearningEvent
```

사용자별 학습 상태에 언어를 **저장하지 않는다.** `learning_item_id`(또는 `sentence_id`)가 이미
언어를 결정하므로 같은 값을 두 곳에 두면 갈라진다. 사용자는 한 명이고 두 언어를 다 쓴다.

**학습 알고리즘은 언어를 모른다.** FSRS scheduling, mastery EMA, probe 정책, context stage
ladder, meaningful exposure, category mix는 전부 item과 sentence만 안다. 언어가 바뀌어도 이
로직은 복제되지 않는다(원칙 12).

언어별로 갈리는 것은 셋뿐이다.

``` text
콘텐츠            seed, 생성 prompt, 설명 내용
표시 보조         후리가나·가나 학습은 일본어 전용. 소리 재생은 영어 전용
정규화·길이 상한   normalized_hash 규칙, max_sentence_length_chars
```

## LearningItem

MVP type: `word | grammar | expression`. `気が乗らない` 같은 표현을
무리하게 token 단위로 쪼개지 않는다. 영어도 같다 --- `put up with`, `you good?`을 단어로
쪼개지 않는다. **type에 언어별 값을 더하지 않는다**(`spec/mvp-03-english/01_ENGLISH_CONTENT.md`).

`language`를 가진다. 영어 item의 `reading`은 NULL이다 --- 영어에 발음 표기를 하지 않는다.

## Surface / Lemma

`任せた / 任せといて / 任せてもらった → 任せる`. surface와 canonical
form을 분리한다.

## Sentence / SentenceItem / Span

Sentence는 **global content entity**다. 사용자별
`new/review/exploration` role을 sentence 자체에 저장하지 않는다. 같은
문장이 시점에 따라 다른 목적으로 재사용될 수 있기 때문이다.

Sentence는 `language`와 원문 `text`를 가진다. 원문 컬럼 이름은 언어 중립이다 --- MVP-03에서
`japanese`를 `text`로 리네임했다(ADR-023 결정 2). 번역은 두 언어 모두 한국어이므로
`korean_translation`이라는 이름을 유지한다.

SentenceItem은 `sentence ↔ LearningItem`의 **언어적 annotation**이다.

Span은 `sentence_item_spans` child entity로 표현하며 offset 기준은
**Unicode code point index**다. 불연속·활용형 표현을 여러 span으로
표현할 수 있다.

## Contextual Explanation

`learning_items.default_meaning`(canonical 의미)과
`sentence_item_explanations.meaning_in_context`(이 문장에서의 의미)를
분리한다. UI가 tap 시 보여주는 것은 후자를 포함한 precomputed
설명이다.

## UserMastery

MVP: `comprehension_mastery`, `listening_mastery`. 둘 다 nullable float
`[0.0, 1.0]`이며 `NULL`은 "능력 0"이 아니라 **"아직 측정하지 않음"**을
뜻한다. `listening_mastery`는 항상 NULL이고 갱신하지 않는다 --- MVP-03에서 영어 문장의 소리
재생이 생겼지만 **재생은 학습 신호가 아니다**(불변식 25). 들었는지, 알아들었는지 아무것도
모른다. Future: `production_mastery`.

## LearningEvent

immutable raw history. MVP event type:

``` text
session_started, sentence_viewed, sentence_completed,
item_clicked, explanation_revealed, translation_revealed,
self_report_known, self_report_uncertain, self_report_unknown,
mastery_probe_shown, mastery_probe_known, mastery_probe_uncertain,
mastery_probe_unknown, mastery_probe_skipped,
content_flagged, session_extended, session_finished
```

알고리즘 변경 시 replay 가능해야 하므로 event는 수정하지 않으며,
derived state(`user_mastery`, `review_states`)에는 계산에 사용된
algorithm/params version을 함께 기록한다.

## ItemExposure

meaningful exposure의 canonical source. 한 presentation의 같은 item은
최대 1 exposure다. denormalized counter는 cache일 뿐이다.

## UserItemLearningState

anchor sentence, context_stage, passive no-signal count, probe 상태 등
사용자별 학습 진행 상태.

## ReviewState

FSRS state + scheduling. mastery score와 **별도**로 저장한다.
`deferred_until`은 무신호 passive review의 단기 재노출 방지용이며 FSRS
memory state가 아니다.

## Candidate / Presentation

`user_sentence_candidates`는 "이 사용자에게 지금 어떤 목적으로 보여줄
문장인가"를, `study_presentations`는 "실제로 무엇을 보여줬는가"를
기록한다. Ready Pool은 candidate의 `status = ready` 집합이다.

## StudySession

한 번의 학습 세션. 기본 목표 12분, +5분 연장 가능. 인증 세션과 구분하기
위해 이름은 `study_sessions`를 사용한다.

**한 세션은 한 언어다**(불변식 22). 세션이 시작될 때 언어가 정해지고 Ready Pool·mix·backlog가
그 언어 범위 안에서 계산된다. 다른 언어로 바꾸려면 지금 세션을 끝낸다
(`mvp-01-core/05_API_SPEC.md`의 `세션 언어와 409`).

## Provenance

source_type/source_id/model/prompt_version/generated_at/parent_sentence_id/
generation_job_id 등.

## Future

`LearningItem → Sense`, richer register/difficulty/audio metadata,
production mastery로 migration 가능해야 한다. MVP에서는 구현하지 않고
확장 여지만 남긴다.
