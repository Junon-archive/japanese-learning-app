# Product Vision

## 한 줄 정의

사용자의 **대상 언어** 수준을 지속적으로 추정하고, 이해 가능한 문맥을 제공하며, 모르는
단어·문법·표현을 문맥 기반 SRS로 자연스럽게 습득시키는 개인화 언어 학습 앱.

**대상 언어는 일본어와 영어 둘이다**(MVP-03, 사용자 결정 2026-10-01). 학습 방식은 두 언어가
같고, 콘텐츠와 일부 표시 보조만 언어별로 갈린다(`spec/mvp-03-english/00_SCOPE.md`).

## 목표

### 공통

-   해당 언어의 일상 콘텐츠를 상당 부분 이해
-   원어민과 일상 주제로 대화
-   연구가 바쁜 날에도 낮은 마찰로 습관 유지

### 일본어

-   일본어 YouTube의 일상 콘텐츠를 상당 부분 이해
-   일본인과 일상 주제로 대화
-   한자는 handwriting이 아니라 recognition/reading 중심

우선순위: `이해/청해 > 어휘·문법 인식 > 회화 > 읽기 >>> 한자 손글씨`

### 영어

-   미국 드라마와 팟캐스트의 이해도를 높인다
-   원어민과 실시간 대화가 되는 것이 목표다
-   **시험 점수가 목표가 아니다.** TOEFL·IELTS식 고급 어휘가 아니라 "실생활에서 살아남기 위한"
    구어 표현을 다룬다. 아는 단어로 되어 있는데 못 알아듣는 표현(`you good?`, `sort of`,
    `put up with`)이 1순위다

우선순위: `청해/이해 > 구어 표현 인식 > 회화 >>> 읽기 > 시험 어휘`

영어 쪽 콘텐츠 기준은 `spec/mvp-03-english/01_ENGLISH_CONTENT.md`가 canonical이다.

## Core Loop

언어와 무관하게 같다.

`Sentence → 표현 확인 → 설명 → 학습 신호 → SRS → 다른 문맥 재노출`

## 장기 Content Source

LLM-generated / YouTube / Manual text / 기타 실제 발화.

MVP에서 실제로 쓰는 것은 LLM-generated와 version-controlled seed다. 나머지는 Future다
(`spec/future/CONTENT_SYSTEM.md`).
