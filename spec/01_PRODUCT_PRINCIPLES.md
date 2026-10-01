# Product Principles

1.  **Sentence First** --- 단어→뜻→예문이 아니라 문장→문맥 속
    표현→설명→반복.
2.  **Friction Minimization** --- 앱을 열면 바로 학습. 사용자가 매일
    계획/챕터/복습량을 관리하지 않는다.
3.  **Learning Engine Decides, LLM Generates.**
4.  **DB Is Source of Truth.**
5.  **Clicked ≠ Unknown, Not Clicked ≠ Known.**
6.  **Contextual Repetition** --- 초기 anchor 후 다양한 문맥으로
    transfer.
7.  **Minimum Meaningful Exposure = 5+** --- 1\~2번 안다고 했다고
    종료하지 않는다.
8.  **Real/Natural Spoken Language 우선.** 교과서체·시험체가 아니라 실제 발화를 우선한다.
    일본어는 자연스러운 구어 일본어, 영어는 드라마·일상 대화에서 실제로 나오는 구어
    영어다(축약형을 피하지 않는다. `spec/mvp-03-english/01_ENGLISH_CONTENT.md`).
9.  **Reveal on Demand** --- 번역과 reading은 필요할 때.
10. **Personal App + Public Demo** --- 실사용 데이터는 private, 방문자는
    fixture로 체험. 언어마다 demo가 하나씩 있다(`spec/mvp-03-english/00_SCOPE.md`).
    계정은 소유자와 소수의 지인용이며 회원가입은 없다. 계정끼리 학습 기록을 공유하지 않지만
    **LLM 사용량 한도는 공유한다**(`mvp-01-core/04_DB_SPEC.md`의 `계정 수와 공유 범위`).
11. **Non-punitive Habit Design** --- streak/overdue 부채감으로 압박하지
    않는다.
12. **One Engine, Many Languages** --- 학습 알고리즘은 언어를 모른다. 언어는
    콘텐츠의 축이며 엔진·SRS·mastery·이벤트 경로를 복제하지 않는다
    (`docs/decisions/ADR-023-multilingual-content-model.md`).
