# Security and Data

## Modes

-   Anonymous: Public Demo only, private mastery/history 접근 금지, paid
    LLM call 금지.
-   Authenticated: 실제 학습 시스템.

## Public Demo 구조 (MVP 확정)

Public Demo는 **완전한 static frontend fixture**다.

``` text
backend API 호출 없음
PostgreSQL write 없음
anonymous user row 없음
generation job 없음
provider client 없음
private user data 접근 가능 경로 없음
```

Demo interaction state는 browser memory/session 수준에서만 유지한다.
따라서 `sessions.mode = demo`, demo user, demo DB state 같은 설계는
사용하지 않는다.

이 구조로 다음이 성립한다.

``` text
Paid LLM call      = structurally impossible
Private DB access  = structurally impossible
```

## Security

-   단순하고 안전한 개인 로그인. password 평문 저장 금지.
-   secure/httpOnly cookie session 또는 동등한 방식.
-   OpenAI key와 DB credential은 server-side secret.
-   PWA bundle에 secret 금지.
-   FastAPI는 Tunnel로 공개, PostgreSQL은 외부 직접 노출 금지.

## Authentication (MVP 확정)

이 앱은 SaaS가 아니다.

-   public signup 없음.
-   private real user 한 명.
-   계정은 seed/admin CLI 또는 초기 setup 절차로 생성한다.
-   password는 **Argon2id 등 안전한 password hash**로 저장한다.
-   auth session은 `auth_sessions` 테이블에 저장한다(학습 세션
    `study_sessions`와 이름을 구분한다).
-   opaque random session token의 **hash만** DB에 저장한다.
-   cookie는 `Secure` + `HttpOnly`.
-   정확한 cookie expiry는 config.

### 배포 도메인 가정

``` text
frontend: jp.example.com
api:      api.jp.example.com
```

처럼 **동일 registrable domain** 아래에서 운영한다.

-   Frontend fetch는 `credentials: include`를 사용한다.
-   API CORS는 명시된 frontend origin만 허용한다. **wildcard 금지.**
-   state-changing request는 SameSite cookie policy, strict Origin
    검증, 필요한 CSRF 방어를 적용한다.

## 데이터 보존

PostgreSQL이 canonical source이다. DB 내부 파일을 직접 편집하지 않는다.

## Backup

정기 pg_dump + rotation + 가능하면 다른 물리 디스크/위치에 최소 1개.
restore 절차도 실제 검증한다.

## Git 제외

-   `.env`
-   DB volume
-   DB backup
-   실제 secret
-   사용자 개인 export

## Portability

장기적으로 vocabulary.csv, learning_history.json, sentences.json export
지원.
