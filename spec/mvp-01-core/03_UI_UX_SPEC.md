# UI/UX Specification

Reference: `spec/reference/ui/core-learning-mockup.html`. 기능/상태
명세가 목업보다 우선한다.

## Study Screen

오늘 약 12분, sentence, tappable item, translation reveal, next,
explanation panel/sheet, progress, occasional probe.

모바일이 주 사용 환경이므로 한 손 조작과 짧은 세션을 우선한다.

MVP Study Screen에는 **audio/듣기 control이 없다**(`00_SCOPE.md`).
Reference mockup의 🔊 버튼은 Future 표시이며 MVP interactive element가
아니다.

## Explanation

cached/precomputed. canonical expression, reading, type, 핵심 뜻 1\~2개,
현재 문맥 뜻, 짧은 nuance, 예문 1개. 하단 self-report는 선택적.

tap 즉시 표시하며 **live LLM을 호출하지 않는다.** 설명이 없는 item이
포함된 문장은 애초에 Ready Pool에 들어가지 않는다(`08_LLM_SPEC.md`).

학습 대상 span은 지나치게 시험 문제처럼 보이지 않게 subtle하게 표시한다.
한 문장에 신규 item은 권장 1개, 최대 2개.

## Mastery Probe

MVP probe UI는 하나로 고정한다. 객관식 의미 문제는 구현하지 않는다.

``` text
이 표현을 알고 계세요?
알고 있었음 / 애매함 / 몰랐음 / 건너뛰기
```

사용자는 언제나 건너뛸 수 있어야 하며 probe는 세션의 중심 UI가 되어서는
안 된다. 상세 정책은 `02_LEARNING_POLICY.md`를 따른다.

## Translation/Furigana

일본어 먼저. 번역 hidden. furigana 상시 표시 금지, item tap 후 reading
제공.

## Session End

`오늘 학습 완료 / +5분 더`. overdue/streak punishment 금지.

## Demo

Demo임은 알리되 실제 학습 UX와 최대한 동일하게.

Demo는 static frontend fixture로만 동작한다. backend API를 호출하지
않으며 demo 상태는 browser memory/session 수준에서만 유지한다
(`04_SECURITY_AND_DATA.md`).
