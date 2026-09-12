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

알려진 한계(MVP에서 고치지 않는다): 사용자별 학습 상태 행을 만드는 경로가
read-or-create(SELECT 후 INSERT)이므로, **같은 item에 `skip`과 self-report가 동시에
도착하면** 한쪽이 `user_item_learning_state` 행을 중복 INSERT하려다 제약 위반으로
**500**을 받을 수 있다. evidence끼리의 동시 요청은
`uq_learning_events_evidence`가 직렬화하지만 skip은 evidence가 아니라 그 상한에
걸리지 않는다(`07_SRS_SPEC.md`의 `노출당 evidence 1건`). **데이터 오염이 아니라
가용성 문제다** --- 제약이 오염을 이미 막으므로 잃는 것은 그 요청 하나이고 사용자는
다시 누르면 된다. 해법 방향은 삽입을 `ON CONFLICT DO NOTHING`으로 바꾸는 것이며
(`services/events.py`가 event 기록에 이미 쓰는 방식), 이 증상이 보고되면 원인을
다시 찾지 않도록 여기 적어 둔다.

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

그래서 `/flag`는 **닫힌 session과 이미 완료된 presentation에서도 받는다.**
exposure는 presentation을 닫을 때 생기므로 위 항목이 참이 되는 순간이 완료
이후뿐이기 때문이다. 다른 상호작용 endpoint는 그 상태에서 409다
(`05_API_SPEC.md`의 `세션·presentation 상태 게이트`가 canonical).

Admin UI는 Future지만 **quarantine 동작 자체는 MVP 필수**다
(`spec/future/ADMIN_AND_DATA.md`).

## Public Demo

Demo는 static fixture이므로 backend/DB/LLM 장애와 무관하게 동작한다
(`04_SECURITY_AND_DATA.md`).
