# Error Handling

-   LLM 실패가 학습 세션을 즉시 막지 않도록 Ready Pool 사용.
-   invalid content는 Ready 상태 금지.
-   Empty Pool이면 안전한 기존 review/original 재사용 → 짧은 안내 →
    replenishment. 무한 spinner 금지.
-   DB 저장 실패를 성공처럼 표시하지 않는다.
-   Demo는 **static frontend fixture이므로** backend/LLM 장애와 구조적으로
    독립이다.

## 사용자 경험 원칙

백엔드/LLM 오류가 학습 세션을 즉시 중단시키지 않도록 한다. 사용자에게
내부 provider 오류 세부정보를 노출하지 않는다.

## LLM Failure

-   실시간 학습 경로는 Ready Pool을 우선 사용한다.
-   background generation 실패 시 기존 콘텐츠를 계속 사용한다.
-   retry 횟수는 제한한다(`09_BACKGROUND_JOBS.md`).

## Invalid Generated Content

코드 validation 실패 시 해당 콘텐츠를 Ready 상태로 만들지 않는다
(`08_LLM_SPEC.md`의 Deterministic Content Validation).

## Empty Pool

Ready Pool이 고갈되면:

1.  다른 available category 선택
2.  안전한 기존 anchor/near-original reinforcement content 재사용
3.  사용자에게 짧은 오류/안내 표시
4.  background replenishment job enqueue

무한 spinner를 보여주지 않으며, request handler에서 provider를
synchronous 호출하지 않는다.

## DB Failure

event 저장 실패 시 사용자에게 데이터가 저장되었다고 거짓 표시하지
않는다. 핵심 transaction 경계를 명확히 한다.

## Content Flag 동작

사용자가 sentence를 `unnatural`, `wrong` 등으로 flag하면 **즉시**:

``` text
sentence / candidate -> quarantined
```

-   향후 selection 대상에서 제외한다.
-   그 presentation에서 발생한 mastery failure는 **사용자 능력 저하
    evidence로 사용하지 않는다.**
-   이미 생성된 `item_exposures`는 `invalidated_at`을 설정하여 재계산 시
    제외할 수 있게 한다.

Admin UI는 Future지만 **quarantine 동작 자체는 MVP 필수**다
(`spec/future/ADMIN_AND_DATA.md`).

## Public Demo

Demo는 static fixture이므로 backend/DB/LLM 장애와 무관하게 동작한다
(`04_SECURITY_AND_DATA.md`).
