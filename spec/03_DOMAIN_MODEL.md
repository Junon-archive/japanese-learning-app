# Domain Model

## User

실제 학습 사용자. MVP에서는 실사용자는 1명이어도 모든 사용자 종속
테이블에 `user_id`를 둔다.

## LearningItem

사용자가 학습할 수 있는 언어 단위.

MVP type: - `word` - `grammar` - `expression`

필수 개념: - canonical form / lemma - surface form - reading - 핵심
의미 - item type

활용형은 가능한 한 canonical item에 연결한다. 예: `任せた`, `任せといて`
→ `任せる`.

## Sentence

사용자에게 보여주는 일본어 문장. 번역, 난이도 정보, source/provenance,
생성 메타데이터를 가질 수 있다.

## SentenceItem

Sentence 안의 어느 span이 어떤 LearningItem에 대응하는지 연결한다.

## UserMastery

사용자별 LearningItem의 현재 추정 상태.

MVP 축: - `comprehension_mastery` - `listening_mastery`

Future: - `production_mastery`

Mastery는 단순 Known/Unknown boolean이 아니다.

## LearningEvent

사용자 행동의 immutable raw history.

예: - sentence_viewed - item_clicked - explanation_revealed -
self_report_known - self_report_uncertain - self_report_unknown -
mastery_probe_answered - translation_revealed - audio_played -
review_result - session_finished

Mastery 알고리즘이 바뀌더라도 과거 event를 replay할 수 있도록 원본
기록을 보존한다.

## ReviewState

LearningItem의 FSRS scheduling 상태와 meaningful exposure count를
저장한다.

## Session

한 번의 학습 세션. 기본 목표는 12분이며 실제 duration과 학습 event를
연결한다.

## ContentSource / Provenance

콘텐츠의 출처와 생성 족보.

예: - source_type - source_id - model/provider - prompt_version -
generated_at - parent_sentence_id

## GenerationJob

백그라운드 LLM 작업의 상태.

상태 예: `queued → running → validated → completed` 실패 시
`retry → failed/dead-letter`.
