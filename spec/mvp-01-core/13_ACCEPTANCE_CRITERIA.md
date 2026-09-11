# Acceptance Criteria

-   모바일에서 세션 시작/진행/종료 가능
-   item tap 설명 즉시 표시
-   reading 표시, 번역 reveal
-   self-report 선택적, probe skip 가능
-   no-click Known 처리 금지
-   mastery 2축 존재 (comprehension은 갱신, listening은 nullable로 보존)
-   FSRS + meaningful exposure가 **독립적으로** 동작
-   configured minimum meaningful exposure 정책 지원
-   configured max new items per sentence 정책 지원
-   **configured category mix를 Learning Engine이 따른다**
-   **configured probe budget과 cooldown을 따른다**
-   무신호 review가 무한 due loop를 만들지 않음 (click이나 probe skip만
    있는 review도 무신호로 처리된다)
-   **configured probe 간격을 지켜 probe가 연속으로 몰리지 않음**
-   세션 시작이 seed 콘텐츠로 Ready Pool을 만들어, background worker 없이
    첫 세션이 성립함
-   presentation 제시 / 완료 / probe 제시가 재시도로 중복 기록되지 않음
-   contextual progression을 DB에서 재현 가능
-   item explanation을 DB에서 조회 가능
-   tap마다 live LLM 불필요
-   모든 provider 호출이 worker에서만 발생
-   background batch generation/validation/Ready Pool 동작
-   flag된 content가 다시 Ready로 선택되지 않음
-   신규 사용자가 seed 기반으로 첫 세션을 시작 가능
-   **Demo는 backend/DB/LLM과 구조적으로 분리** (paid LLM 0, private data
    접근 0)
-   DB migration 재현 가능
-   Postgres 직접 인터넷 노출 없음
-   secret frontend/Git 노출 없음
-   명세 하한 미만 password로는 계정을 만들 수 없음
-   restart 후 state 유지
-   retry 무한루프 없음 (max attempts + dead-letter)
-   backup/restore 최소 1회 검증

## 수치 취급 원칙

Acceptance Criteria에 실험 수치를 직접 박지 않는다. 검증하는 것은 "엔진이
configured 값을 따르는가"이지 특정 숫자가 아니다.

다만 다음은 현재 제품 핵심으로 승인된 값이며
`14_CONFIGURATION.md`의 **기본값**으로 유지한다.

``` text
max_new_items_per_sentence   = 2
minimum_meaningful_exposures = 5
default_session_minutes      = 12
```

기술 검증 후 실제 2\~4주 사용하여 지속 사용성, 설명 마찰, 자연스러움,
contextual SRS 효과, 12분 적합성을 평가한다. 이 결과가 MVP-02 또는 정책
수정의 근거가 된다.
