# MVP-02 Test Plan (delta)

`spec/mvp-01-core/12_TEST_PLAN.md`의 모든 항목은 그대로 유지한다. 이 문서는 MVP-02에서 **더하는**
테스트만 적는다. 규칙의 canonical은 각 항목 끝에 적은 조항이며, 이 문서는 무엇을 단정하는지와 어디에
두는지를 정한다.

-   **수치를 테스트에 복사하지 않는다.** demo 전용 상수는 `frontend/src/demo/constants.ts`의 상수를
    참조하고, 가나 라운드 문항 수도 그 값을 정의한 곳을 참조한다. 학습 정책값은 기존대로 config를
    참조한다.
-   **변이 검증은 불변식 13\~20의 핵심 단언에만 한다**(아래 `변이 검증`). 기존 MVP-01 항목의 추가
    변이 검증은 하지 않는다.
-   아래 `위치`의 새 파일 이름은 권장이다. 구현이 이름을 바꾸면 이 표도 같은 변경에서 고친다. 이미 있는
    파일 이름은 그대로다.
-   결정 배경: 후리가나는 ADR-021, 선택 홈·로그인 진입·격리·localStorage는 ADR-022다.

## 명령

``` text
backend    make lint typecheck test
frontend   cd frontend && npm test && npm run build
e2e        make test-e2e
           (개별: NC_E2E_REQUIRED=1 uv run pytest -m e2e backend/tests/e2e/<파일>)
fixture    uv run python scripts/build_demo_fixture.py --check     커밋된 fixture와 재생성 결과 비교
backfill   uv run python scripts/backfill_ruby.py                   dry-run (쓰기 없음)
           uv run python scripts/backfill_ruby.py --apply --pg-bin <DIR>
```

Makefile 타깃 이름은 구현이 정한다. 테스트는 위 스크립트를 직접 부르거나 그 진입 함수를 부른다.

## Frontend Unit

### 격리 검사 (불변식 13·14)

위치: `frontend/tests/unit/demo-isolation.test.ts`(공개 화면 셋으로 확장), `demo-route.test.ts`,
새 `login-entry.test.ts`. 검사 규칙의 canonical은 `spec/04_SECURITY_AND_DATA.md`의 `격리 검사 (MVP-02 확정)`다.

-   TypeScript 컴파일러 AST로 만든 import 그래프로 **(a)\~(d)**를 단정한다.
    -   (a) `main.ts` 정적 그래프에 `api.ts`·`endpoints.ts`·`env.ts`·`private.ts`가 없다.
    -   (b) `src/home/`, `src/demo/`, `src/kana/` 아래 **모든 모듈**의 정적 + 리터럴 동적 그래프에 위 네 모듈이
        없다(디렉터리 기준).
    -   (c) `private.ts` 정적 그래프 밖에서 API 모듈에 닿는 동적 import는 `main.ts`의 `import('./private')`
        하나다. `main.ts` 정적 그래프 안의 리터럴 동적 import 대상은 `private.ts`이거나 home·demo·kana 아래다.
    -   (d) `src/` 전체에 다음이 없다: 비리터럴 `import()`, 풀리지 않는 상대·루트 지정자(`.js` 확장자 지정자 포함),
        bare 지정자, `?` 쿼리 지정자(`?worker`, `?raw` 등), `import.meta.glob`, `env.ts` 밖의 `import.meta.env`,
        `api.ts` 밖의 네트워크 원시 API(`fetch`, `XMLHttpRequest`, `navigator.sendBeacon`, `WebSocket`, `EventSource`),
        `new Worker`/`new SharedWorker`, `eval`/`Function` 생성자, 첫 인자가 함수가 아닌 `setTimeout`/`setInterval`,
        `require()`, 인자가 문자열 리터럴이 아니거나 `'script'`인 `document.createElement`, HTML 삽입(`innerHTML`,
        `outerHTML`, `insertAdjacentHTML`, `document.write`, `document.writeln`, `Range.createContextualFragment`,
        `DOMParser.parseFromString`, `iframe.srcdoc` 대입), `setAttribute`로 `on*`·`srcdoc`에 넣는 값(리터럴 포함)과 `href`·`src`에 넣는 동적 값,
        고정 route 상수가 아닌 값의 이동(`location.href =`, `location.assign`, `location.replace`, `window.open`,
        `a.href =`). `createElementNS`·`setAttributeNS`, `src`·`action`·`formAction`·`data` 동적 대입, 다단계 전역 객체
        접근(`window.window`, `top`, `parent`, `frames`, `document.defaultView`)도 목록에 든다(`spec/04_SECURITY_AND_DATA.md`의
        (d)가 canonical).
    -   **fail-closed:** 판정 함수가 풀지 못한 지정자를 건너뛰지 않고 위반으로 낸다.
    -   **양성 대조군:** `private.ts` 그래프에 `endpoints.ts`가 있다. (d)의 판정 함수가 합성 소스의
        `import('../' + 'api')`, `import.meta.glob`, `import './api.js'`, `import 'some-pkg'`, `import W from './x?worker'`,
        `api.ts` 밖의 `fetch`, `el.innerHTML = s`, `document.createElement(tag)`, `setTimeout(code)`,
        `el.setAttribute('onclick', v)`, `el.setAttribute('onclick', 'x()')`, `el.setAttribute('href', v)`, `location.href = v`를 각각 위반으로 낸다.
    -   **한계:** 이 검사는 실수 방지용이며 의도적인 우회는 막지 못한다. 부팅 런타임 단정과 e2e (f)가 받친다.
    -   이 항목이 MVP-01 backlog의 "demo 격리 검사가 동적 import를 놓칠 가능성"을 해소한다((c)(d)).
-   **(e) 빌드 산출물:** 현재 소스로 빌드한 `dist/index.html`의 entry 청크에 API base URL 문자열(unit 빌드에서는
    `env.ts`의 기본 origin)이 없고, `dist/assets`의 어떤 청크에는 있다(양성 대조군). 빌드 신선도 확인은
    `no-service-worker.test.ts`와 공용 helper로 한다.
-   **부팅 런타임 단정:** `main.ts`를 `''`, `'#/'`, `'#/demo'`, `'#/kana'`, `'#/kana/<하위>'`, 모르는 hash로
    부팅하고 **가짜 타이머를 충분히 진행한 뒤에도** 던지는 `fetch` 스텁이 **불리지 않는다.** 상단바 `로그인`을
    누르면 **정확히 1회** 불린다. 확인 중에 다시 눌러도 겹쳐 불리지 않는다.
-   **`openLogin` 호출 위치(AST):** `openLogin` 호출이 `ui/topbar.ts`의 로그인 버튼 `click` 리스너 콜백 안 한 곳뿐이다.
    공개 화면 모듈과 `main.ts`는 `renderTopBar`의 `onLogin`으로 넘기기만 한다. 위 런타임 단정이 그 결과를 본다.
-   **로그인 진입 결과:** `enterPrivate`에서 200이면 Study Screen, 401이면 Login, 403이면 `출처 거부` 문구만 있고 버튼이 없으며,
    그 밖의 실패면 인라인 안내와 `다시 시도하기`이고 누르면 `fetchMe`만 다시 불린다(동적 import와 hash 처리는 되풀이되지 않는다). `import('./private')`가 실패하면 홈 자리에 안내 "로그인 화면을 불러오지 못했어요. 위의 로그인을 다시 눌러 주세요."만 남고
    버튼이 없다. 상단바 `로그인`을 누르면 hash가 `history.replaceState`로 지워지고 `hashchange`가 오지 않는다.
-   **늦은 응답:** `fetchMe` 응답을 기다리는 동안 `hashchange`로 홈에 가면, 늦게 온 200이 학습 화면을 그리지
    않고 **다음 요청(세션 요청)도 시작하지 않는다**(`signal.aborted`). 동적 import 도중 떠나면 `fetchMe`도 나가지
    않는다.
-   **세션 시작 늦은 응답:** `POST /api/study/session` 응답을 기다리는 동안 학습 화면의 `signal`이 abort되고 그 뒤
    응답이 도착하면 세션 시작 안내 토스트가 없고 `/next` 요청도 나가지 않는다(`study.test.ts`).
-   **URL 값 비출력:** 모르는 hash나 하위 경로 문자열(예: `<img>`가 든 값)을 넣어도 화면 텍스트와 DOM에 그 값이
    나오지 않는다.

### route와 상단바

위치: 새 `routes.test.ts`, `home.test.ts`, `topbar.test.ts`, 기존 `logout.test.ts`.

-   `''`와 `#/`는 선택 홈, `#/demo`는 Demo, `#/kana`와 `#/kana/<하위>`는 가나 학습이고 `subpath`가 전달된다.
    모르는 hash는 선택 홈이며 URL이 `#/`로 바뀐다. `navigate`가 같은 hash에서도 화면을 적용한다.
-   `hashchange` 리스너는 `routes.ts` 한 곳이다. 로그인 영역에는 hash가 생기지 않는다.
-   선택 홈에 카드 둘이 있고 카드에 문장 수 숫자가 없다.
-   `ui/topbar.ts`가 `ui/logout.ts`를 import하지 않는다(버튼은 `actions`로 받는다).
-   상단바 오른쪽: History는 `로그아웃`만, Login은 비어 있음, Study Screen은 `학습 기록`·`로그아웃`·후리가나 토글,
    Demo는 후리가나 토글·`로그인`, 선택 홈·가나 학습은 `로그인`.
-   로그인 확인 실패(403·연결 실패) 화면과 로그인 영역 불러오기 실패 화면의 상단바 오른쪽은 `로그인`이고, 누르면 로그인 진입이 처음부터(abort, hash 지움, 동적 import, `fetchMe`) 다시 일어난다.
-   로그아웃 성공(401 포함)이면 선택 홈이다. 실패면 그 자리에 안내가 남는다.
-   Login 폼은 두 필드와 버튼 하나이고 폼 안에 demo 진입 버튼이 없다. 실패 문구는 사유와 무관한 한 문구다.

### 문구

위치: 각 화면 테스트(`explanation`, `probe`, `flag`, `history`, `logout`, `progress`, `session-end`,
`demo`, `home`, kana 화면).

-   화면 문구가 `mvp-01-core/03_UI_UX_SPEC.md`의 `화면 문구 표`와 같다. MVP-01 테스트가 옛 문구를 단정하던
    곳은 새 문구로 바꾼다.
-   `세션 시작 안내`, `완료 화면`의 바뀐 문구와 `Mastery Probe` 선택지, `오늘 학습 완료 / 더 학습하기`,
    `아직 평가 없음`이 각 절의 고정 문구와 같다. probe 질문은 서버 값을 그대로 쓴다.
-   유형 태그 매핑(`word` → 단어 등)이 표시용이며 모르는 값은 원문 그대로다.

### 화면 전환과 시트

위치: 새 `screen.test.ts`, `sheet.test.ts`, 기존 `interactions.test.ts`, `explanation.test.ts`.

-   **번역:** `문장 뜻 보기`를 누르기 전에는 번역 노드가 DOM에 없고, reveal 응답 뒤에 문장 아래 인라인
    영역에 생긴다. 시트가 열리지 않는다.
-   **설명 시트:** `role="dialog"`이고 `닫기`·가림막·Esc로 닫히며 포커스가 연 표현으로 돌아온다. 닫은 뒤
    조작이 `transitionend` 없이도 즉시 가능하다.
-   **`explanation_revealed` 시점:** 떠나지 않은 학습 화면의 DOM에 설명 내용이 삽입된 직후에 보낸다. 애니메이션
    종료 이벤트가 오지 않는 가짜 DOM에서도 보낸다.
-   **떠난 뒤 도착한 응답:** 표현을 탭해 `/click`이 대기 중일 때 상단바 앱 이름이나 뒤로 가기(`hashchange`)로
    화면을 떠나고 그 뒤 `/click` 응답이 도착하면, 설명이 그려지지 않고 `explanation-revealed` 요청이 **0건**이다
    (`item_clicked`만 남는다).
-   **학습 기록으로 떠난 뒤 도착한 응답:** `/click` 대기 중에 상단바 `학습 기록`으로 로그인 영역 안에서 화면을 옮겨도
    같다. 늦게 온 응답 뒤 설명 시트가 없고 `explanation-revealed` 요청이 0건이며 `/click`은 1건이다(`study.test.ts`).
-   **재열기:** 설명 시트를 닫고 같은 표현을 다시 탭하면 설명이 다시 보이고, `/click`과 `explanation-revealed`
    요청이 **presentation + item당 1회**뿐이다. 다른 표현을 탭하면 그 item의 첫 요청이 나간다.
-   **`showScreen`:** `signal`이 abort되었으면 아무것도 하지 않는다.
-   **토스트:** 정보성 안내만 토스트이고 일정 시간 뒤 사라진다. 오류는 인라인 안내와 행동 버튼이다.

### 후리가나 (불변식 15·16·17)

위치: 새 `furigana.test.ts`(`ui/furigana.ts`), 기존 `segments.test.ts`, `interactions.test.ts`, `fake-dom.ts`.

-   **설정:** `nc.furigana.v1`이 없거나 형식이 틀리거나 읽을 수 없으면 `isFuriganaOn()`이 false다. 정확히
    `{"on": true}`일 때만 true다. `setFuriganaOn`이 저장하고 `document.documentElement`의 `furigana-on`
    class를 전환한다. localStorage가 던져도 끔으로 시작하고 토글이 동작한다.
-   **CSS class 전환:** 토글 전후로 문장 DOM 노드가 **같은 노드**이고(다시 렌더링하지 않음), tappable 버튼과
    상호작용 handle이 다시 만들어지지 않으며, 네트워크 호출이 0건이다.
-   **렌더링:** `renderSentence`의 시그니처가 그대로다. `ruby`가 `[]`이면 text만, 아니면 `reading`이 null인
    part는 텍스트 노드, 그 밖은 `<ruby>text<rt>reading</rt></ruby>`다. `rt`는 토글과 무관하게 항상 만들어진다.
-   **불변식 17:** `rt`를 뺀 문장 텍스트가 원문과 같고, 모든 ruby가 tappable 버튼 안이거나 밖에 온전히
    있으며, tappable 버튼의 텍스트와 개수가 ruby가 없을 때와 같다. 문장 `aria-label`에 읽기가 없다.
-   **표시 범위:** 설명 시트의 예문·`canonical_form`, probe의 표현 표기에 ruby가 없다. probe가 떠 있는 동안에도
    학습 문장의 ruby가 그대로다. CSS 선택자가 학습 문장 안의 `rt`로 한정된다.
-   **설명의 읽기:** 설명 머리가 span 표면형과 데이터의 `reading`을 짝지어 보여주고 기본형을 따로 적는다.

### 가나 학습

위치: 새 `kana-data.test.ts`, `kana-quiz.test.ts`, `kana-progress.test.ts`, `kana-screen.test.ts`,
`kana-route.test.ts`.

-   **데이터 품질:** 히라가나·가타카나 각각 청음·탁음·반탁음·요음 표가 `03_UI_UX_SPEC.md`의 `정답 표기` 표의
    글자 수와 같다. 촉음·장음 단어가 두 문자 체계 각각에 있고 외래어는 가타카나에만 있다. 글자·단어의
    **중복이 없다.** 로마자가 소문자 ASCII이고 장음 부호가 없다. **한글 표기 누락이 없고** 단어에는 뜻이
    있다. 데이터는 명시적 import다.
-   **로마자 규칙의 대표 예:** `ん`=`n`, `を`=`o`, `っち`=`tchi`, `おう`=`ou`, `ええ`=`ee`,
    `コーヒー`=`koohii`, `じゃ`=`ja`, `しゃ`=`sha`, `ちゃ`=`cha`가 데이터에서 그대로 나온다
    (해당 글자·단어가 데이터에 있을 때).
-   **보고 고르기:** 선택지가 로마자 4개, 정답이 정확히 하나, 겹침 없음, 오답은 같은 범위다. 난수를 주입하면
    문항과 선택지가 고정된다.
-   **라운드:** 문항 수가 `라운드` 상한을 넘지 않는다. 틀린 문항은 라운드 끝에 한 번 더 나오고, 다시 나온
    문항은 또 나오지 않는다. 결과의 맞힌 수는 처음에 바로 맞힌 수다. 다시 나온 문항을 또 틀리면 보고 고르기
    피드백이 `정답은 {로마자}예요.`뿐이고 보고 읽기는 토스트가 없다(`kana-screen.test.ts`).
-   **진도 저장:** 응답마다(다시 묻는 문항 포함) `nc.kana.v1`의 글자·단어별 맞음/틀림 수가 늘고 마지막 학습
    시각이 저장된다. 형식이 맞지 않는 값은 조용히 초기화된다. localStorage가 던져도 퀴즈가 끝까지
    진행된다. 진도 초기화가 확인 뒤 가나 진도만 지운다.
-   **하위 경로:** 라운드 진행 상태가 hash에 없다.

### Demo

위치: 기존 `demo.test.ts`, 새 `demo-progress.test.ts`.

-   **진행 규칙:** 자기평가에서 "몰랐음/애매함"을 고른 문장이 `DEMO_REVIEW_AFTER_SENTENCES` 뒤에 한 번 다시
    나온다. **probe에서 "몰랐음/애매함"을 골라도 같다.** 같은 문장이 두 번째로 대기열에 들어가지 않는다.
    다시 나온 문장은 `본 문장 수`를 올리지 않는다. probe에서 고른 표현(learning item)이 여러 문장에 나왔으면
    가장 최근에 본 문장이 대기열에 들어간다.
-   **probe:** `DEMO_PROBE_EVERY_SENTENCES`마다 한 번, 앞에서 본 문장의 자기평가하지 않은 표현이 먼저 본
    순서로 골라진다. 후보가 없으면 건너뛰고 같은 표현은 다시 묻지 않는다. 건너뛰기로 응답한 표현도 다시 묻지 않는다.
-   **완료:** 모든 문장을 한 번 이상 봤고 대기열이 비었을 때만 완료 화면이다. 두 행동이 `#/kana` 이동과 진도
    삭제 뒤 첫 문장이다. 새 문장이 끝났는데 대기열이 남으면 대기열 순서대로 곧바로 나오고, `본 문장 수`는 그대로인
    채 대기열이 비면 완료다.
-   **없어진 것:** 12분 진행바, `오늘 학습 완료 / 더 학습하기`, 연장이 없다. 진행 표시는
    `본 문장 수 / 전체 문장 수`다.
-   **진도 저장:** `nc.demo.v1`에 fixture 식별자, 현재 위치, 표현별 자기평가(key `learning_item_id`), 다시 보기
    대기열, 본 문장 수, probe로 물은 표현이 저장되고 다시 mount하면 이어진다. 식별자가 다르거나 형식이 맞지 않으면 조용히 처음부터다.
    localStorage가 던져도 메모리로 끝까지 진행된다. 진도 초기화가 확인 뒤 demo 진도만 지우고
    `nc.furigana.v1`은 남긴다.
-   **신고 UI:** 신고해도 요청이 없고 "체험에서는 신고가 저장되지 않아요."가 보인다. 신고한 문장의 다시 보기
    동작은 신고하지 않은 경우와 같다.
-   **route 적재 실패:** demo 화면 동적 import가 실패하면 인라인 실패 문구가 보인다.
-   **상수 위치:** 두 상수가 `frontend/src/demo/constants.ts` 한 곳에만 정의된다.

### localStorage (불변식 18)

위치: 새 `local-store.test.ts`, `local-storage-scope.test.ts`. 규칙의 canonical은
`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)`다.

-   `localStorage` 식별자가 `src/local-store.ts`에만 나온다.
-   **계산된 속성 접근:** `globalThis`, `window`, `self`, `document`, `navigator`, `history`, `location`에 대한 `[...]`
    접근이 없고, `local-store.ts` 밖의 문자열 리터럴에 `Storage`, `cookie`, `indexedDB` 조각이 없다.
-   `sessionStorage`, `indexedDB`, `document.cookie`, `cookieStore`, `caches`, `window.name`, `navigator.storage`가 `src/` 어디에도
    없고, `history.pushState`/`replaceState`의 state 인자가 `null`뿐이다.
-   `LOCAL_STORE_KEYS`가 `nc.furigana.v1`, `nc.kana.v1`, `nc.demo.v1`과 같다. `localSlot` 호출이 key마다 정확히 한
    번이고 소유 위치(`ui/furigana.ts`, `src/kana/` 한 모듈, `src/demo/` 한 모듈)에만 있으며 key 인자가 문자열
    리터럴이다. 같은 key로 두 번 만들면 던진다.
-   `private.ts` 그래프 안의 `localSlot` 호출이 `nc.furigana.v1` 하나뿐이다(AST).
-   던지는 `localStorage` 스텁에서 `read`가 undefined, `write`가 던지지 않고, 같은 페이지의 다음 `read`가 쓴 값을
    돌려준다. `remove`가 메모리와 저장소 둘 다에서 지운다. JSON이 아닌 저장값은 undefined다. `isValid`를 통과하지
    못하는 값의 `write`는 아무것도 하지 않는다.
-   **값 범위와 소속(`isValid`):** 다른 키가 섞인 후리가나 값, 음수·소수 맞음/틀림 수, 유한하지 않은 시각, 가나
    데이터에 없는 글자 key, 다른 fixture 식별자, 문장 수를 넘는 위치, fixture에 없는 문장·표현을 가리키는
    대기열·자기평가가 저장되어 있으면 `read`가 undefined이고 조용히 처음부터 시작한다.
-   저장되는 값에 로그인 여부, `login_id`, 인증 값, 서버 응답 데이터가 없다.

## Backend Unit·Integration (후리가나)

규칙의 canonical은 ADR-021과 `mvp-01-core/04_DB_SPEC.md`의 `ruby_json`, `05_API_SPEC.md`의
`render_segments[].ruby`다. 분석기는 실제 사전을 쓴다(호스트 기본 dependency group).

### 정렬과 교정 (`app/furigana.py`)

위치: 새 `backend/tests/test_ruby_alignment.py`.

-   **정렬 단위:** okurigana 분리(`任せ` → `任[まか]`), `々` 등 한자 run에 붙는 문자(`時々` 하나), 정렬이 모호한
    토큰의 축약 span, 정렬 불일치의 토큰 전체 span, 숫자 규칙(수사 품사, 숫자 문자, 수사 바로 뒤 한자 토큰)의
    생략, 사전 읽기 없음의 생략, tappable 경계 충돌 시 짧은 단위 재분할 구제(읽기 이음이 같을 때만), 연탁으로
    이음이 다르면 구제하지 않고 생략(`本棚`). 모호·불일치처럼 사전이 잘 내지 않는 입력은 토큰 dataclass를
    직접 만들어 넣는다.
-   **교정 계층 1:** tappable item span에서 `explanation.reading`으로 정렬이 성립하면 그 읽기가 쓰이고 그 글자를
    덮는 분석기 span이 버려진다. 성립하지 않으면(0개 또는 2개 이상) 분석기 읽기를 쓴다. 불연속 span은 위치가
    끊기는 곳에서도 run을 자른다.
-   **교정 계층 2:** 규칙마다 적중 조건(앞 토큰 연속, 다음 토큰 집합)에서 적중하고 조건 밖에서 적중하지
    않는다(`何です`는 `なん` 유지, `席は空いて`는 `あい` 유지). 표 순서대로 처음 적중한 규칙 하나만 쓴다.
    재분할은 교정된 읽기와 짧은 단위 읽기 이음을 비교한다.
-   **불일치 보고 두 종류:** `reading_mismatch`(정렬 불성립 + 다름)와 `explanation_override`(정렬 성립 + 다름)가
    각각 나온다. 설명 읽기 정규화(NFKC, 공백 제거, 가나 변환)가 적용된다.
-   **결정성:** 같은 입력의 결과가 같다. 계산 모듈이 시계를 읽지 않는다(`computed_at`은 주입).
-   **ruby_json 모양:** `algorithm_version`, `analyzer`, `dictionary`, `split_mode`, `computed_at`, `spans`,
    `omitted` 세 키, `corrected` 두 키가 항상 있다. span은 start 오름차순이고 겹치지 않으며 읽기가 히라가나다.
-   **생략 비율:** seed 전체에 대해 "경계로 생략한 토큰 수 / 한자를 포함한 토큰 수"를 계산해 출력한다.

### 저장값 검증과 payload (`app/render.py`, API)

위치: 기존 `test_render.py`, `test_study_api.py`, `test_services_presentation.py`.

-   **R1\~R4:** `ruby`는 `[]`이거나 parts의 text 이음이 segment text다. span이 없는 segment는 `[]`이고
    `[{"text": ..., "reading": null}]`로 나오지 않는다. 인접한 null part가 합쳐진다. reading이 히라가나다.
-   **R5:** `ruby_json`이 NULL이면 모든 segment가 `[]`이다. `spans: []`도 모든 segment가 `[]`다.
-   **R6:** 저장값이 검증을 통과하지 못하면(원문 밖, 겹침, tappable 경계 침범, 빈 읽기, **히라가나가 아닌 읽기** ---
    예: 가타카나 `タナカ`, 한자, ASCII, U+3097 이후 문자, `spans`가 배열이 아니거나 원소 모양이 틀린 값) 응답이 **200**이고 모든 segment가 `[]`이며
    `ruby.invalid_stored`가 기록된다. tappable span 오류는 여전히 500이다.
-   **R7:** 응답이 토글 상태와 무관하다(요청에 토글 정보가 없다).
-   probe와 `/click` 응답에 ruby가 없다.

### 계산 지점과 실패

위치: 기존 `test_seed_loader.py`, `test_jobs_persistence.py`, `test_jobs_worker.py`, 새
`test_ruby_persistence.py`.

-   **seed 적재:** 문장마다 `ruby_json`이 채워진다. `compute_ruby`를 던지게 대체하면 그 문장은 `ruby_json = NULL`
    이고 적재가 계속된다.
-   **worker 저장:** test double provider로 생성 job을 끝까지 돌리면 저장된 문장의 `ruby_json`이 채워진다.
    `compute_ruby`를 던지게 대체해도 문장은 `validated`이고 `ruby_json = NULL`이며, 이어진 materialization이
    `ready` candidate를 만든다. `ruby.failed`가 기록된다. `EXPLAIN_ITEM`은 `ruby_json`을 바꾸지 않는다.
-   **worker 부팅:** 분석기 적재가 실패하면 worker 진입점이 부팅에 실패한다.
-   **원문 불변:** 계산 전후로 `sentences.japanese`와 span 행이 바뀌지 않는다.
-   **같은 계산 함수:** seed 적재, worker, backfill, fixture 생성이 같은 입력에 같은 `spans`를 낸다.

### 경계 guard (불변식 15)

위치: 기존 `test_module_boundaries.py`, `test_no_provider_in_request_path.py`, `test_infra_compose.py`.

-   **G14(a)** 분석기 import는 `app/furigana.py`에서만. **(b)** `app.furigana` import는 `ANALYZER_IMPORTERS`
    (`services/seed_loader.py`, `jobs/persistence.py`)에서만. **(c)** `app/furigana.py`는 DB·설정·시계·다른 계층을
    import하지 않고 L0 중 `render`만 쓴다. `render.py`는 `PURE_MODULES`에 남는다.
-   **런타임 탐침:** 별도 프로세스에서 API를 띄워 요청까지 밟은 뒤 `sys.modules`에 `app.furigana`, `sudachipy`,
    `sudachidict_core`가 없다(`FORBIDDEN_IN_API_PROCESS`).
-   **의존성 위치:** `sudachipy`와 `sudachidict-core`가 `pyproject.toml`의 `[project.dependencies]`에 없고 dependency
    group `furigana`에만 있다.
-   **이미지:** `Dockerfile.backend`의 sync 명령이 기본 group 없이, `Dockerfile.worker`는 `furigana` group을
    더해 sync한다는 것을 고정한다. `pyproject.toml`의 `default-groups`에 `furigana`가 있다.

### migration (불변식 19)

위치: 기존 `test_migrations.py`, `test_schema_invariants.py`.

-   빈 DB에서 upgrade·downgrade 왕복이 된다.
-   **학습 기록이 있는 DB**에서 upgrade한 뒤 기존 행이 그대로이고 `sentences.ruby_json`이 NULL이다.
-   새 migration은 `ADD COLUMN ruby_json JSONB NULL`(default 없음)뿐이다.

### backfill

위치: 새 `backend/tests/test_backfill_ruby.py`.

-   **dry-run:** `--apply` 없이 실행하면 쓰기가 없고 "dry-run: nothing written"과 요약·불일치 목록을 출력하며
    계산 실패가 없으면 exit 0이다. 가린 대상 DSN과 `algorithm_version`을 먼저 출력한다(password 없음).
-   **백업 강제:** `--apply`에서 쓸 행이 있으면 쓰기 전에 백업을 만들고 검증한다. 백업이 실패하도록 만들면
    쓰기 없이 exit 2다. 백업을 건너뛰는 옵션이 없다. 계산 실패가 없고 쓸 행이 0이면 백업 없이 exit 0이다.
-   **멱등:** 두 번째 `--apply`는 대상 0, 백업 없음, exit 0이다.
-   **동시 실행:** 두 실행이 겹쳐도 결과가 같고 늦은 쪽의 갱신이 0행이다. 그 사이 worker가 쓴 행을 덮어쓰지
    않는다.
-   **재계산 옵션 없음:** `ruby_json`이 이미 있는 행(버전이 낮아도)은 대상이 아니고, 이미 계산된 행을 다시 쓰는
    옵션이 없다.
-   **계산 실패와 종료 코드:** 실패한 문장이 있으면 **쓸 행 수와 무관하게** exit 2다. `--apply`에서는 성공분을
    쓴 뒤 exit 2, 성공분이 0이면 백업 없이 exit 2, dry-run에서도 exit 2다. 실패한 문장은 NULL로 남고 다음 실행이
    그 문장만 다시 본다.
-   **학습 테이블 비접근:** 실행 전후로 학습 테이블의 행이 같다.
-   **출력 이스케이프:** 설명 읽기나 표면형에 제어문자(개행, ESC 등)가 든 문장으로 불일치 목록을 출력하면 그
    문자가 이스케이프되어 한 줄로 나온다(seed 적재·fixture 생성의 CLI 출력도 같은 함수를 쓴다).
-   **prompt 불변:** `backend/app/llm/prompts/`가 MVP-02에서 바뀌지 않았고 structured output 스키마에 읽기 필드가
    없다(`git diff`로 확인).

## Fixture (demo, 불변식 20)

위치: 새 `backend/tests/test_demo_fixture.py`. 규칙의 canonical은 `mvp-01-core/03_UI_UX_SPEC.md`의 `Demo`의
`fixture`다.

-   **재생성 일치:** `scripts/build_demo_fixture.py --check`가 커밋된 fixture와 재생성 결과가 같다고 판정한다.
    fixture를 한 글자 바꾸면 실패한다.
-   **선택 규칙:** 작은 입력으로 item 정렬 키(`difficulty_label` → `frequency_rank` → `seed_id`), "아직 덮지 않은
    item을 가장 많이 덮는 문장", 문장 `seed_id` 동률, 상한, 선택 순서가 규칙대로 나온다. `frequency_rank`가 없는
    item은 같은 `difficulty_label`의 rank 있는 item 뒤에 `seed_id` 순으로 온다.
-   **검사 3종:** span 문자열 불일치, 설명 누락, 문장당 tappable item 수 범위 밖인 문장이 각각 제외되고 사유와
    함께 출력된다. tappable 수 상한은 `config/default.yaml`의 `learning.max_new_items_per_sentence`에서 읽는다.
-   **덮지 못한 item:** 상한 안에서 덮지 못한 item이 있으면 멈추지 않고 목록을 출력한다.
-   **ruby 일치:** fixture segment의 `ruby`가 `compute_ruby` + `build_render_segments`의 출력과 같다. 형식이
    `render_segments[].ruby`와 같다. ruby 계산이 실패한 문장은 ruby `[]`로 포함되고 `ruby_failed` 줄이 나오며 exit 0이다.
-   **fixture 식별자:** fixture 내용이 같으면 같고 내용이 바뀌면 달라진다.
-   **출처:** fixture의 모든 문장이 `seed/`의 문장이다.

## Browser E2E

휴대폰 viewport로 돈다. "서버 요청"은 API origin으로 나간 요청이다(정적 자산 제외).

| 파일 | 단정 |
|---|---|
| 새 `test_home_browser.py` | hash 없이 열면 앱 이름, `로그인`, 한 줄 소개, 카드 2개. API 요청 0건, `/api/auth/me` 없음. `로그인`을 누르면 `/api/auth/me` 1건. 401이면 Login, 로그인하면 Study Screen. Study Screen 새로고침 → 선택 홈, 다시 `로그인` → 곧바로 Study Screen. 로그아웃 → 선택 홈. 선택 홈 → Demo → 뒤로 → 선택 홈, 선택 홈 → 가나 → 뒤로 → 선택 홈 |
| 기존 `test_frontend_invariants.py` | **(f)** API origin에 아무도 listen하지 않는 구성에서 `''`, `#/demo`, `#/kana`를 열고 조작해도 **frontend origin 밖으로
나가는 요청 0건**(API origin과 제3자 origin 모두). `reducedMotion: 'reduce'`에서 화면 진입과 설명 시트에 transform 이동이 없다. localStorage 접근이 던지는 페이지에서 선택 홈·Demo·가나·후리가나 토글이 동작한다 |
| 새 `test_furigana_browser.py` | Study Screen과 Demo에서 기본 끔, 켜면 한자 위 읽기, 한쪽에서 켠 설정이 다른 쪽과 새로고침 뒤에도 유지. 켠 상태의 탭·설명·번역·다음 문장 요청이 끈 상태와 같다. 토글 자체는 요청 0건 |
| 기존 `test_demo_e2e_browser.py` | 카드로 들어가 설명 시트, 번역 인라인, 자기평가, probe, 같은 문장 다시 보기. 새로고침 뒤 같은 위치. 완료 화면의 `글자 배우기`가 `#/kana`(완료 직전 상태는 저장 형식에 맞춘 값을 미리 넣어 만든다). contextual review 단정은 같은 문장 다시 보기로 바꾼다 |
| 새 `test_kana_browser.py` | 두 탭, 범위 칩, 두 퀴즈 방식, 틀린 문항 재출제, 라운드 결과, 새로고침 뒤 진도 유지, 진도 초기화 |
| 기존 `test_core_e2e_browser.py`, `test_history_browser.py`, `test_pwa_installable.py`, `study_flow.py` | 로그인을 상단바 `로그인` 경유로 바꿔 그대로 통과. PWA 검사의 API 없는 경로를 `/`로 바꿀 수 있다 |

## 변이 검증

불변식 13\~20의 핵심 단언이 **실제로 회귀를 잡는지** 확인한다. 변이를 넣고 해당 테스트가 빨개지는 것을 본
뒤 되돌린다. 결과(변이, 실패한 테스트)는 게이트 보고에 남긴다. 표에 없는 후보는 기록만 한다.

| 불변식 | 핵심 단언 | 넣을 변이 (예) | 빨개져야 할 테스트 |
|---|---|---|---|
| 13 | 공개 화면이 API 모듈에 닿지 않고 요청 0건 | `src/kana/` 모듈에 `import '../api'` 추가 / `import '../api.js'` 추가 / `import W from './x?worker'` 추가 / `routes.ts`에 `import('./ui/study')` route 추가 / `import('../' + 'api')` 추가 / demo에서 `fetch` 호출 / 공개 화면에 제3자 이미지 URL 추가 | `demo-isolation.test.ts` (b)(c)(d), `test_frontend_invariants.py` (f) |
| 14 | 부팅에서 `fetchMe` 0회 | `main.ts` 부팅에서 `import('./private')` 즉시 호출 / 공개 화면 모듈에서 `openLogin` 직접 호출 / 타이머로 `openLogin` 호출 / `#/kana/<하위>` 적용 시 `openLogin` 호출 / abort 뒤에도 세션 요청 시작 | `login-entry.test.ts` 부팅·늦은 응답 단정, `demo-isolation.test.ts` (a) |
| 15 | API 프로세스에 분석기 미적재 | `services/presentation.py`에서 `app.furigana` import | `test_module_boundaries.py` G14(b), `test_no_provider_in_request_path.py` |
| 16 | 토글·가나·demo가 요청·event를 만들지 않음 | `setFuriganaOn`에서 event endpoint 호출 | `furigana.test.ts` 요청 0건, `demo-isolation.test.ts` (b) |
| 17 | `rt` 뺀 텍스트 = 원문, ruby가 span 경계 안, 토글이 재렌더 없음 | 렌더러가 `rt` 없이 읽기를 text에 붙임 / 토글이 문장을 다시 렌더 / 정렬의 경계 검사(4) 제거 | `segments.test.ts`, `furigana.test.ts`, `test_ruby_alignment.py` 경계 |
| 18 | localStorage는 `local-store.ts`만, 세 key만, 예외에도 동작 | 화면 모듈에서 `localStorage` 직접 접근 / `globalThis['local' + 'Storage']` 접근 / 네 번째 key 추가 / 같은 key로 `localSlot` 두 번 / private 그래프에서 `localSlot('nc.demo.v1', ...)` / `write`의 try/catch 제거 / `isValid`의 범위 검사 제거 | `local-storage-scope.test.ts`, `local-store.test.ts`, `demo-progress.test.ts` |
| 19 | migration additive, backfill 가드 | migration에 기존 컬럼 삭제 추가 / backfill `--apply`에서 백업 단계 건너뛰기 / UPDATE 재조건 제거 | `test_migrations.py`, `test_backfill_ruby.py` 백업 강제·동시 실행 |
| 20 | fixture 재생성 일치 | 커밋된 fixture의 한 글자 수정 | `test_demo_fixture.py` 재생성 일치 |

불변식 20의 "Learning Engine·FSRS·mastery를 프론트엔드에 복제하지 않는다"는 코드 변이로 관측하기 어렵다. 이
부분은 learning-verifier와 scope-guard 게이트의 리뷰로 확인한다.
