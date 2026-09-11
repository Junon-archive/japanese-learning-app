# Security and Data

## 접근 모델

### Anonymous / Public Demo

-   회원가입 없이 핵심 UX 체험 가능.
-   고정 demo fixture만 사용.
-   실제 사용자 mastery/history 접근 금지.
-   실시간 유료 LLM 호출 금지.
-   demo state는 브라우저 세션 수준의 임시 상태여도 된다.

### Authenticated Private User

-   실제 Sentence Pool, mastery, SRS, history 사용.
-   LLM generation 허용.
-   개인 학습 데이터 접근 가능.

## 인증

MVP는 복잡한 SaaS 인증을 만들지 않는다. 단순하고 안전한 로그인 세션을
사용한다. 비밀번호는 평문 저장하지 않으며 secure/httpOnly cookie 기반
세션 또는 동등한 안전한 방식을 사용한다.

## Network

-   FastAPI는 Cloudflare Tunnel을 통해 노출한다.
-   PostgreSQL은 외부 인터넷에 직접 노출하지 않는다.
-   DB credential과 OpenAI API key는 서버-side secret으로만 관리한다.
-   API key를 PWA bundle에 포함하지 않는다.

## 데이터 보존

PostgreSQL이 canonical source이다. DB 내부 파일을 직접 편집하지 않는다.

## Backup

-   정기 `pg_dump` 백업.
-   rotation 적용.
-   최소 하나의 백업은 동일 물리 디스크 밖에 보관하는 것을 목표로 한다.
-   restore script와 restore 절차를 문서화하고 검증한다.

## Git 제외

-   `.env`
-   DB volume
-   DB backup
-   실제 secret
-   사용자 개인 export
