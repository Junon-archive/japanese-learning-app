# Error Handling

-   LLM 실패가 학습 세션을 즉시 막지 않도록 Ready Pool 사용.
-   invalid content는 Ready 상태 금지.
-   Empty Pool이면 안전한 기존 review/original 재사용 → 짧은 안내 →
    replenishment. 무한 spinner 금지.
-   DB 저장 실패를 성공처럼 표시하지 않는다.
-   Demo는 **static frontend fixture이므로** backend/LLM 장애와 구조적으로
    독립이다. MVP-02에서 선택 홈과 가나 학습도 같다(아래 `Public Demo`).

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

MVP-02에서 이 범위가 **공개 화면 셋(선택 홈, Demo, 가나 학습)**으로 넓어졌다. 세 화면은 서버
요청을 하지 않으므로(불변식 13) API 서버가 꺼져 있어도 정상 동작한다.

-   **로그인 상태를 자동으로 확인하지 않으므로** 공개 화면을 여는 것만으로는 API 장애가 드러나지
    않는다. 장애를 보는 것은 상단바 `로그인`을 누른 경우뿐이며, 그때도 그 자리에 인라인 안내와
    `다시 시도하기`만 띄우고(403 출처 거부면 버튼 없이 출처 거부 문구만) 공개 화면은 계속 쓸 수 있다
    (`03_UI_UX_SPEC.md`의 `상단바`·`로그인 진입`).
-   **localStorage를 쓸 수 없어도**(차단, 용량 초과, 읽기·쓰기 예외) 세 화면과 후리가나 토글은
    메모리만으로 정상 동작한다. 저장된 값의 형식이 맞지 않으면 오류를 띄우지 않고 조용히
    처음부터 시작한다(`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)`).
-   demo fixture를 불러오지 못하면(동적 import 실패) demo 화면에 인라인 안내를 띄운다. 선택 홈과
    가나 학습은 영향을 받지 않는다(`03_UI_UX_SPEC.md`의 `Demo`). 가나 학습 route도 같다.
-   상단바 `로그인`을 눌렀을 때 로그인 영역 코드를 불러오지 못하면(청크 적재 실패, 오프라인, 배포로 옛 청크가
    사라짐) 선택 홈 자리에 인라인 안내 "로그인 화면을 불러오지 못했어요. 위의 로그인을 다시 눌러 주세요."만
    띄운다. 재시도 버튼은 두지 않는다(`openLogin` 호출 위치는 상단바 `로그인` 버튼 한 곳). 새로고침하면 새 청크를 받는다
    (`03_UI_UX_SPEC.md`의 `로그인 진입`).

## 후리가나 계산 실패 (MVP-02)

후리가나(ruby) 계산은 표시 보조다. **계산이 실패해도 문장 채택(Ready)을 막지 않는다.** 위
`Invalid Generated Content`의 validation 실패와 다르다. 실패한 문장은 ruby 없이 표시되고
(`03_UI_UX_SPEC.md`의 `Translation/Furigana`), 실패는 관측한다(`11_OBSERVABILITY.md`의
`MVP-02 추가: 후리가나 계산 결과`).

실패는 두 종류이고 처리가 다르다.

``` text
문장 하나의 계산 예외   sentences.ruby_json = NULL로 두고 문장은 정상 저장·validated
                        (예상 밖 입력, 계산 결과가 검증을 통과하지 못함 등)
                        로그 ruby.failed. backfill의 기본 대상(ruby_json IS NULL)이라 다음 실행이 다시 시도한다
                        seed 적재는 계속하고, backfill은 성공분을 쓴 뒤 쓸 행 수와 무관하게 exit 2로 끝난다
분석기 부재             분석기 import나 사전 적재가 실패한다
                        worker 진입점이 부팅에서 분석기를 적재하고 실패를 잡지 않는다 -> worker가 뜨지 않는다
                        seed 명령과 backfill 명령도 시작에서 실패한다
```

-   **둘을 가르는 이유:** "계산 실패는 Ready를 막지 않는다"는 문장 단위 표시 보조의 실패를 말한다. 분석기가
    이미지에 없는 것은 **배포 결함**이고, 그것을 문장마다 NULL로 흡수하면 worker가 오랫동안 후리가나 없는
    문장만 쌓아도 드러나지 않는다. worker가 뜨지 않는 동안 학습 세션은 Ready Pool로 계속된다
    (`08_LLM_SPEC.md`의 `검증 뒤 후리가나(ruby) 계산 (MVP-02 확정)`).
-   **demo fixture 생성에서 문장 하나의 계산 예외**는 그 문장을 ruby `[]`로 포함하고 `ruby_failed` 줄로 보고한 뒤
    exit 0으로 끝난다(`03_UI_UX_SPEC.md`의 `Demo`의 `fixture`, Wave 3 보완 결정, 2026-09-13).
-   **저장값이 표시 시점 검증을 통과하지 못하면** API는 그 문장의 모든 segment에 빈 ruby를 싣고 로그
    `ruby.invalid_stored`를 남긴다. 500을 내지 않는다(`05_API_SPEC.md`의 `render_segments[].ruby` R6).
-   되돌림은 `UPDATE sentences SET ruby_json = NULL`이다(`04_DB_SPEC.md`의
    `MVP-02: additive migration과 후리가나 backfill`).
