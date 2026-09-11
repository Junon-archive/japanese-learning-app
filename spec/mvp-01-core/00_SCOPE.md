# MVP-01 Scope

## 목적

Core Learning Loop가 실제 개인 학습에서 매일 사용할 만큼 편하고 유용한지
검증한다.

## In Scope

-   Public Demo / Private Learning mode 분리
-   개인 로그인
-   12분 기본 학습 세션
-   Sentence feed
-   LearningItem span 표시 및 클릭
-   표현 설명
-   reading reveal
-   한국어 문장 번역 reveal
-   `알고 있었음 / 애매함 / 몰랐음` 선택적 self-report
-   앱 주도 mastery probe
-   comprehension/listening 2축 mastery 데이터 모델
-   FSRS scheduling
-   최소 5회 meaningful exposure
-   원문 → 유사 문맥 → 새로운 문맥으로 점진적 전환
-   review/new/exploration 70/20/10 초기 정책
-   문장당 신규 item 권장 1개, 최대 2개
-   LLM sentence batch generation
-   LLM explanation/review-context generation
-   PostgreSQL-backed background jobs
-   LearningEvent 기록
-   기본 history
-   content flagging
-   PWA installability
-   코드 기반 content validation

## Out of Scope

-   YouTube ingestion
-   microphone/STT
-   pronunciation scoring
-   free-form AI conversation
-   production mastery
-   social/gamification
-   고급 추천 시스템
-   복잡한 offline learning/sync
-   LLM judge를 이용한 모든 생성물 재검증
-   JLPT 시험 최적화 기능
