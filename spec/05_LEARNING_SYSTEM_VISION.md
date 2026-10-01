# Learning System Vision

이 문서는 **장기 방향**을 기술한다. MVP 구현 범위를 넓히지 않는다.
구체 실험 수치는 `spec/future/EXPERIMENTAL_PARAMETERS.md`로 옮겼다.

## Comprehensible Input

대부분 이해 가능한 input에 소량의 novelty를 섞는다.

구체 난이도 밴드 수치는 `spec/future/EXPERIMENTAL_PARAMETERS.md`에 있으며
non-binding experimental starting point다. MVP에서는 문장당 신규 1\~2개
규칙이 우선한다.

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

**MVP-03 주석: 분석기는 일본어 전용이다.** 영어용 분석기·lemmatizer는 도입하지 않았고 범위
밖이다(`spec/mvp-03-english/00_SCOPE.md`). 영어 item의 `canonical_form`은 seed가 사람 손으로
적은 값이며, span 검증은 두 언어 모두 code point index 비교다.

## Polysemy

필요 시 `LearningItem → Sense`로 확장한다.

## Register

casual/neutral/polite/formal/written/internet/slang/regional/generational
metadata를 고려한다. 일부 표현은 `active_use_recommended`와
`recognize_only`로 구분한다.

## Explanation Progression

초기 Korean → easy target language + Korean support → target-language-first/only로 발전 가능.

**MVP-03 주석: 두 언어 모두 설명·번역이 한국어다.** 영어를 쉬운 영어로 설명하는 것은 이 절의
Future 항목 그대로이며 MVP-03에서 열지 않았다(ADR-023 결정 6).

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

기본 12분. 바쁜 날에도 habit continuity를 지원한다. streak 벌점 대신
최근 30일 활동/주간 학습시간/meaningful exposure 같은 지표를 선호한다.

Busy/Deadline 모드의 구체 시간값은
`spec/future/EXPERIMENTAL_PARAMETERS.md`에 있으며 MVP 범위가 아니다.

## Real Language Input

LLM은 유일한 source가 아니다. 실제 발화 source 비율을 장기적으로 높인다.

**MVP-03 주석:** 영어 seed의 표현 선별은 공개 코퍼스 기반 목록(자막 코퍼스 빈도, 구어 구문
표현 목록)에서 왔다. 문장 자체는 LLM 생성이지만 **무엇을 가르칠지는 실제 코퍼스가 정했다.**
이 절이 말하는 방향의 첫걸음이다(ADR-024).

구체 mix 비율은 `spec/future/EXPERIMENTAL_PARAMETERS.md`와
`spec/future/CONTENT_SYSTEM.md`에 있으며 확정값이 아니다.

## Listening

TTS는 보조. 최종 목표는 spontaneous real speech.

MVP-01·MVP-02에는 audio가 전혀 없었다. **MVP-03에서 영어 문장·예문의 재생 하나만 열렸다** ---
브라우저 내장 `speechSynthesis`의 로컬 음성이고, **학습 신호가 아니다**(불변식 24·25,
ADR-025 결정 4). 듣기 probe, `listening_mastery` 갱신, 듣기 전용 복습, 서버 TTS는 모두 그대로
Future다(`spec/future/LISTENING.md`).

합성 음성은 실제 원어민 발화가 아니므로 축약·연음 같은 실제 구어 현상이 약하게 나타난다.
이 절의 "TTS는 보조"가 그 한계를 이미 말하고 있다.

## MVP 경계

이 문서의 다음 항목은 **모두 Future이며 MVP 구현 지시가 아니다.**

-   multidimensional difficulty scorer
-   morphological analyzer 도입
    (주석, MVP-02: 콘텐츠 적재·생성 시점의 후리가나 계산 용도로만 도입했다(ADR-021). 나머지 용도는
    여전히 Future다. MVP-03: 일본어 콘텐츠 전용이며 영어용 분석기는 도입하지 않았다)
-   `LearningItem → Sense` 확장
-   register metadata와 active-use/recognize-only 구분
-   explanation language progression
-   정교한 topic budget
-   Busy/Deadline mode
-   listening/audio 일체
    (주석, MVP-03: 영어 문장·예문의 **재생** 하나만 해제되었다. 듣기 평가·probe·mastery 갱신·
    서버 TTS는 여전히 Future다)

MVP가 실제로 하는 범위는 `spec/mvp-01-core/` + `spec/mvp-02-onboarding/` +
`spec/mvp-03-english/`를 따른다. 이 문서에 숫자나 아이디어가 있다는 이유만으로 구현하지 않는다.
