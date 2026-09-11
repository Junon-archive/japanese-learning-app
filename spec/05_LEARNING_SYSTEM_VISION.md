# Learning System Vision

## Comprehensible Input

개념적 난이도 목표: - Comfort: known 95\~98% - Normal: known 90\~95% -
Challenge: known 80\~90%

고정 법칙이 아니며 MVP의 문장당 신규 1\~2개 규칙이 우선한다.

## Difficulty Is Multidimensional

lexical rarity, grammar complexity, length, omission, colloquiality,
kanji density, inference burden, register familiarity, listening에서는
speech rate/reduction/audio quality 등을 확장 가능하게 본다.

## Sentence Understanding ≠ Item Mastery

문장 전체를 이해했다고 모든 item을 안다고 판단하지 않는다. 반대로 모든
token을 학습시키지도 않는다.

## LearningItem Evolution

MVP word/grammar/expression. Future collocation/idiom/discourse marker
등.

## Morphology

deterministic Japanese morphological analyzer를 기본으로 하고 애매한
경계만 LLM 보정을 고려한다. LLM-only tokenization에 의존하지 않는다.

## Polysemy

필요 시 `LearningItem → Sense`로 확장한다.

## Register

casual/neutral/polite/formal/written/internet/slang/regional/generational
metadata를 고려한다. 일부 표현은 `active_use_recommended`와
`recognize_only`로 구분한다.

## Explanation Progression

초기 Korean → easy Japanese + Korean support →
Japanese-first/Japanese-only로 발전 가능.

## Contextual SRS

FSRS는 WHEN, Learning Engine은 WHAT. 최소 meaningful exposure 5회. 새
문맥 실패는 item 망각뿐 아니라 문장 난이도 때문일 수도 있다.

## Topic Coverage

daily life / friends-conversation / work-research / hobbies / travel /
media-culture / random-general. 개인 관심사는 동기부여에 쓰되 과적합
금지.

## Backlog

review backlog가 늘면 신규 공급을 줄인다.

## Habit

기본 12분. 장기적으로 Busy/Deadline에서는 약 5분 최소 세션으로 습관 유지
가능. streak 벌점 대신 최근 30일 활동/주간 학습시간/meaningful exposure
같은 지표 선호.

## Real Japanese

LLM은 유일한 source가 아니다. 장기 아이디어로 real source 60 / source
transformation 30 / fully generated 10 정도를 실험할 수 있으나 확정값은
아니다.

## Listening

TTS는 보조. 최종 목표는 spontaneous real speech.
