# MVP-01 Scope

## In Scope

Public Demo/Private mode, 개인 로그인, 12분 세션, Sentence feed,
LearningItem click, 설명/reading, 번역 reveal, 선택적
알고있음/애매함/몰랐음, active mastery probe, comprehension/listening
mastery, FSRS, 5+ meaningful exposure, contextual review, 70/20/10, 신규
권장1/최대2, LLM batch generation, background jobs, LearningEvent, 기본
history, content flagging, PWA, deterministic content validation.

추가로 In Scope: static frontend demo fixture, starter seed data,
content flag 시 quarantine 동작, `/api/health`.

`comprehension/listening mastery`는 **2축 데이터 모델**을 뜻한다.
MVP에서 실제로 갱신하는 축은 comprehension 하나다.

## Out of Scope

YouTube, STT/microphone, pronunciation, free AI chat, production
mastery, social/gamification, advanced analytics, complex offline sync,
mandatory LLM judge, JLPT optimization.

**Audio 일체가 MVP-01 범위 밖이다.**

``` text
TTS 없음
audio button 없음
audio API 없음
audio event 없음
listening review 없음
```

따라서 `listening_mastery`는 nullable 컬럼으로 존재하되 초기값 NULL이며
MVP에서 갱신하지 않는다. NULL은 listening 능력이 0이라는 뜻이 아니라
아직 측정하지 않았다는 뜻이다(`spec/future/LISTENING.md`).

`ANALYZE_SENTENCE` LLM task도 MVP에서 호출자가 없어 범위 밖이다
(`08_LLM_SPEC.md`).
