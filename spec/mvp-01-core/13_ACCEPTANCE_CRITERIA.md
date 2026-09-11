# Acceptance Criteria

-   모바일에서 세션 시작/진행/종료 가능
-   item tap 설명 즉시 표시
-   reading 표시, 번역 reveal
-   self-report 선택적, probe skip 가능
-   no-click Known 처리 금지
-   mastery 2축 존재
-   FSRS + meaningful exposure + 5회 최소 정책 지원
-   신규 권장1/최대2, 70/20/10 configurable
-   tap마다 live LLM 불필요
-   background batch generation/validation/Ready Pool 동작
-   Demo paid LLM 0, private data 접근 0
-   DB migration 재현 가능
-   Postgres 직접 인터넷 노출 없음
-   secret frontend/Git 노출 없음
-   restart 후 state 유지
-   retry 무한루프 없음
-   backup/restore 최소 1회 검증

기술 검증 후 실제 2\~4주 사용하여 지속 사용성, 설명 마찰, 자연스러움,
contextual SRS 효과, 12분 적합성을 평가한다.
