# User Flow

`Open → auth → create/resume session → sentence → item tap/translation/probe/next → event → mastery/SRS update → next → ~12분 → 완료 → optional +5분`

## Private Learning

``` text
App Open
→ Authentication check
→ Today session create/resume (idle timeout 초과 시 새 session)
→ Learning Engine이 다음 candidate 선택 → study_presentation 생성
→ Sentence displayed (일본어 먼저)
→ User reads Japanese first
   ├─ item tap → precomputed explanation + reading
   │             └─ optional known/uncertain/unknown feedback
   ├─ translation reveal
   ├─ occasional mastery probe (skip 가능)
   └─ next sentence
→ LearningEvent 저장
→ meaningful exposure 확정 / mastery·review state 갱신
→ next sentence 선택
→ ~12분 도달
→ session complete
→ optional +5분
```

-   self-report는 진행에 필수 아님.
-   no-click을 Known으로 처리하지 않음.
-   번역 기본 hidden.
-   reading은 item 설명에서 reveal.
-   probe는 간헐적이고 skip 가능.
-   MVP에는 audio action이 없다(`00_SCOPE.md`).

## Public Demo

``` text
Visitor opens app
→ Demo mode 즉시 사용 가능 (로그인 없음)
→ static frontend fixture
→ item tap / explanation / probe / contextual review 체험
→ backend API 호출 없음
→ private DB 접근 없음
→ paid LLM call 없음
```

Demo interaction state는 browser memory/session 수준에서만 유지한다.
따라서 private DB 접근과 paid LLM 호출이 **구조적으로 불가능**하다
(`04_SECURITY_AND_DATA.md`).
