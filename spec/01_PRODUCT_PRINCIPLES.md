# Product Principles

## 1. Sentence First

전통적인 `단어 → 뜻 → 예문`이 아니라
`문장 → 문맥 속 표현 → 설명 → 반복 노출` 순서로 학습한다.

## 2. Friction Minimization

사용자가 과목, 챕터, 난이도, 신규 단어 수, 복습 계획을 매일 관리하지
않는다. 앱을 열면 바로 학습이 시작되어야 한다.

## 3. Learning Engine Decides, LLM Generates

Learning Engine이 무엇을 언제 학습할지 결정한다. LLM은 자연스러운 일본어
콘텐츠 생성·설명·변형을 담당한다.

## 4. DB Is the Source of Truth

사용자의 mastery, event, SRS state, 콘텐츠 provenance는 PostgreSQL에
저장한다. LLM의 대화 기록에 사용자 상태를 의존하지 않는다.

## 5. Clicked ≠ Unknown, Not Clicked ≠ Known

표현 클릭은 강한 학습 신호지만, 클릭하지 않았다고 그 표현을 안다고
판단하지 않는다. 사용자는 모르는 사실 자체를 인지하지 못할 수 있으므로
앱이 가끔 mastery probe를 수행한다.

## 6. Contextual Repetition

동일한 flashcard만 반복하지 않는다. 초기에는 원문/유사 문맥으로 기억의
anchor를 만들고 이후 다양한 문맥으로 transfer한다.

## 7. Minimum Meaningful Exposure

학습 표현은 알고 있다고 응답하더라도 최소 5회의 의미 있는 노출을
보장한다. 5회 이후에도 FSRS가 필요하다고 판단하면 계속 복습한다.

## 8. Real Japanese over Textbook Japanese

일상 회화, 자연스러운 구어체, 실제 사용 register를 우선한다. 개인
관심사는 동기 부여에 활용하되 콘텐츠 전체를 연구/GPU/운동에 과적합시키지
않는다.

## 9. Reveal on Demand

한국어 번역과 reading/furigana는 처음부터 항상 노출하지 않는다. 일본어를
먼저 시도하고 필요할 때 확인한다.

## 10. Personal App, Public Demo

실제 학습 데이터와 LLM 기능은 인증된 개인 사용자에게 제공한다.
포트폴리오 방문자는 고정된 demo fixture로 핵심 UX를 체험하며 유료 LLM
호출을 발생시키지 않는다.
