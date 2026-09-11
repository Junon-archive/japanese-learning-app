# Domain Model

## LearningItem

MVP type: `word | grammar | expression`. `気が乗らない` 같은 표현을
무리하게 token 단위로 쪼개지 않는다.

## Surface / Lemma

`任せた / 任せといて / 任せてもらった → 任せる`. surface와 canonical
form을 분리한다.

## Sentence / SentenceItem

문장과 문장 내 LearningItem span을 분리 저장한다.

## UserMastery

MVP: `comprehension_mastery`, `listening_mastery`. Future:
`production_mastery`.

## LearningEvent

immutable raw history: sentence_viewed, item_clicked,
explanation_revealed, self-report, probe, translation, audio, review,
session_finished 등. 알고리즘 변경 시 replay 가능해야 한다.

## ReviewState

FSRS state + meaningful exposure count.

## Provenance

source_type/source_id/model/prompt_version/generated_at/parent_sentence
등.

## Future

`LearningItem → Sense`, richer register/difficulty/audio metadata로
migration 가능해야 한다.
