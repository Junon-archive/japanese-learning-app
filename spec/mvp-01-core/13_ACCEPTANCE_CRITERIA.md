# Acceptance Criteria

-   모바일에서 세션 시작/진행/종료 가능
-   item tap 설명 즉시 표시
-   reading 표시, 번역 reveal
-   self-report 선택적, probe skip 가능
-   no-click Known 처리 금지
-   mastery 2축 존재 (comprehension은 갱신, listening은 nullable로 보존)
-   FSRS + meaningful exposure가 **독립적으로** 동작
-   configured minimum meaningful exposure 정책 지원
-   configured max new items per sentence 정책 지원
-   **configured category mix를 Learning Engine이 따른다**
-   **configured probe budget과 cooldown을 따른다**
-   무신호 review가 무한 due loop를 만들지 않음 (click이나 probe skip만
    있는 review도 무신호로 처리된다)
-   **configured probe 간격을 지켜 probe가 연속으로 몰리지 않음**
-   세션 시작이 seed 콘텐츠로 Ready Pool을 만들어, background worker 없이
    첫 세션이 성립함
-   presentation 제시 / 완료 / probe 제시가 재시도로 중복 기록되지 않음
-   client가 보낸 event key로 서버 경로를 막을 수 없음 (server 발급 키와
    client 발급 키의 공간이 겹치지 않아, 한 번의 요청으로 세션 종료나 새
    세션 생성이 영구히 불가능해지는 상태가 만들어지지 않음)
-   종료된 세션과 이미 완료된 문장에는 학습 상호작용이 기록되지 않음. 콘텐츠
    신고만 예외로 계속 받고, 이미 만들어진 노출을 무효화함
-   **같은 노출이 두 번 평가되지 않음**: 한 `(presentation, learning_item)`에
    explicit evidence는 최대 1건이며 **서버가** 그것을 강제함. self-report와
    probe 응답을 합쳐 세고, 두 번째 요청은 재시도로 뚫리지 않으며 mastery·FSRS를
    다시 적용하지 않음. 그 거부가 세션 상태 때문이 아님을 client가 구분할 수 있음
-   contextual progression을 DB에서 재현 가능 (실패 없이 반복 노출하면
    context ladder가 올라가고, explicit `몰랐음` 뒤에는 한 단계 내려간다)
-   incidental click에서 승격된 item이 `new` category로 실제 공급된다
-   item explanation을 DB에서 조회 가능
-   기본 history를 자기 데이터만으로 조회 가능 (최근 session 요약과
    learned/reviewed item summary가 고정 상한 안에서 반환되고, 다른 사용자의
    행은 어떤 요청으로도 들어오지 않음)
-   history가 **잘렸는지를 응답이 말함**: 행이 상한과 정확히 같을 때와 상한을
    넘을 때가 `truncated`로 구분되므로, 화면이 행 수로 추측해 경계에서 거짓을
    말하지 않음
-   tap마다 live LLM 불필요
-   모든 provider 호출이 worker에서만 발생
-   background batch generation/validation/Ready Pool 동작
-   flag된 content가 다시 Ready로 선택되지 않음 (격리된 문장과 같은 문장이
    generation으로 다시 만들어지지도 않음)
-   생성된 문장의 **모든 tappable item에 설명이 있음** (tap했을 때 빈
    화면이 되지 않음)
-   실제 provider 키 없이도 generation 경로 전체를 실행·검증할 수 있고, 그
    mock 구현이 앱 코드에 없으므로 어떤 환경에서도 배포 설정으로 선택될 수 없음
-   worker 생존 여부를 `/api/health`가 구분해 보고함 (한 번도 신호가 없음 /
    살아 있음 / 신호가 끊김)
-   crash로 `running`에 갇힌 job이 자동으로 회수되어 다시 실행 가능해짐
-   영구 오류 job과 attempt 소진 job이 서로 다른 종료 상태로 남음
-   하루 provider 사용량 한도에 도달하면 신규 generation이 멈추고 학습
    세션은 계속 진행됨
-   신규 사용자가 seed 기반으로 첫 세션을 시작 가능
-   **Demo는 backend/DB/LLM과 구조적으로 분리** (paid LLM 0, private data
    접근 0)
-   DB migration 재현 가능
-   Postgres 직접 인터넷 노출 없음
-   secret frontend/Git 노출 없음
-   명세 하한 미만 password로는 계정을 만들 수 없음
-   restart 후 state 유지
-   retry 무한루프 없음 (max attempts + dead-letter)
-   backup/restore 최소 1회 검증

## 수치 취급 원칙

Acceptance Criteria에 실험 수치를 직접 박지 않는다. 검증하는 것은 "엔진이
configured 값을 따르는가"이지 특정 숫자가 아니다.

다만 다음은 현재 제품 핵심으로 승인된 값이며
`14_CONFIGURATION.md`의 **기본값**으로 유지한다.

``` text
max_new_items_per_sentence   = 2
minimum_meaningful_exposures = 5
default_session_minutes      = 12
```

기술 검증 후 실제 2\~4주 사용하여 지속 사용성, 설명 마찰, 자연스러움,
contextual SRS 효과, 12분 적합성을 평가한다. 이 결과가 MVP-02 또는 정책
수정의 근거가 된다.
