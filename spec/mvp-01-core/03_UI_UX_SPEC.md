# UI/UX Specification

Reference: `spec/reference/ui/core-learning-mockup.html`. 기능/상태
명세가 목업보다 우선한다.

**MVP 레이아웃은 단일 컬럼이다.** 모바일이 주 사용 환경이므로(아래
`Study Screen`) mockup의 사이드바는 MVP 구조가 **아니다.** 이 문서가
`사이드바의 ...`라고 적은 곳은 mockup 안에서의 위치를 가리키는 말이며 그
구조를 만들라는 뜻이 아니다. 화면 사이 이동은 각 화면 안의 링크·버튼으로
한다(`History`의 `학습으로 돌아가기`, `Study Screen`의 `학습 기록`).

## Login

`01_USER_FLOW.md`의 `Authentication check`에 대응하는 화면이다. **폼은 두
필드와 버튼 하나가 전부다.**

``` text
login_id     텍스트 입력
password     비밀번호 입력 (마스킹)
[로그인]     POST /api/auth/login
```

-   실패 응답은 사유와 무관하게 같은 401이므로(`05_API_SPEC.md`) 화면도
    **하나의 문구**만 보여준다. "없는 아이디"와 "틀린 비밀번호"를 갈라
    적으면 서버가 감춘 것을 UI가 알려주게 된다.
-   회원가입·비밀번호 재설정·소셜 로그인 진입점을 두지 않는다. public
    signup이 없고 계정은 CLI로만 만들기 때문에(`04_DB_SPEC.md`) 누를 대상이
    되는 endpoint 자체가 MVP에 없다.
-   password 길이 규칙을 이 화면에 적지 않는다. 검증은 계정 생성 경로에만
    있고 login은 검증하지 않는다(`05_API_SPEC.md`).
-   성공하면 Study Screen으로 이동한다. Demo는 로그인 없이 접근하므로 이
    화면을 지나지 않는다.

## Study Screen

오늘 약 12분, sentence, tappable item, translation reveal, next,
explanation panel/sheet, progress, occasional probe.

모바일이 주 사용 환경이므로 한 손 조작과 짧은 세션을 우선한다.

MVP Study Screen에는 **audio/듣기 control이 없다**(`00_SCOPE.md`).
Reference mockup의 🔊 버튼은 Future 표시이며 MVP interactive element가
아니다.

### 진행 표시

진행바의 분자·분모와 "세션 종료 도달"의 판정식은 `05_API_SPEC.md`의
`진행 상태의 갱신과 세션 종료 판정`이 canonical이다. 화면 쪽 요구는 셋이다.

-   진행은 **문장 단위로** 갱신한다. `/complete` 직후
    `GET /api/study/session`을 한 번 다시 읽는다. 문장을 읽는 동안 진행바가
    멈춰 있는 것은 정상이다 --- `active_seconds`는 상호작용 사이의 시간을
    누적한 값이고, 멈춘 화면은 그 정의를 그대로 보여주는 것이다.
-   **주기적 폴링을 하지 않는다.** 진행바를 매끄럽게 만들려고 상호작용
    endpoint를 주기 호출하면 자리를 비운 시간이 학습 시간으로 누적된다(같은
    절). 진행바의 부드러움을 위해 `active_seconds`의 의미를 바꾸지 않는다.
-   **화면에 쓰는 분 수는 서버가 준 숫자만이다.** `오늘 약 12분`의 출처는 응답의
    `target_minutes`이고 연장분은 `extended_minutes`다. config 값을 frontend에
    복사하지 않는다. 서버가 주지 않는 숫자는 아래 `Session End`처럼 문구에서
    **뺀다.**

### 세션 시작 안내

`POST /api/study/session`은 세 결과 중 하나이고, 화면은 그것을 **한 번 사라지는
안내**로 알린다. 문구는 다음으로 고정한다.

``` text
resumed = true                    이어서 학습합니다.
timed_out_session_id != null      이전 세션은 오랫동안 활동이 없어 종료했습니다.
                                  새 세션을 시작합니다.
그 밖 (새 session, timeout 아님)  안내 없음
```

-   **두 안내는 동시에 나오지 않는다.** `resumed = true`인 응답의
    `timed_out_session_id`는 항상 `null`이다 --- resume은 열린 session을 그대로
    돌려주는 경로이므로 닫은 session이 없고, timeout은 그 session을 닫고 **새** session
    을 만드는 경로이므로 `resumed = false`다. 두 값은 배타적이므로 화면에 우선순위
    규칙이 필요하지 않다.
-   처음 시작하는 세션에는 안내를 띄우지 않는다. 알릴 것이 없다.

세 경우 모두 다음 제약을 지킨다.

-   경고나 오류로 보이게 하지 않는다. 사용자가 잘못한 것이 없고 학습 기록도 그대로
    남아 있다. overdue/streak punishment 금지와 같은 취지다.
-   내부 id를 화면에 노출하지 않는다(`timed_out_session_id`, `session_id`).
-   **복귀나 확인 동작을 요구하지 않는다.** 안내를 닫는 것 외에 누를 것이 없고,
    안내가 학습 진행을 막지 않는다.

timeout 경우에만 해당하는 것 하나: **지난 세션으로 돌아가는 동작을 제공하지
않는다.** 그 session은 이미 닫혔고 남은 문장은 영원히 미완료다(`05_API_SPEC.md`의
`세션·presentation 상태 게이트`).

## Explanation

cached/precomputed. canonical expression, reading, type, 핵심 뜻 1\~2개,
현재 문맥 뜻, 짧은 nuance, 예문 1개. 하단 self-report는 선택적.

tap 즉시 표시하며 **live LLM을 호출하지 않는다.** 설명이 없는 item이
포함된 문장은 애초에 Ready Pool에 들어가지 않는다(`08_LLM_SPEC.md`).

설명 패널이 실제로 렌더된 직후에 `explanation_revealed`를 보낸다. `item_clicked`와
시점이 다른 이유(탭했으나 설명이 표시되지 않은 경우를 구분한다)와 횟수 규칙은
`05_API_SPEC.md`의 `explanation_revealed를 언제 보내는가`가 canonical이다.

### tappable span 표시

**tappable span은 전부 같은 방식으로** 지나치게 시험 문제처럼 보이지 않게
subtle하게 표시한다. 학습 대상(target)인 span과 그렇지 않은 span을 시각적으로
구분하지 않으며, 그 구분을 알려주는 필드를 `tappable_items` payload에 두지도
않는다(`05_API_SPEC.md`의 `Sentence Presentation Payload`).

-   대상만 강조하면 그 문장에서 무엇이 평가 대상인지가 드러나 "지나치게 시험
    문제처럼 보이지 않게"가 그 자리에서 무너진다.
-   강조된 span만 눌리게 되어 incidental click 경로가 사실상 사라진다. 그 경로는
    사용자가 target이 아닌 표현을 눌러 `몰랐음`/`애매함`을 고르는 것이고
    (`02_LEARNING_POLICY.md`의 `Incidental Item Click`), MVP에서 신규 학습
    target이 생기는 주된 통로다.
-   target 여부는 `user_sentence_candidate_targets`가 가진 서버 측 사실이며
    (`07_SRS_SPEC.md`의 `target item의 canonical 정의`) 화면이 그것을 알 필요가
    없다.

한 문장에 신규 item은 권장 1개, 최대 2개.

## Mastery Probe

MVP probe UI는 하나로 고정한다. 객관식 의미 문제는 구현하지 않는다.

``` text
이 표현을 알고 계세요?
알고 있었음 / 애매함 / 몰랐음 / 건너뛰기
```

사용자는 언제나 건너뛸 수 있어야 하며 probe는 세션의 중심 UI가 되어서는
안 된다. 상세 정책은 `02_LEARNING_POLICY.md`를 따른다.

## Translation/Furigana

일본어 먼저. 번역 hidden. furigana 상시 표시 금지, item tap 후 reading
제공.

## Session End

`오늘 학습 완료 / 더 학습하기`. overdue/streak punishment 금지.

이 선택지를 언제 띄우는지는 `05_API_SPEC.md`의
`진행 상태의 갱신과 세션 종료 판정`이 canonical이다. 도달했다는 것은 세션이
닫혔다는 뜻이 아니므로 화면을 강제로 전환하지 않는다 --- 사용자가 `오늘 학습 완료`를
누르면 `/finish`, `더 학습하기`를 누르면 `/extend`이고, 둘 다 누르지 않으면 현재
문장을 계속 읽을 수 있다.

**연장 버튼 문구에 분 수를 적지 않는다.** 연장 폭은 서버의
`extra_session_minutes`(`14_CONFIGURATION.md`)이고, 그 값은 `/extend`를 호출하기
전 어떤 응답에도 실려 있지 않다(`05_API_SPEC.md`). 그래서 화면에 `+5분 더`라고
적으면 그것은 **정책값 하드코딩**이다. config를 6분으로 바꾸는 순간 화면은 계속
`5분`이라 말하고 서버는 6분을 더하는데, 그 불일치를 잡는 테스트가 없다. v0.2의
`+5분 더`는 이 이유로 철회한다.

-   같은 규칙이 `오늘 약 12분`을 허용하는 이유는 그 숫자가 응답의
    `target_minutes`로 내려오기 때문이다(위 `진행 표시`). 규칙은 **"서버가 준
    숫자만 화면에 쓴다"** 하나이고, 두 문구의 처리가 갈리는 것은 그 규칙의
    결과다.
-   `01_USER_FLOW.md`와 `spec/03_DOMAIN_MODEL.md`의 `+5분`은 config **기본값**을
    가리키는 서술이며 화면 문구가 아니다.
-   연장이 실제로 얼마였는지는 `/extend` 응답의 `extended_minutes`로 확인되고,
    그 값이 곧 진행바 분모를 갱신한다(위 `진행 표시`). 사용자가 "얼마나 늘었나"를
    알 수 있는 지점은 **누른 뒤**이며, 그 숫자는 서버가 준 것이다.
-   `StudySessionPayload`에 연장 폭을 노출하는 API 변경은 하지 않았다. 이 화면이
    누르기 **전에** 정확한 분 수를 보여야 한다고 요구하는 조항이 어디에도 없고,
    세션 길이 자체를 `오늘 약 12분`처럼 근사로 제시하는 문서 전체의 어조와도
    어긋나지 않는다. 요구가 생기면 API를 먼저 고친다.

### 완료 화면

`/finish`가 성공한 뒤의 화면은 **완료 문구 한 줄과 학습 시간 한 줄로 끝난다.**

``` text
오늘 학습을 마쳤습니다.
학습 시간 {active_seconds에서 만든 값}
```

-   숫자는 `/finish` 응답의 `active_seconds` 하나다. 위 `진행 표시`의 규칙
    **"서버가 준 숫자만 화면에 쓴다"**가 여기에도 적용된다. 초를 분으로 반올림해
    보여주는 것은 표현이고, 없는 값을 계산해 넣는 것은 금지다.
-   **새 세션 시작 버튼을 두지 않는다.** 방금 `오늘 학습 완료`를 누른 사용자에게
    `POST /session`을 권하는 화면이 되면, 눌릴 때마다 session 행이 하나 더 생겨
    **history의 세션 기록이 부풀고**(`05_API_SPEC.md`의 `History`) "한 번 더
    하시죠"라는 압박으로 읽힌다. 후자는 이 절이 이미 금지한
    overdue/streak punishment와 같은 종류다. 이 선택은 새 규칙이 아니라 그 금지의
    결과다.
-   그래서 **완료 후에 막히는 경로는 없다.** 다시 학습하려면 앱을 다시 열거나
    새로고침하면 되고, 그때 `POST /api/study/session`이 새 session을 만든다(idle
    timeout 이내에 같은 날 다시 들어와도 방금 세션은 이미 닫혀 있으므로 resume이
    아니라 신규다). 사용자가 명시적으로 다시 시작하는 동작과 화면이 권하는 동작을
    구분하는 것이 요점이다.
-   통계·streak·정답률·이번 세션 요약을 넣지 않는다(`00_SCOPE.md`의
    `advanced analytics`, `social/gamification`). 학습 기록을 보려면 `History`로
    간다.

## History

사이드바의 `학습 기록`에 대응하는 화면이다. `00_SCOPE.md`의 `기본 history`가
전부이며 **두 목록으로 끝난다.**

``` text
최근 세션    GET /api/history/sessions
학습한 표현  GET /api/history/items
```

-   `최근 세션`은 한 행에 날짜, 학습 시간, 완료한 문장 수를 보여준다. 진행 중인
    세션은 종료 시각 자리에 `진행 중`을 적는다(`ended_at`이 `null`이다).
-   `학습한 표현`은 한 행에 표현(`lemma`), 노출 횟수, 다음 복습 시점을 보여준다.
    `comprehension_mastery`가 `null`인 행은 숫자 대신 **`아직 평가 없음`**으로
    적는다. 0%로 표시하면 "능력이 0"으로 읽히는데 그 값의 뜻은 "아직 evidence가
    없음"이다(`02_LEARNING_POLICY.md`).
-   고정 상한(`05_API_SPEC.md`의 `개수 상한`)에 걸려 목록이 잘리면 그 사실을 목록
    끝에 한 줄로 적는다. 잘린 것을 숨기면 사용자가 기록이 사라졌다고 읽는다. **더
    보기·기간 선택·검색·정렬 변경을 두지 않는다.**
-   그 문구는 응답의 `truncated`가 `true`일 때만 띄운다(`05_API_SPEC.md`의
    `truncated`). **받은 행 수로 추측하지 않는다** --- 행이 정확히 상한만큼인
    사용자에게 잘렸다고 거짓을 말하게 된다.
-   통계·차트·표현별 상세 화면을 두지 않는다(`00_SCOPE.md`의
    `advanced analytics`). 여기서 다음 행동으로 이어지는 버튼도 두지 않는다 ---
    학습은 Study Screen에서만 일어난다.
-   Reference mockup 사이드바의 `표현 보관함`과 `설정`은 **MVP 화면이 아니다.**
    `00_SCOPE.md`에 해당 기능이 없고 그것을 지탱하는 API도 없다.

## 로그아웃

`POST /api/auth/logout`(`05_API_SPEC.md`의 `Authentication`)에 대응하는
**버튼 하나**다. 새 화면을 만들지 않는다.

``` text
화면   Study Screen. 이 화면에만 둔다
위치   화면 위쪽, `학습 기록` 링크 바로 아래
문구   로그아웃
동작   POST /api/auth/logout -> 성공하면 Login 화면으로 이동
```

**`History`에는 두지 않는다.** 그 화면은 `두 목록으로 끝난다`이고 같은 절이
"여기서 다음 행동으로 이어지는 버튼도 두지 않는다"를 이미 정했다. 거기에
로그아웃을 얹으면 그 조항의 첫 예외가 되고, 다음 사람이 그 예외를 근거로
컨트롤을 더 붙인다. 치르는 비용은 **탭 한 번**이다 --- `History`의 유일한
출구인 `학습으로 돌아가기`가 항상 화면에 있고 그 다음 화면이 곧 이 버튼이다.
"기기를 잃었을 때 폐기할 수단이 있다"는 목적에는 **한 곳의 진입점으로
충분하다.**

이것이 MVP 화면인 이유는 `00_SCOPE.md`의 `개인 로그인`이 이미 MVP이고 그
endpoint가 이미 계약에 있기 때문이다. 진입점이 없으면 30일 cookie를
브라우저에서 폐기할 수단이 없어, 기기를 잃거나 공유했을 때 남는 경로가 DB
직접 조작뿐이다. 새 기능을 여는 것이 아니라 **이미 있는 인증 범위를 닫는
것이다.**

-   **확인 대화상자를 두지 않는다.** 잃는 것이 없다 --- 학습 기록은 서버에
    남고 다시 로그인하면 그대로 보인다. 되돌리는 비용이 로그인 한 번이므로
    파괴적 동작이 아니다.
-   **진행 중인 study session을 닫지 않는다.** `logout`이 폐기하는 것은 auth
    session이다. 다시 로그인하면 idle timeout 이내인 세션은 그대로 resume되고
    화면은 위 `세션 시작 안내`의 `이어서 학습합니다.`를 띄운다. 그 안내는
    `POST /api/study/session`의 `resumed`가 담당하므로 **로그아웃 경로가 따로
    하는 일은 없다.** 여기에 `/finish` 호출이나 세션 정리를 붙이지 않는다.
-   실패하면 로그인 화면으로 보내지 않고 그 자리에 짧은 안내만 띄운다
    (`10_ERROR_HANDLING.md`). 쿠키가 살아 있는데 화면만 로그아웃된 상태를
    만들지 않는다. **`401`은 예외로 성공과 같게 처리한다** --- 폐기할 세션이
    이미 없다는 뜻이다(`05_API_SPEC.md`).
-   **Demo에는 두지 않는다.** Demo는 Login 화면을 지나지 않으므로 폐기할
    세션이 없다(위 `Login`, 아래 `Demo`).
-   이 버튼과 함께 계정 관리·설정·통계 화면을 만들지 않는다. 위 `History`의
    `설정`은 MVP 화면이 아니라는 조항은 그대로다.

## Demo

Demo임은 알리되 실제 학습 UX와 최대한 동일하게.

Demo는 static frontend fixture로만 동작한다. backend API를 호출하지
않으며 demo 상태는 browser memory/session 수준에서만 유지한다
(`04_SECURITY_AND_DATA.md`).
