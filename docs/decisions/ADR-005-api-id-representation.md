# ADR-005 --- API ID Representation

Status: Accepted

Decision: API 응답에 실리는 DB 정수 PK는 **JSON number(정수)** 로 낸다.
문자열로 감싸지 않는다. 예외는 client가 생성하는 `client_event_id`(UUID
문자열) 하나다. canonical 정의는 `spec/mvp-01-core/05_API_SPEC.md`의
`ID 표현`에 있다.

`05_API_SPEC.md`의 초기 예시는 `"si_1"`, `"li_1"` 같은 문자열 placeholder
였지만 실제 PK는 bigint다. Wave 2의 모든 응답 스키마가 이 결정 위에
올라가므로 되돌리기 비싸다.

## 근거

-   문자열로 감싸면 backend 직렬화와 frontend 역직렬화 양쪽에 변환
    지점이 생기고, 같은 값이 `1`과 `"1"`로 갈리는 비교 버그를 만든다.
-   `si_`/`li_` 같은 prefix는 타입 정보를 문자열에 인코딩하는 것이다.
    타입은 필드 이름(`sentence_item_id`, `learning_item_id`)이 이미
    표현한다.
-   외부에 공개되는 SaaS가 아니므로 id 열거(enumeration)를 막기 위한
    불투명 식별자가 필요하지 않다. 모든 학습 endpoint는 인증 뒤에 있고
    사용자는 한 명이다.

## 한계

JavaScript `Number.MAX_SAFE_INTEGER`(2^53-1)를 넘는 id는 정확히 표현되지
않는다. 단일 사용자 개인 앱에서 PK가 이 값에 도달할 계획이 없으므로 MVP는
이 위험을 받아들인다. 도달할 규모가 되면 이 ADR과 `05_API_SPEC.md`를 먼저
고친다.
