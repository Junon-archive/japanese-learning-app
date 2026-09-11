# UI / UX Specification

## Reference

Visual reference: `spec/reference/ui/core-learning-mockup.html`

기능·상태 규칙은 본 문서가 목업보다 우선한다. 목업은 레이아웃과 인터랙션
방향을 보여주는 reference이며 pixel-perfect 구현 요구사항이 아니다.

## Main Study Screen

필수 요소: - 오늘의 학습 / 약 12분 - 현재 Sentence - tappable
LearningItem spans - translation reveal - 다음 문장 - 설명 panel/sheet -
session progress - 필요 시 mastery probe

모바일이 주 사용 환경이므로 한 손 조작과 짧은 세션을 우선한다.

## Sentence

-   일본어를 가장 먼저 보여준다.
-   한자 위에 항상 furigana를 표시하지 않는다.
-   학습 대상 span은 지나치게 시험 문제처럼 보이지 않게 subtle하게
    표시한다.
-   한 문장에 신규 item은 권장 1개, 최대 2개.

## Item Explanation

클릭 즉시 cached/precomputed 설명을 표시한다. 일반적인 클릭마다 LLM을
실시간 호출하지 않는다.

기본 정보: - canonical expression - reading - item type - 핵심 한국어
의미 1\~2개 - 현재 문맥에서의 의미 - 짧은 usage nuance - 예문 1개

하단 self-report: - 알고 있었음 - 애매함 - 몰랐음

입력은 강제하지 않는다.

## Translation

기본 hidden. `문장 뜻 보기`를 눌렀을 때 한국어 번역을 표시한다.

## Mastery Probe

앱이 간헐적으로 특정 표현의 이해도를 확인한다. 사용자는 건너뛸 수 있어야
한다. Probe는 세션의 중심 UI가 되어서는 안 된다.

## Session End

약 12분에 도달하면 자연스럽게 완료 상태를 제안한다.

-   `오늘 학습 완료`
-   `+5분 더 하기`

과도한 streak punishment, overdue debt 압박을 사용하지 않는다.

## Public Demo

Demo임을 명확히 알리되 핵심 학습 UI는 실제 Private mode와 최대한
동일하게 보여준다.
