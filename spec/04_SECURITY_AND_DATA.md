# Security and Data

## Modes

-   Anonymous: Public Demo only, private mastery/history 접근 금지, paid
    LLM call 금지.
-   Authenticated: 실제 학습 시스템.

## Security

-   단순하고 안전한 개인 로그인. password 평문 저장 금지.
-   secure/httpOnly cookie session 또는 동등한 방식.
-   OpenAI key와 DB credential은 server-side secret.
-   PWA bundle에 secret 금지.
-   FastAPI는 Tunnel로 공개, PostgreSQL은 외부 직접 노출 금지.

## Backup

정기 pg_dump + rotation + 가능하면 다른 물리 디스크/위치에 최소 1개.
restore 절차도 실제 검증한다.

## Portability

장기적으로 vocabulary.csv, learning_history.json, sentences.json export
지원.
