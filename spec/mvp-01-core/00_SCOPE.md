# MVP-01 Scope

**대상 언어:** MVP-01·MVP-02는 일본어 하나였다. **MVP-03에서 영어가 더해졌다**
(`spec/mvp-03-english/00_SCOPE.md`). 이 문서의 규칙은 언어를 가리지 않으며, 언어별로 갈리는
것은 콘텐츠·표시 보조·정규화뿐이다(`spec/03_DOMAIN_MODEL.md`의 `Language`).

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

**Audio 일체가 MVP-01 범위 밖이었다. MVP-03에서 두 줄만 해제된다.**

``` text
TTS 없음              -> MVP-03 해제. 브라우저 내장 speechSynthesis의 localService 음성만
audio button 없음     -> MVP-03 해제. 영어 문장·예문 옆 재생 버튼 (영어 전용)
audio API 없음        그대로. 서버에 audio endpoint가 없고 오디오 파일을 만들지도 저장하지도 않는다
audio event 없음      그대로. 재생은 LearningEvent를 만들지 않는다 (불변식 25)
listening review 없음 그대로. 듣기 probe와 듣기 전용 복습이 없다
```

따라서 `listening_mastery`는 nullable 컬럼으로 존재하되 초기값 NULL이며
MVP에서 갱신하지 않는다. NULL은 listening 능력이 0이라는 뜻이 아니라
아직 측정하지 않았다는 뜻이다(`spec/future/LISTENING.md`). **재생이 생겼다고 이 값을 추정하지
않는다** --- 들었는지, 알아들었는지, 몇 번 돌렸는지 아무것도 모른다. 범위와 근거는
`spec/mvp-03-english/00_SCOPE.md`와 ADR-025 결정 4다.

`pronunciation`(발음 평가·음성 인식) 제외는 그대로다. 재생은 평가가 아니다.

`ANALYZE_SENTENCE` LLM task도 MVP에서 호출자가 없어 범위 밖이다
(`08_LLM_SPEC.md`).
