# ADR-022 --- 선택 홈, 로그인 진입, 공개 화면 격리 경계

Status: Accepted

Decision: 부팅은 **어떤 경우에도 API를 부르지 않는다.** 공개 화면(홈·demo·가나)은 hash route이고
`hashchange`로 오간다. 로그인 영역(로그인 폼·학습·기록)은 hash가 없고, **상단바 `로그인`을 눌렀을 때
`main.ts`의 동적 import 한 곳**으로만 들어간다. `fetchMe`는 그 영역 안에만 있다. 격리는 TypeScript
컴파일러 AST로 만든 import 그래프(정적 + 리터럴 동적)로 검사하고, 비리터럴 `import()`는 저장소
전체에서 금지한다. localStorage는 `src/local-store.ts` 한 모듈이 세 개의 버전 key만 다룬다.

``` text
부팅               src/main.ts         라우터 시작. fetchMe 없음. import('./private') 한 곳
공개 route         src/routes.ts       ''·'#/' 홈(정적) | '#/demo' | '#/kana'(하위 포함)   hashchange
                   모르는 hash          홈
로그인 영역        src/private.ts      fetchMe -> 학습 | 401 -> 로그인 폼. hash route 없음 -> 새로고침 = 홈
공개 화면 모듈     src/home/  src/demo/  src/kana/     api.ts·endpoints.ts·env.ts·private.ts에 닿지 않는다
격리 검사          (a) main.ts 정적 그래프  (b) home·demo·kana 정적+리터럴 동적 그래프
                   (c) API에 닿는 동적 import는 main.ts의 1곳  (d) 비리터럴 import()·import.meta.glob 금지
                   (e) entry chunk에 API base URL 없음  (f) e2e frontend origin 밖 요청 0건
                   + 네트워크 원시 API·import.meta.env·HTML 삽입 API·저장소 API의 위치 제한
localStorage       src/local-store.ts  nc.furigana.v1 / nc.kana.v1 / nc.demo.v1   key별 타입 slot, try/catch + 메모리
전환·시트          src/ui/screen.ts  src/ui/sheet.ts  src/ui/topbar.ts  토큰은 src/styles.css
후리가나 토글      src/ui/furigana.ts  documentElement class 전환. 문장을 다시 그리지 않는다
```

`spec/`에 반영하기 전까지 구현 근거가 아니다(사용자 결정 2026-09-13).

---

## 맥락

사용자 결정(2026-09-13, `updates/U-001-ui-ux-overhaul/request.md`, `updates/U-003-furigana.md`,
`updates/U-004-kana-learning.md`, `updates/U-005-demo-expansion.md`와 그 요청서들의 불변식 13·14·16·18)은 확정이다.

지금 구조(`frontend/src/main.ts`):

``` text
main.ts --정적--> api.ts, endpoints.ts, demo/demo.ts, ui/login.ts, ui/study.ts, ui/history.ts
boot(): if hash == '#/demo' -> demo  (fetchMe보다 먼저)
        else fetchMe() -> study | 401 -> login(안에 demo 진입 버튼)
hashchange를 듣지 않는다
```

-   entry 모듈이 API client를 **정적으로** import한다. demo는 `demo/demo.ts`에서 시작한 그래프가 API에
    닿지 않을 뿐, 같은 번들에서 API 모듈이 부팅 때 평가된다. 불변식 13("import하지 않는다")을 route
    단위로 말할 수 없다.
-   "demo가 fetchMe보다 먼저 갈린다"는 **분기 순서**로 지켜진다. 홈과 가나가 더해지면 분기가 셋이 되고,
    그 순서 하나를 틀리면 요청이 나간다. 불변식 14는 순서가 아니라 구조로 지켜야 한다.
-   `tests/unit/demo-isolation.test.ts`는 정규식으로 import를 찾는다. 리터럴 `import('./x')`는 잡지만
    `import('../' + 'api')` 같은 조합은 못 잡는다(`updates/backlog.md` #35, MVP-02에서 해소).

### 실측: 빌드 산출물로 검사할 수 있는가 (Vite 8.3.0, 저장소 밖 임시 환경의 소형 프로젝트)

``` text
구성      main.ts -> import('./demo/demo'), import('./private-app')
          private-app -> private.ts, history.ts -> api.ts -> env.ts
manifest  entry·dynamic entry 단위의 imports / dynamicImports만 적힌다
          api.ts·env.ts는 private-app 청크에 **인라인되어 manifest 어디에도 이름이 없다**
          두 dynamic entry가 api.ts를 공유하면 api 청크가 따로 생긴다 (entry 청크로 올라가지 않았다)
조합 import  import('./' + name) -> 경고 없이 빌드 성공, 청크도 manifest 항목도 생기지 않는다
AST 시제품  typescript(이미 devDependency, 6.0.3)의 createSourceFile로
          정적/리터럴 동적 import와 비리터럴 import()·import.meta.glob 위반을 모두 찾았다
```

빌드 산출물은 "어느 모듈이 어느 route에서 닿는가"를 담지 않고, 조합 import는 산출물에서 **보이지
않는다.** 그래서 1차 검사는 소스 AST다(`결정 2`).

---

## 결정 1 --- route와 모듈 배치

### route 표

``` text
hash                      화면        적재           API
''  '#/'                  홈          정적           없음
'#/demo'                  demo        동적 import    없음
'#/kana'  '#/kana/<sub>'  가나 학습   동적 import    없음   <sub>은 kana 레인이 정한다
그 밖(모르는 hash)         홈          정적           없음   history.replaceState로 URL을 '#/'로 바꾼다
(hash 없음)               로그인 폼·학습·기록           private.ts 안에서만
```

-   **서버 요청 0건의 "서버"는 API origin이다.** 공개 route에 들어갈 때 frontend origin에서 청크·아이콘·
    manifest를 받는 것은 정적 자산이며 여기에 들지 않는다. 기존 demo e2e가 `api_calls`와 `foreign`을
    갈라 세는 그 구분이다.
-   **demo fixture의 동적 import(`updates/U-005-demo-expansion.md`)는 route 단위 동적 import로 충족한다.** `demo/demo.ts`가 fixture를
    정적으로 import해도 그 둘은 홈 번들 밖의 청크다. fixture를 한 번 더 동적으로 나누지 않는다.
-   **가나 라운드 진행 상태는 hash에 두지 않는다.** 하위 hash가 바뀌면 라우터가 kana 화면을 다시 mount
    하므로 메모리 상태가 사라진다. 하위 hash는 메뉴 수준(예: 히라가나/가타카나 선택)에만 쓴다.

### 모듈

``` text
src/main.ts         부팅. 라우터 시작, openLogin 조립. import('./private')가 여기 한 곳에만 있다
src/routes.ts       공개 route 표, navigate(), hashchange 리스너 (hashchange를 듣는 유일한 곳)
src/home/           선택 홈 (main.ts 정적 그래프 안)
src/demo/           demo 화면, fixture, demo 전용 상수
src/kana/           가나 데이터·퀴즈·화면
src/private.ts      enterPrivate(): fetchMe -> ui/study | 401 -> ui/login.
                    ui/login·study·history·logout, api·endpoints·env는 여기서부터만 닿는다
src/ui/screen.ts    showScreen()             화면 교체 (결정 4)
src/ui/sheet.ts     openSheet()              바텀시트 (결정 4)
src/ui/topbar.ts    renderTopBar()           상단바 레이아웃. 동작은 주입받는다
src/ui/furigana.ts  후리가나 설정·토글 (결정 5)
src/local-store.ts  localStorage 단일 모듈 (결정 3)
```

-   기존 `ui/login.ts`, `ui/study.ts`, `ui/history.ts`, `ui/logout.ts`는 자리를 옮기지 않는다. 그 파일들은
    `private.ts`에서만 닿으면 되고, 옮기는 diff는 이 결정이 요구하지 않는다.
-   `private.ts`를 디렉터리로 만들지 않는다. 새로 생기는 파일이 하나다.

### 부팅과 이동

``` text
boot           applyRoute(location.hash)  -- fetchMe를 부를 수 없다: main.ts 정적 그래프에 endpoints가 없다
hashchange     applyRoute(location.hash)  -- 지금 화면(로그인 영역 포함)의 signal을 abort하고 새로 mount
navigate(h)    ''와 '#/'를 같은 홈으로 본다
               location.hash가 이미 h면 applyRoute(h)를 직접 부른다 (hashchange가 오지 않으므로)
               아니면 location.hash = h  (applyRoute는 hashchange에서)
openLogin()    0 사용자 이벤트 핸들러(상단바 로그인 버튼의 click) 안에서만 불린다
               1 지금 화면의 signal을 abort하고 새 signal을 만든다
               2 hash가 비어 있지 않으면 history.replaceState로 hash를 지운다 (hashchange 없음)
                 -> 로그인 영역에서 새로고침하면 홈이 뜬다 (Wave 1 보완 결정, 2026-09-13)
               3 const { enterPrivate } = await import('./private')
                 실패(청크 적재 실패, 오프라인, 배포로 옛 청크가 사라짐) -> 홈 자리에 안내 문구만 보인다
                   예: "로그인 화면을 불러오지 못했어요. 위의 로그인을 다시 눌러 주세요."
                   [다시 시도하기] 버튼을 두지 않는다. 다시 시도는 상단바 로그인 버튼이 한다
                   (openLogin 호출 위치를 ui/topbar.ts의 click 리스너 한 곳으로 유지하기 위해서다)
               4 signal.aborted면 멈춘다. 아니면 enterPrivate({ root, signal, goHome: () => navigate('#/'), openLogin })
                 openLogin은 실패 화면 상단바의 로그인에 값으로만 넘긴다 (Wave 2 보완 결정, 2026-09-13)
로그아웃       goHome()
```

-   **불변식 14는 검사와 런타임 단정으로 지킨다.** `fetchMe`를 부를 수 있는 모듈은 `private.ts` 그래프 안에만
    있고, 그 그래프로 들어가는 간선은 `openLogin`의 동적 import 하나다(`결정 2`의 (a)(c)). 분기 순서를
    틀려서 요청이 나가는 경로는 이 검사가 막는다. 다만 정적 검사는 **`openLogin`이 언제 불리는가**를 보지
    못한다(부팅에서 바로 부르거나 타이머로 부르면 그래프는 그대로인데 요청이 나간다). 그래서 두 가지를 더한다.
    -   `openLogin` 호출은 `ui/topbar.ts`의 로그인 버튼 `click` 리스너 콜백 안 한 곳뿐이다(AST 검사). 공개
        화면 모듈과 `main.ts`는 그 함수를 `renderTopBar`에 넘기기만 하고 부르지 않는다.
    -   런타임 단정(`결정 2`)이 부팅 뒤 가짜 타이머를 끝까지 진행해도 fetch 0회임을 확인한다.
-   **로그인 영역 안의 이동(로그인 -> 학습 -> 기록)은 지금처럼 콜백**이고 hash를 바꾸지 않는다.
-   **뒤로 가기는 공개 route 사이에서만 보장한다(Wave 1 보완 결정, 2026-09-13).** 로그인 영역에서 뒤로 가기를 누르면 이전 기록의
    hash가 다를 때만 `hashchange`가 와서 그 공개 화면으로 간다. 같으면 아무 일도 없다. 로그인 영역에서
    홈으로 가는 길은 상단바 `Nihongo Context`다.
-   **`signal`이 늦게 도착한 응답의 화면 가로채기를 막는다.** `hashchange`를 듣게 되면서 생긴 경합이다.
    `fetchMe` 응답을 기다리는 동안 뒤로 가기로 홈에 가면, 늦게 온 200이 학습 화면을 홈 위에 그릴 수 있다.
    화면을 바꾸는 호출은 전부 `showScreen(root, el, signal)`을 지나고, 그 함수는 `signal.aborted`면 아무것도
    하지 않는다. 학습 화면 내부의 부분 갱신은 자기 `screen` 요소에만 쓰므로 떼어진 뒤에는 보이지 않는다.
-   **`signal.aborted`면 다음 요청도 시작하지 않는다.** 화면 전환만 막으면 늦게 온 `fetchMe` 200이 이어서
    `POST /api/study/session`을 보내 사용자가 떠난 뒤에 study session을 만들거나 resume한다. 그래서 요청을
    시작하는 지점(로그인 영역 진입, `fetchMe` 뒤의 학습 화면 진입, 로그인 성공 뒤의 학습 화면 진입)은 시작
    직전에 `signal.aborted`를 확인하고 abort됐으면 아무것도 하지 않는다.
-   **로그인 영역 안의 화면도 화면마다 `signal`을 가진다(Wave 2 보완 결정, 2026-09-13).** 영역 안 이동은 콜백이라
    `hashchange`가 없으므로 route의 signal 하나로는 학습 → 기록 이동을 "떠남"으로 알 수 없다. `enterPrivate`는 받은
    `signal`에 묶인 화면별 signal을 만들어 학습·기록·로그인·로그인 확인 실패 화면에 넘기고, 화면을 옮기면 이전 화면의
    signal을 abort한다. 요청을 시작하는 지점뿐 아니라 `await` 뒤에도 확인하며, 떠난 화면에 늦게 온 409의 session
    재획득과 401의 Login 이동도 하지 않는다. canonical은 `spec/04_SECURITY_AND_DATA.md`의 `모듈 경계`다.
-   **`beforeunload`/`pagehide`/`visibilitychange`에는 여전히 아무것도 달지 않는다**(기존 `ui/study.ts`
    규칙). abort는 요청을 취소하지 않는다. 떠난 화면의 요청은 끝까지 가고, 결과만 그리지 않는다.
-   **떠난 화면에 늦게 온 `/click` 응답은 설명을 그리지 않고 `explanation_revealed`도 보내지 않는다(Wave 1 보완 결정, 2026-09-13).**
    item을 탭한 뒤 응답 전에 화면을 떠나 `signal`이 abort됐으면 그 응답으로 설명 내용을 만들지 않는다. 그
    presentation에는 `item_clicked`만 남는다. "탭했으나 설명이 표시되지 않은 경우"를 `item_clicked`만으로
    구분한다는 `05_API_SPEC.md`의 기존 규칙 그대로다. 떼어진 DOM에 그린 뒤 보내면 사용자가 보지 않은 설명이
    "표시됐다"로 기록된다.
-   상단바는 모든 화면에 있다(Wave 1 보완 결정, 2026-09-13). 공개 화면은 `onLogin`을 넘겨 상단바가 `로그인` 버튼을 만들게 한다.
    로그인 영역의 메뉴(학습 기록, 로그아웃, 후리가나 토글)는 **그 영역이 만든 요소를 `actions`로 넘긴다.**
    `ui/topbar.ts`는 `ui/logout.ts`를 import하지 않는다(그러면 공개 그래프가 API에 닿는다).
-   로그인 폼 안의 demo 진입 버튼을 없앤다(Wave 1 보완 결정, 2026-09-13). `mountLogin`의 `onOpenDemo` 인자가 사라진다.

### PWA `start_url`

`manifest.webmanifest`의 `start_url: "/"`와 `scope: "/"`는 **바꾸지 않는다.** `/`가 곧 홈이 되므로 설치한
앱을 열면 API 요청 없이 홈이 뜬다. 사용자(계정 주인)는 앱을 열 때마다 `로그인`을 한 번 누른다. 쿠키가
유효하면 곧바로 학습 화면이고 열린 세션은 resume된다.

`backend/tests/e2e/test_pwa_installable.py`의 `_NO_API_ROUTE = "#/demo"`는 "루트는 `/me`를 부른다"는
전제가 사라지므로 `/`로 바꿀 수 있다(shell 레인).

---

## 결정 2 --- 격리 검사: TypeScript AST import 그래프

### 도구

`frontend/node_modules/typescript`(이미 devDependency)의 `ts.createSourceFile` + `ts.forEachChild`로 vitest
안에서 그래프를 만든다. **새 의존성이 없다.**

``` text
정적 간선    ImportDeclaration, ExportDeclaration(from)의 문자열 모듈 지정자. import type도 센다(더 엄격)
동적 간선    CallExpression(expression = ImportKeyword)이고 인자가 정확히 1개의 StringLiteral 또는
             NoSubstitutionTemplateLiteral
해석         상대 경로만. base, base.ts, base/index.ts 순. 존재하는 .css 파일은 그래프에서 뺀다
             **fail-closed:** 풀리지 않는 상대·루트 지정자(없는 파일, `./api.js`처럼 확장자가 다른 것),
             `?` 쿼리가 붙은 지정자(`?worker`, `?raw`, `?url` 등), bare 지정자(패키지)는 전부 위반이다
API_MODULES  api.ts, endpoints.ts, env.ts
PRIVATE      private.ts
```

### 검사 항목

``` text
(d) src/ 전체   다음이 하나라도 있으면 실패
                 - import() 인자가 문자열 리터럴 1개가 아니다 (연결, 변수, 템플릿 치환, 인자 2개)
                 - 위 `해석`의 fail-closed 위반 (정적·동적 모두)
                 - import.meta.glob (정적 이름으로도 동적 import를 만든다)
                 - import.meta.env 가 env.ts 밖에 있다
                 - fetch, XMLHttpRequest, navigator.sendBeacon, WebSocket, EventSource 가 api.ts 밖에 있다
                 - new Worker / new SharedWorker (별도 그래프의 진입점이 된다)
                 - eval, Function 생성자, require() (문자열·런타임 해석으로 코드를 만든다)
                 - document.createElement의 인자가 'script'이거나 문자열 리터럴이 아니다
                 - setTimeout / setInterval의 첫 인자가 함수가 아니다 (문자열 코드 실행)
                 - innerHTML, outerHTML, insertAdjacentHTML, document.write, document.writeln,
                   Range.createContextualFragment, DOMParser.parseFromString, iframe의 srcdoc
                   (HTML 삽입. DOM은 textContent와 요소 생성으로만 만든다)
                 - setAttribute로 on* 속성·srcdoc·href·src에 값을 넣는다 (리터럴 상수가 아닌 값이면 위반.
                   on*·srcdoc은 리터럴이어도 위반)
                 - location.href 대입, location.assign, location.replace, window.open, <a>의 href 대입에
                   동적 값을 넣는다 (routes.ts의 고정 route 상수만 허용)
                 Wave 2 보완 결정(2026-09-13)으로 더한 항목(createElementNS, setAttributeNS, URL 속성 대입,
                 다단계 전역 객체 접근)은 spec/04_SECURITY_AND_DATA.md의 격리 검사 (d)가 canonical이다
(a) main.ts     정적 그래프에 API_MODULES와 PRIVATE가 없다
(b) src/home/ src/demo/ src/kana/ 의 모든 모듈
                정적 + 리터럴 동적 그래프에 API_MODULES와 PRIVATE가 없다
(c) src/ 전체   PRIVATE의 정적 그래프 밖에서, 대상의 정적 + 동적 그래프가 API_MODULES에 닿는
                동적 import는 정확히 1개이고, main.ts에 있으며 대상이 PRIVATE다.
                main.ts 정적 그래프 안의 리터럴 동적 import는 PRIVATE이거나 home·demo·kana 아래 모듈이다
양성 대조군    PRIVATE의 그래프에 endpoints.ts가 있다.
                (d)의 판정 함수가 합성 소스 문자열의 변이를 전부 위반으로 낸다:
                import('../' + 'api'), import.meta.glob, import('../api.js'), import('../x?worker'),
                demo 모듈의 fetch 호출, innerHTML 대입, setTimeout('code'), createElement('script')
(e) dist        현재 소스로 빌드한 dist/index.html의 module script(entry 청크)에 API base URL 문자열이 없다.
                dist/assets의 어떤 청크에는 있다(양성 대조군)
(f) e2e         API origin에 아무도 listen하지 않는 구성에서 '', '#/demo', '#/kana'를 각각 열고 조작해도
                **frontend origin 밖으로 나가는 요청 0건**(API origin과 제3자 origin 모두).
                상단바 로그인을 누르면 GET /api/auth/me 요청이 1건 나간다
```

-   **(b)는 디렉터리 기준이다.** route 진입 모듈 이름을 테스트에 적지 않는다. kana 레인이 파일을 더해도
    테스트를 고치지 않는다.
-   **(c)의 두 번째 줄이 (b)의 우회를 막는다.** `routes.ts`에 `import('./ui/study')` 같은 route를 넣으면
    그 대상이 home·demo·kana 밖이므로 실패한다.
-   **(d)가 조합 import를 원천 차단한다.** 조합을 "해석해서 따라가는" 대신 쓰지 못하게 한다. 저장소에
    조합 import가 필요한 곳이 없다. `import.meta.glob`도 같은 이유로 막는다(kana 데이터는 명시적 import).
-   **(e)를 둔다.** 소스 그래프가 보지 못하는 것은 번들러 설정이다(`manualChunks`, 동적 import 인라인
    옵션 등이 API 코드를 entry 청크로 합칠 수 있다). `no-service-worker.test.ts`가 이미 현재 소스로 dist를
    다시 빌드하므로 추가 비용은 파일 읽기다. 그 빌드 신선도 함수를 공용 helper로 옮겨 함께 쓴다. unit
    빌드는 `VITE_API_BASE_URL` 없이 돌므로 찾는 문자열은 `env.ts`의 기본 origin이다
    (`no-hardcoded-origin.test.ts`가 그 리터럴이 `env.ts`에만 있음을 이미 보장한다).
-   **런타임 단정(vitest)도 둔다.** `main.ts`를 `''`, `'#/'`, `'#/demo'`, `'#/kana'`, `'#/kana/<하위 경로>'`,
    `'#/unknown'`으로 부팅하고 **가짜 타이머를 끝까지 진행해도** 던지는 `fetch` 스텁이 불리지 않는다. 상단바
    `로그인`을 누르면 정확히 1회 불린다. 기존
    `demo-route.test.ts`의 방식이다. 정적 검사는 "코드에 없다"를, 런타임은 "그래서 안 나간다"를 말한다.
-   기존 `demo-isolation.test.ts`의 `keeps demo state out of every persistent store`는 `결정 3`의 규칙으로
    바뀐다(demo가 이제 localStorage를 쓴다).
-   **URL에서 온 값은 화면에 그대로 내지 않는다.** hash의 하위 경로(`subpath`)는 화면 모듈이 가진 고정 허용
    목록과 **비교만** 하고, 목록에 없으면 기본 화면으로 간다. 그 문자열을 `textContent`로도 출력하지 않는다.
    (d)의 HTML 삽입 금지와 함께 URL 조작으로 화면에 임의 내용을 넣는 경로를 없앤다.
-   **CSP(Content-Security-Policy)는 이번 범위에서 두지 않는다.** CSP의 `connect-src`에는 API origin이
    들어가야 하는데 이 저장소는 API origin을 코드·설정 파일에 적지 않고 빌드 셸 환경변수로만 주입한다
    (ADR-020 결정 5·6). 정적 호스팅의 응답 헤더에 그 값을 주입하는 설계가 따로 필요하다. 그때까지 스크립트
    주입 방어는 (d)의 AST 금지 목록이 맡는다. 후속 과제로 `updates/backlog.md`에 기록한다.

---

## 결정 3 --- localStorage: `src/local-store.ts` 한 모듈

### key 표

``` text
key              값 형식을 정하는 곳        저장하는 것
nc.furigana.v1   src/ui/furigana.ts         {"on": boolean}
nc.kana.v1       src/kana/ (kana-core)      글자·단어별 맞음/틀림 수, 전체 마지막 학습 시각 (`updates/U-004-kana-learning.md`)
nc.demo.v1       src/demo/ (demo)           fixture 식별자, 현재 위치, 표현별 자기평가, 다시 보기 대기열,
                                            본 문장 수 (`updates/U-005-demo-expansion.md`)
```

-   **네임스페이스 `nc.`, 끝에 형식 버전.** 형식을 호환되지 않게 바꾸면 key 이름의 버전을 올린다
    (`nc.demo.v2`). 옛 key는 옮기지 않는다.
-   **fixture가 바뀐 경우는 key 버전이 아니라 값 안의 fixture 식별자로 판정한다.** 식별자는 fixture 생성
    스크립트가 fixture 내용에서 결정적으로 만든다. 다르면 조용히 처음부터(`updates/U-005-demo-expansion.md`).
-   후리가나 설정은 로그인 학습 화면과 demo가 **하나를 공유한다**(Wave 1 보완 결정, 2026-09-13).

### 인터페이스

임의 key·임의 값을 쓰는 함수를 export하지 않는다. key마다 **그 값의 타입과 검사 함수를 가진 slot**을 key의
주인 모듈이 한 번 만든다.

``` ts
export const LOCAL_STORE_KEYS = ['nc.furigana.v1', 'nc.kana.v1', 'nc.demo.v1'] as const
export type LocalStoreKey = (typeof LOCAL_STORE_KEYS)[number]

export type LocalSlot<T> = {
  /** 없거나, 읽을 수 없거나, JSON이 아니거나, isValid가 거르면 undefined. 던지지 않는다. */
  read: () => T | undefined
  /** isValid를 통과한 값만 메모리에 쓰고 localStorage에 시도한다. 실패해도 던지지 않는다. */
  write: (value: T) => void
  /** 진도 초기화. 메모리와 localStorage 둘 다에서 지운다. 던지지 않는다. */
  remove: () => void
}

/** key 인자는 문자열 리터럴이어야 한다(AST 검사). 같은 key로 두 번 만들면 던진다. */
export function localSlot<T>(key: LocalStoreKey, isValid: (value: unknown) => value is T): LocalSlot<T>
```

``` text
메모리 Map     페이지가 살아 있는 동안의 기준값
read           Map에 있으면 그 값. 없으면 try { getItem -> JSON.parse } -> isValid -> Map에 넣고 반환
               예외(접근 거부, SecurityError, 파싱 실패), null, isValid 실패 -> undefined (조용히 처음부터)
write          isValid(value)가 false면 아무것도 하지 않는다
               Map.set 후 try { setItem(JSON.stringify) } catch {}   (용량 초과, 사생활 모드)
remove         Map.delete 후 try { removeItem } catch {}
slot 소유      nc.furigana.v1 -> src/ui/furigana.ts   nc.kana.v1 -> src/kana/ 한 모듈   nc.demo.v1 -> src/demo/ 한 모듈
```

-   **`isValid`는 형식만이 아니라 값 범위와 소속까지 본다.** 형식이 맞아도 값이 틀리면 조용히 초기화한다.

    ``` text
    furigana   {"on": boolean} 이고 다른 키가 없다
    kana       글자·단어 key가 정적 가나 데이터에 있는 것뿐이다. 맞음/틀림 수는 0 이상의 안전한 정수다.
               마지막 학습 시각은 유한한 수다
    demo       fixture 식별자가 지금 fixture와 같다. 현재 위치는 0 이상 문장 수 이하의 정수다.
               자기평가·다시 보기 대기열·본 문장 수가 가리키는 문장·표현은 지금 fixture에 있고 값은 허용값 안이다
    ```

-   **저장이 안 되는 브라우저에서도 그 페이지 안에서는 진도가 이어진다.** 새로고침하면 사라진다. 불변식
    18의 "저장이 없어도 정상 동작"이다.
-   **넣지 않는 것:** secret, 쿠키 값, 로그인 여부, 서버 응답(API의 id·문장·설명). demo·kana가 저장하는 id는
    정적 데이터의 id다. 로그인 영역은 후리가나 설정만 읽고 쓴다.
-   **검사(AST):**
    -   `localStorage` 식별자는 `src/local-store.ts`에만 나온다.
    -   `sessionStorage`, `indexedDB`, `caches`, `document.cookie`, `window.name`, `navigator.storage`는 `src/`
        어디에도 없다. `history.pushState`/`history.replaceState`의 state 인자는 `null`만 허용한다.
    -   **계산된 속성 접근을 막는다.** `globalThis`, `window`, `self`, `document`, `navigator`, `history`,
        `location`에 대한 `[...]` 접근은 금지다(`globalThis['local' + 'Storage']` 같은 문자열 조각 우회). 문자열
        리터럴 안의 `Storage`, `cookie`, `indexedDB` 조각도 `local-store.ts` 밖에서는 위반으로 본다.
    -   `localSlot` 호출은 key마다 정확히 한 번이고 위 `slot 소유` 표의 위치에만 있다. key 인자는 문자열 리터럴이다.
    -   **로그인 영역(`private.ts`) 그래프 안의 `localSlot` 호출은 `nc.furigana.v1` 하나뿐이다.**
    -   `LOCAL_STORE_KEYS`가 위 세 개와 같다.
-   **런타임 검사:** 던지는 `localStorage` 스텁에서 read가 undefined, write가 던지지 않고, 같은 페이지의 다음
    read가 쓴 값을 돌려준다. 범위 밖 값(음수 횟수, 없는 글자 key, 다른 fixture 식별자, 문장 수를 넘는 위치)을
    넣어 두면 read가 undefined다.
-   세 key를 **Wave 2에서 한꺼번에** 넣는다. Wave 3 레인(furigana-fe, demo, kana-ui)은 이 파일을 고치지
    않는다. 어느 Wave 2 레인이 만드는지는 구현 작업 분담에서 정한다.

---

## 결정 4 --- 화면 전환과 시트의 구현 경계

값(duration, easing, 화면 진입 이동 거리 10px, reduced-motion 대체)과 무엇을 시트로 보여주는가는
`spec/mvp-01-core/03_UI_UX_SPEC.md`의 `화면 전환과 시트` 절이 canonical이다. 참고 관찰 기록
(`updates/U-001-ui-ux-overhaul/refs/guitar-riff-motion.md`)의 수치는 근거일 뿐이며 명세와 다르면 명세를 따른다.
이 ADR은 **어디에 두고 무엇이 무엇을 기다리지 않는가**만 정한다.

``` text
src/styles.css    :root motion 토큰, @media (prefers-reduced-motion: reduce) 안의 토큰 치환
src/ui/screen.ts  showScreen(root, screen, signal)
src/ui/sheet.ts   openSheet(options) -> SheetHandle
src/ui/topbar.ts  renderTopBar(options)
```

``` ts
export function showScreen(root: HTMLElement, screen: HTMLElement, signal: AbortSignal): void
// signal.aborted면 아무것도 하지 않는다. replaceChildren -> 진입 class -> 맨 위로 즉시 스크롤 -> 제목 focus

export type SheetHandle = { close: () => void }
export function openSheet(options: {
  container: HTMLElement            // 시트를 붙일 화면 요소. 화면이 떼어지면 시트도 함께 사라진다
  title: string
  body: HTMLElement                 // 열 때 만든 item 설명 내용. 숨겨 둔 노드를 재사용하지 않는다
  returnFocusTo: HTMLElement | null
  onClose?: () => void
}): SheetHandle

export function renderTopBar(options: {
  onHome: () => void
  onLogin?: () => void              // 있으면 오른쪽에 로그인 버튼. click 리스너 안에서만 부른다
  actions: HTMLElement[]
}): HTMLElement
```

-   **움직임은 CSS뿐이다.** 애니메이션 라이브러리, View Transitions API, JS `matchMedia` 분기를 쓰지 않는다.
    reduced-motion은 미디어 쿼리 안에서 토큰을 바꾸는 것으로 끝난다.
-   **논리 상태는 애니메이션 이벤트를 기다리지 않는다.** 화면 교체는 즉시 DOM을 바꾸고 나가는 화면을
    애니메이션하지 않는다. 시트를 닫으면 포커스 복귀, `inert`, 다음 조작 가능이 즉시 일어나고, 시각적
    숨김만 `transitionend`에서 한다. 그 이벤트가 오지 않아도(reduced-motion, 테스트의 가짜 DOM) 조작이
    막히지 않는다.
-   **`explanation_revealed`는 떠나지 않은 학습 화면의 DOM에 설명 내용이 삽입된 직후에 보낸다(Wave 1 보완 결정, 2026-09-13).**
    삽입 직전에 그 화면의 `signal`이 abort되지 않았음을 확인한다(`결정 1`의 늦은 `/click` 응답). 올라오는
    애니메이션의 끝이 아니다. 끝을 기다리면 애니메이션이 끊기거나 이벤트가 오지 않는 환경에서 event가 사라지고, 같은
    설명이 환경에 따라 기록되거나 안 되는 상태가 된다. `05_API_SPEC.md`의 "실제로 렌더된 직후"를 이 뜻으로
    못박는다. 목업이나 다른 문서의 문구가 다르면 이 정의가 canonical이다.
-   **설명 시트를 닫고 같은 표현을 다시 탭해도 `item_clicked`와 `explanation_revealed`는 presentation +
    item당 1회다(Wave 1 보완 결정, 2026-09-13).** 두 번째부터는 이미 받은 설명으로 시트 내용을 다시 만들어 보여주고 `/click`을
    다시 부르지 않는다. 시트가 열 때마다 내용을 만든다는 규칙과 부딪히지 않는다 --- 다시 만드는 재료가
    메모리의 응답이다. 매번 `/click`을 부르면 raw history가 학습 신호가 아니라 시트 여닫기 횟수를 센다.
-   **시트는 item 설명에만 쓴다(Wave 1 보완 결정, 2026-09-13).** 문장 번역은 시트가 아니라 **문장 바로 아래 인라인 펼침**이고,
    확인·오류도 시트가 아니다. `openSheet`의 호출자는 설명 패널 하나다.
-   **번역 펼침 영역은 reveal 응답을 받은 뒤에 DOM을 만든다.** 번역을 미리 DOM에 숨겨 두고 펼치는 구조를
    만들지 않는다(기존 `translation_revealed` 규칙). 펼침 움직임도 CSS뿐이고 응답 표시가 transition 끝을
    기다리지 않는다.
-   **문서 수준 리스너는 `routes.ts`의 `hashchange` 하나다.** 시트의 Esc는 시트 요소에 단다(열 때 포커스가
    시트 안으로 들어가므로 키 이벤트가 거기로 온다). 화면이 떼어지면 리스너도 함께 사라져 정리 코드가
    필요 없다.
-   화면 모듈은 `root.replaceChildren`을 직접 부르지 않고 `showScreen`을 쓴다(`결정 1`의 `signal`).

---

## 결정 5 --- Wave 2·3 병렬을 위한 확장점

### 공개 route 등록 (`src/routes.ts`)

``` ts
export type PublicScreenContext = {
  root: HTMLElement
  signal: AbortSignal        // 다른 화면으로 가면 abort된다
  subpath: string            // '#/kana/hiragana' -> 'hiragana'. 없으면 ''
  navigate: (hash: string) => void
  openLogin: () => void      // main.ts가 주입한다. 공개 모듈은 private.ts를 모른다
}
export type PublicScreenModule = { mount: (ctx: PublicScreenContext) => void }

type PublicRoute = { prefix: string; load: () => Promise<PublicScreenModule> }
const PUBLIC_ROUTES: PublicRoute[] = [
  { prefix: '#/demo', load: () => import('./demo/demo') },
  // Wave 3 kana-ui가 이 한 줄을 더한다
  // { prefix: '#/kana', load: () => import('./kana/<진입 모듈>') },
]
```

-   홈은 표에 없다. `routes.ts`가 정적으로 import해 기본값으로 쓴다.
-   Wave 2 `shell`이 표와 `#/demo`를 만든다. Wave 3에서 이 파일을 고치는 레인은 `kana-ui` 하나다. Wave 2
    머지 시점에 `#/kana`는 등록 전이라 홈 카드가 홈으로 돌아온다. 배포는 Wave 4 뒤이므로 그 중간 상태를
    가리는 코드를 두지 않는다.
-   기존 `mountDemo(root, onExit)`는 `mount(ctx)`로 바뀐다. 나가는 길은 상단바(`ctx.navigate('#/')`)다.

### 로그인 영역 (`src/private.ts`)

``` ts
export function enterPrivate(ctx: {
  root: HTMLElement
  signal: AbortSignal
  goHome: () => void
  openLogin: () => void   // 실패 화면 상단바의 로그인에 값으로만 넘긴다 (Wave 2 보완 결정, 2026-09-13)
}): void
```

### 공통 문장 렌더러 (`src/ui/segments.ts`, Wave 3 `furigana-fe` 소유)

``` ts
// 시그니처는 바꾸지 않는다
export function renderSentence(segments: RenderSegment[], onTapItem: (id: number) => void): HTMLElement
```

``` text
segment.ruby.length === 0   지금처럼 text만 넣는다
그 밖                       part마다: reading === null -> 텍스트 노드
                                      그 밖            -> <ruby>text<rt>reading</rt></ruby>
                            tappable이면 그 조각들이 <button class="token"> 안에 들어간다
aria-label                  joinSegments(segments) = segment.text만 이은 원문. 읽기를 넣지 않는다
토글 상태                   렌더러는 모른다. <rt>는 **항상** 만들고 CSS가 숨긴다
                            (목업의 "끄면 <rt>를 만들지 않는다" 류 문구와 다르면 이 정의가 canonical)
```

-   타입은 ADR-021 `결정 5`의 `RubyPart`와 `RenderSegment.ruby: RubyPart[]`다. `types.ts`에 이 두 선언을
    Wave 2에서 넣고(기존 demo fixture의 segment에는 `ruby: []`), Wave 3 두 레인은 선언을 고치지 않고
    소비만 한다. 어느 Wave 2 레인이 넣는지는 구현 작업 분담에서 정한다.
-   **불변식 17:** part의 `text`를 이으면 `segment.text`이고(ADR-021 R1), 렌더러는 `text`를 자르거나 잇지
    않으며, tappable 경계는 segment 경계 그대로다. 번역 reveal과 무관하다.

### 후리가나 설정과 토글 (`src/ui/furigana.ts`, Wave 3 `furigana-fe` 소유, `demo`가 병렬로 호출)

``` ts
/** documentElement에 붙는 class. 있으면 .sentence 안의 rt가 보인다. 없으면(기본) 숨긴다. */
export const FURIGANA_ON_CLASS = 'furigana-on'

/** 저장값이 {"on": true}일 때만 true. 없거나 형식이 틀리거나 읽을 수 없으면 false(기본 끔). */
export function isFuriganaOn(): boolean

/** local-store에 쓰고 document.documentElement의 FURIGANA_ON_CLASS를 전환한다.
 *  서버 요청도 learning event도 만들지 않는다. 문장을 다시 렌더링하지 않는다. */
export function setFuriganaOn(on: boolean): void

/** 상단바 actions에 넣는 스위치(<button aria-pressed>). 만들 때 저장값을 문서 class에 적용한다. */
export function renderFuriganaToggle(): HTMLElement
```

-   **class는 `document.documentElement`에 둔다.** Wave 1 보완 결정(2026-09-13)은 "문장을 다시 그리지 않고 CSS class로
    전환한다"까지이고, class를 붙이는 위치는 이 ADR의 구현 결정이다. 다음 문장이 새 요소로 그려져도 상태를 넘길 필요가
    없고, 토글이 문장·interactions handle을 건드리지 않는다. CSS 기본값이 "숨김"이므로 설정을 읽기 전에
    읽기가 번쩍 보이는 일이 없다.
-   **표시 범위는 학습 문장뿐이다(Wave 1 보완 결정, 2026-09-13).** CSS 선택자를 `.sentence rt`로 한정한다. 설명 시트의 예문·
    `canonical_form`·probe 표현에는 ruby 데이터가 없다.
-   **부팅 hook이 없다.** 문장이 있는 화면(학습, demo)은 상단바에 토글을 넣고, 토글을 만들 때 저장값이
    적용된다. `main.ts`를 Wave 3에서 고칠 레인이 생기지 않는다.
-   demo 레인은 `renderTopBar({ onHome, onLogin: ctx.openLogin, actions: [renderFuriganaToggle()] })`처럼 이 시그니처대로
    호출을 작성하고, 머지 순서(furigana-fe -> demo)에 따라 furigana-fe가 들어간 main을 받아 합친다.
-   이 모듈은 공개 그래프(demo) 안에 있으므로 `결정 2`의 (b)가 API import를 막는다.

---

## 버린 대안

-   **정규식 그래프 + "조합 import 금지" grep.** 정규식은 주석·문자열·여러 줄 호출에서 인자를 안정적으로
    가르지 못한다. 필요한 파서(typescript)가 이미 의존성에 있다.
-   **Vite manifest / 청크 그래프를 1차 검사로.** 위 `실측`: manifest는 청크에 인라인된 모듈을 적지 않고,
    조합 import는 산출물에 흔적이 없다. 켜면 `dist/.vite/manifest.json`이 배포 디렉터리 안에 생겨 배포 제외를
    따로 챙겨야 한다.
    청크 내용 grep만 (e)로 남긴다.
-   **esbuild metafile.** Vite 8의 번들러는 rolldown이다. 검사를 위해 별도 esbuild 번들을 만들면 배포
    산출물과 다른 그래프를 검사하게 된다.
-   **로그인 영역에 hash route(`#/study`)를 두고 부팅에서 `fetchMe`.** 불변식 14 위반이다. 새로고침에서
    화면을 되살리는 편의와 맞바꿀 수 없다(Wave 1 보완 결정, 2026-09-13).
-   **지금처럼 로그인 영역을 정적 import하고 분기 순서로 막는다.** entry가 API client를 import하므로 불변식
    13을 import 수준에서 말할 수 없고, 분기가 셋으로 늘면 순서 실수가 곧 요청이다.
-   **`hashchange`를 계속 듣지 않는다.** 공개 route에서 브라우저 뒤로 가기가 화면을 바꾸지 못한다(Wave 1 보완 결정, 2026-09-13).
-   **`openLogin`의 동적 import를 상단바나 홈 모듈에 둔다.** 그 모듈의 그래프가 API에 닿아 (b)가 실패한다.
    동작을 `main.ts`에서 주입받는 것이 기존 `mountDemo(root, onExit)`의 방식이다.
-   **기능마다 storage wrapper.** try/catch·메모리 대체가 세 벌이 되고 key 허용 목록을 한 곳에서 강제할 수
    없다.
-   **sessionStorage / IndexedDB.** sessionStorage는 탭을 닫으면 사라져 "다시 열면 이어서"(`updates/U-005-demo-expansion.md`)가 안 된다.
    IndexedDB는 비동기 API라 저장 불가 시의 메모리 대체와 초기 렌더가 복잡해지고, 저장량이 작다.
-   **토글 시 문장 재렌더링.** Wave 1 보완 결정(2026-09-13)으로 CSS class 전환만 쓴다. tappable 버튼이 새로 만들어져 포커스와 시트의 포커스 복귀 대상이
    사라지고, interactions handle을 다시 묶어야 한다.
-   **`renderSentence`에 `{ furigana: boolean }` 옵션.** 토글 상태를 렌더러까지 끌고 와야 하고, 토글할 때마다
    다시 그려야 한다. CSS class 한 곳이면 렌더러는 상태를 모른다.

---

## 결과와 한계

-   **현재 구현은 이 정의를 지키지 않는다.** `frontend/src/ui/interactions.ts`는 `/click` 응답을 받으면 화면이
    아직 붙어 있는지 보지 않고 `render()` 뒤 `explanation_revealed`를 보낸다. 구현 레인이 `signal` 확인을 넣어
    고친다(테스트: 응답 전에 abort하면 설명 DOM이 없고 `explanation_revealed` 호출 0회).

-   **로그인 영역에서 새로고침하면 홈이다.** 설치한 앱을 열 때도 홈이다. 계정 주인은 매번 `로그인`을 한 번
    누른다. 대신 방문자가 여는 어떤 경로도 API를 부르지 않는다.
-   **로그인 영역의 뒤로 가기는 보장하지 않는다.** standalone PWA에는 뒤로 가기 버튼이 없으므로 상단바가
    유일한 이동 수단이다.
-   **localStorage는 브라우저·설치 형태마다 따로다.** iOS에서 Safari와 홈 화면에 설치한 앱은 저장소를
    공유하지 않는다. WebKit은 설치하지 않은 사이트의 스크립트 저장소를 7일간 상호작용이 없으면 지울 수
    있다. 방문자가 하루쯤 쓴다는 전제(`updates/U-005-demo-expansion.md`)에서는 받아들인다.
-   **격리 검사가 TypeScript의 JS 컴파일러 API에 기댄다.** 그 API가 없는 TypeScript 판(네이티브 구현)으로
    올리면 테스트가 import 단계에서 실패한다. 조용히 통과하지 않는다. 그때 도구를 다시 정한다.
-   **`import.meta.glob`을 저장소 전체에서 쓸 수 없다.** 가나 데이터 파일은 명시적으로 import한다.
-   **글자·AST 검사는 의도적 우회를 다 막지 못한다.** `Reflect.get`, 별칭 변수(`const w = window`),
    `Function` 생성자를 다른 이름으로 얻는 방식 등은 이름 기반 검사를 지난다. 이 검사의 목적은 실수 방지이고,
    그 뒤를 부팅 런타임 단정과 e2e (f)(frontend origin 밖 요청 0건)가 받친다.
-   **(e)는 entry 청크만 본다.** demo·kana 청크의 API 코드 포함 여부는 (b)와 (f)가 맡는다.
-   **배포 직후 열려 있던 탭은 옛 청크 이름으로 동적 import에 실패할 수 있다.** 로그인 영역은 안내 문구만 보이고
    재시도 버튼이 없으므로, 사용자가 상단바 로그인을 다시 누르거나 새로고침해야 한다. 새로고침하면 새 청크를
    받는다. 공개 route에서도 같은 일이 생길 수 있으며 API와 무관하다.
---

## 명세 반영 대상 (spec-sync)

``` text
spec/mvp-01-core/01_USER_FLOW.md   Private Learning 시작을 "상단바 로그인 누름 -> fetchMe"로 (불변식 14).
                                   Public Demo를 홈 카드 경유로. demo 진도는 localStorage(`updates/U-005-demo-expansion.md`)
spec/mvp-01-core/03_UI_UX_SPEC.md  머리 단락(상단바가 모든 화면에), 선택 홈, 로그인 폼의 demo 버튼 제거,
                                   새로고침·뒤로 가기 동작, 전환·시트 규칙(값은 이 문서 `화면 전환과 시트` 절이 canonical), 시트와 event 시점,
                                   후리가나 토글 위치와 표시 범위
spec/mvp-01-core/05_API_SPEC.md    explanation_revealed의 "렌더된 직후" = 떠나지 않은 학습 화면의 DOM에 설명 내용이
                                   삽입된 시점(떠난 뒤 늦게 온 /click 응답이면 보내지 않고 item_clicked만 남는다),
                                   재열기 시 item_clicked·explanation_revealed는 presentation + item당 1회, /click 재호출 없음
spec/mvp-01-core/10_ERROR_HANDLING.md  API 장애와 무관한 범위를 홈·demo·가나로, 동적 import 적재 실패 안내
spec/04_SECURITY_AND_DATA.md       Public Demo 구조를 세 공개 route로 확장, 동적 import 리터럴 규칙,
                                   네트워크 원시 API·import.meta.env·HTML 삽입 API 위치 제한, URL 값 비출력,
                                   CSP는 범위 밖(이유), localStorage 규칙(key 표, slot, 값 범위 검증,
                                   넣지 않는 것, 저장 불가 시 동작)
spec/02_ARCHITECTURE.md            frontend 모듈: main.ts, routes.ts, private.ts, home/, kana/, local-store.ts
spec/mvp-02-onboarding/12_TEST_PLAN.md  결정 2의 (a)~(f)와 변이 양성 대조군(.js 확장자, ?worker 포함),
                                   부팅 런타임 단정(하위 경로, 가짜 타이머), openLogin 호출 위치,
                                   abort 뒤 다음 요청 없음, local-store 검사(계산된 속성 접근, 값 범위),
                                   설명 시트 재열기 1회
spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md
updates/backlog.md                 #35(동적 import 누락) 해소 수단: 결정 2의 (c)(d)
```
