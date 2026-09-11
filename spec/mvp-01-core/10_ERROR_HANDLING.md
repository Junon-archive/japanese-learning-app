# Error Handling

-   LLM 실패가 학습 세션을 즉시 막지 않도록 Ready Pool 사용.
-   invalid content는 Ready 상태 금지.
-   Empty Pool이면 안전한 기존 review/original 재사용 → 짧은 안내 →
    replenishment. 무한 spinner 금지.
-   DB 저장 실패를 성공처럼 표시하지 않는다.
-   Demo는 가능하면 static fixture로 backend/LLM 장애와 독립.
