# ADR-004 --- Session Cookie

Status: Accepted

Decision: 인증 session cookie는 `__Host-nc_session`이며 속성은
`HttpOnly; Secure; SameSite=Strict; Path=/`, `Domain` 미지정(host-only),
수명은 환경변수 `AUTH_SESSION_TTL_DAYS`(양의 정수, 기본 30)다. 규격의
canonical 정의는 `spec/04_SECURITY_AND_DATA.md`의
`Session Cookie (MVP 확정)`에 있다.

`spec/04_SECURITY_AND_DATA.md`는 "정확한 cookie expiry는 config"라고만
했고, 그 값이 학습 정책 YAML과 배포 env 중 어디에 속하는지 명세 어디에도
없었다. Wave 1 인증 구현이 여기서 막혔다.

## 수명은 env

`spec/mvp-01-core/14_CONFIGURATION.md`는 **학습 정책** 파일이다. 로더가
전 키를 읽고 category 비율 합까지 검증한다. session 수명은 실사용 후
튜닝하는 학습값이 아니라 바꾸면 보안 표면이 바뀌는 배포 설정이다.
`APP_ENV`를 같은 이유로 이미 env에 뒀으므로 성격이 같은 값을 두 곳에
나누지 않는다.

MVP는 absolute expiry만 쓴다. `auth_sessions.last_used_at`은 기록하되
만료를 연장하지 않는다. 사용자가 한 명이고 재로그인 비용이 낮아
sliding session 로직의 값이 비용보다 작다.

## 이름과 속성은 env가 아니다

-   `Secure`를 끄는 스위치를 만들지 않는다. Chrome/Firefox는
    `http://localhost`를 secure context로 취급해 `Secure` cookie를
    저장·전송한다. `APP_ENV`는 배포 표면 제어 전용이므로 보안 하향
    플래그로 쓰면 그 규칙과 충돌한다.
-   `SameSite=Strict`. 배포는 frontend와 API가 동일 registrable domain
    아래(`jp.example.com` / `api.jp.example.com`)라 앱이 보내는 요청은
    same-site다. Strict에서도 cookie가 실리고 cross-site 요청에는 실리지
    않는다. `None`을 쓸 이유가 없다.
-   `Domain` 미지정(host-only). 지정하면 frontend 정적 호스트에도 cookie가
    전송되어 노출 표면이 넓어진다.
-   `__Host-` prefix는 위 세 결정을 브라우저가 강제하게 만들고, 형제
    subdomain의 동명 cookie 덮어쓰기를 막는다. 비용은 이름 문자열뿐이다.

## 결과

로컬 개발에서 frontend와 API는 같은 host 이름(`localhost`)으로 접근해야
한다. `127.0.0.1`과 `localhost`를 섞으면 서로 다른 site가 되어 cookie가
전송되지 않는다. 해법은 host 이름을 맞추는 것이지 cookie 속성을 낮추는
것이 아니다.
