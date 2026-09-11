# Error Handling

## 사용자 경험 원칙

백엔드/LLM 오류가 학습 세션을 즉시 중단시키지 않도록 한다.

## LLM Failure

-   실시간 학습 경로는 Ready Pool을 우선 사용한다.
-   background generation 실패 시 기존 콘텐츠를 계속 사용한다.
-   retry 횟수 제한.
-   사용자에게 내부 provider 오류 세부정보를 노출하지 않는다.

## Invalid Generated Content

코드 validation 실패 시 해당 콘텐츠를 Ready 상태로 만들지 않는다.

## Empty Pool

Ready Pool이 고갈되면: 1. 기존 안전한 review/original content 재사용 2.
사용자에게 짧은 오류 안내 3. background generation 요청 무한 spinner를
보여주지 않는다.

## DB Failure

event 저장 실패 시 사용자에게 데이터가 저장되었다고 거짓 표시하지
않는다. 핵심 transaction 경계를 명확히 한다.

## Public Demo

Demo는 backend/LLM 장애에도 가능한 한 static fixture로 동작한다.
