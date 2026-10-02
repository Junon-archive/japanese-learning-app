# ADR-025 --- 언어 선택 홈, route 중첩, 브라우저 TTS

Status: Accepted (결정 2의 `묻는 조건` 개정 2026-10-02 --- 그 `개정` 절이 본문보다 우선한다)

Decision: 첫 화면을 **언어 선택 홈**으로 바꾸고 공개 route를 한 단계 중첩한다(`#/ja/demo`). 기존
`#/demo`·`#/kana`는 일본어 쪽으로 **replaceState 리다이렉트**한다. demo 진도 localStorage key는
언어별로 갈라 네 개가 된다. 소리는 **브라우저 내장 `speechSynthesis`**로만 내고, **`localService`
음성만 쓴다** --- 네트워크 음성을 쓰면 공개 화면이 외부로 요청을 보내게 되어 격리 검사 (f)가
깨진다. 재생은 영어 전용이고 **학습 신호가 아니다**(불변식 25. 불변식 16의 목록에 한 줄을 더한다).

``` text
route
  ''  '#/'                     언어 선택 홈        정적
  '#/ja'                       일본어 홈           정적
  '#/ja/demo'                  일본어 demo         동적 import
  '#/ja/kana'  '#/ja/kana/<s>' 가나 학습           동적 import
  '#/en'                       영어 홈             정적
  '#/en/demo'                  영어 demo           동적 import
  '#/demo' '#/kana' '#/kana/<s>'  -> replaceState로 '#/ja/...' (한 번, hashchange 없음)
  그 밖의 hash                 언어 선택 홈        replaceState로 '#/'

localStorage (네 개)
  nc.furigana.v1   후리가나 설정 (일본어 전용)      변경 없음
  nc.kana.v1       가나 진도                        변경 없음
  nc.demo.ja.v1    일본어 demo 진도                 nc.demo.v1에서 개명. 옛 값은 옮기지 않는다
  nc.demo.en.v1    영어 demo 진도                   신규

소리
  구현        window.speechSynthesis + SpeechSynthesisUtterance.  새 의존성 없음
  음성 선택   lang이 'en'으로 시작하고 voice.localService === true 인 것만.  'en-US' 우선
  없으면      재생 버튼을 그리지 않는다 (비활성으로 두지 않는다)
  위치        영어 Study Screen의 문장, 설명 시트의 example_sentence, 영어 demo의 같은 두 자리
  일본어      재생 버튼이 없다
  학습 신호   아니다. event·exposure·mastery를 만들지 않는다 (불변식 25)
  접근 경계   frontend/src/ui/speech.ts 한 모듈에만 speechSynthesis 식별자가 있다 (AST 검사)
```

`spec/`에 반영하기 전까지 구현 근거가 아니다(사용자 결정 2026-10-01).

---

## 맥락

사용자 결정(2026-10-01):

-   첫 화면에서 **언어를 먼저 고르고 언어별 홈으로** 간다. 로그인 후에도 학습 시작 전 같은 선택을
    거친다.
-   **브라우저 내장 TTS를 추가**한다. 서버 TTS와 오디오 파일 저장은 하지 않는다.
-   듣기는 **재생 버튼만**이고 학습 신호가 아니다. `listening_mastery`는 계속 NULL이다.

MVP-02가 만든 구조(ADR-022)는 공개 route가 평면 셋(`#/`, `#/demo`, `#/kana`)이고 `#/kana`만
하위 경로를 받는다. 언어가 둘이 되면 평면으로는 `#/demo-en` 같은 이름이 생기고, 세 번째 언어나
영어 쪽 보조 화면이 붙는 순간 이름 규칙이 무너진다.

MVP-01·MVP-02는 **audio 일체가 범위 밖**이었다(`mvp-01-core/00_SCOPE.md`의 "Audio 일체가 MVP-01
범위 밖이다", `AGENTS.md`의 "MVP 구현 대상이 아님"에 audio/TTS). 이 ADR이 그 금지를 **재생 하나에
한해** 연다.

---

## 결정 1 --- route를 한 단계 중첩한다

### 표

``` text
hash                        화면              적재        언어
''  '#/'                    언어 선택 홈      정적        -
'#/ja'                      일본어 홈         정적        ja
'#/ja/demo'                 일본어 demo       동적        ja
'#/ja/kana'                 가나 학습         동적        ja
'#/ja/kana/<sub>'           가나 학습 하위    동적        ja
'#/en'                      영어 홈           정적        en
'#/en/demo'                 영어 demo         동적        en
'#/demo'                    -> '#/ja/demo'    replaceState 뒤 그 route를 적용한다
'#/kana'  '#/kana/<sub>'    -> '#/ja/kana...' 같다
그 밖                       언어 선택 홈      정적        replaceState로 '#/'
(hash 없음, 로그인 영역)    로그인·학습·기록  private.ts  세션의 language
```

-   **route 표가 언어를 들고 있다.** 화면 모듈은 `ctx.language`를 받고, 자기가 어느 언어인지
    문자열을 스스로 정하지 않는다. 그래야 "영어 화면이 일본어 fixture를 불러오는" 조합이
    route 표 한 곳에서만 가능해진다.
-   ADR-022의 `acceptsSubpath`를 그대로 쓴다. `#/ja/kana/<sub>`는 `<sub>`가 subpath다.
-   **공개 화면은 여전히 서버 요청 0건이고 API 모듈에 닿지 않는다**(불변식 13). 중첩은 경로
    문자열만 바꾼다.

### 옛 경로 리다이렉트

`#/demo`와 `#/kana`는 이미 운영에 배포되어 북마크·PWA 바로가기에 남아 있을 수 있다.

``` text
1  route 적용 전에 옛 경로를 새 경로로 바꾼다
2  history.replaceState로 URL만 바꾼다 (pushState 아님. 뒤로 가기에 옛 경로를 남기지 않는다)
3  replaceState는 hashchange를 발생시키지 않으므로 라우터가 그 자리에서 새 경로를 적용한다
4  리다이렉트는 한 단계다. 새 경로가 또 리다이렉트 대상이 되는 표를 만들지 않는다
```

-   **영구 리다이렉트로 둔다.** 떼어낼 시점을 정하지 않는다. 두 줄짜리 표이고 비용이 없다.
-   `history.pushState`/`replaceState`의 state 인자는 계속 `null`만 허용한다
    (`spec/04_SECURITY_AND_DATA.md`).

### 버린 대안

-   **평면 유지(`#/demo`는 일본어, `#/demo-en`은 영어).** 이름이 언어를 품는 규칙이 없어지고,
    "일본어가 기본"이라는 암묵 전제가 경로에 박힌다.
-   **쿼리스트링(`#/demo?lang=en`).** 지금 URL 값 검사는 "고정 허용 목록과 비교만" 한다
    (`03_UI_UX_SPEC.md`의 `화면 이동`). 쿼리를 파싱하기 시작하면 그 검사 규칙을 다시 써야 한다.
-   **localStorage에 "마지막 언어"를 두고 `#/demo`가 그걸 읽기.** URL이 가리키는 화면이 저장값에
    따라 달라진다. 공유한 링크가 사람마다 다른 화면을 연다.

---

## 결정 2 --- 화면 구성

### 언어 선택 홈 (`#/`)

``` text
상단바       Nihongo Context · 로그인
한 줄 소개   (문구 표)
카드 1       일본어   -> #/ja
카드 2       영어     -> #/en
```

-   **앱 이름은 `Nihongo Context` 그대로 둔다.** 사용자가 "어차피 나 혼자 쓸거라서 이름은
    무시해도 된다"고 명시했다(2026-10-01). 이름을 바꾸면 PWA manifest, 상단바, README, Workers
    이름, 문서가 전부 따라 바뀌고 얻는 것이 없다.
-   **카드에 문장 수·표현 수 숫자를 적지 않는다**(기존 선택 홈 규칙 그대로).
-   로그인·계정 관리·통계로 가는 카드를 두지 않는다(기존 규칙 그대로).

### 일본어 홈 (`#/ja`) / 영어 홈 (`#/en`)

``` text
#/ja     상단바  Nihongo Context · 로그인
         카드 1  표현 학습 체험해 보기   -> #/ja/demo
         카드 2  글자부터 배우기         -> #/ja/kana

#/en     상단바  Nihongo Context · 로그인
         카드 1  표현 학습 체험해 보기   -> #/en/demo
```

-   **영어 홈에 카드가 하나뿐인 것을 그대로 둔다.** 가나 학습에 대응하는 영어 보조 화면(파닉스,
    발음기호 표)을 만들지 않는다. 범위 밖이고, 사용자가 필요로 하는 것은 글자가 아니다.
-   언어 홈에서 **언어 선택 홈으로 돌아가는 길은 상단바 앱 이름**이다. 기존 규칙과 같다.

### 로그인 영역의 언어 선택

로그인 영역은 hash route가 없다(ADR-022). 그래서 언어 선택도 hash가 아니라 **화면**이다.

``` text
로그인 진입 (GET /api/auth/me 200)
→ GET /api/study/session
   ├─ 열린 세션 있음 → 그 세션의 language로 Study Screen (선택 화면을 건너뛴다)
   └─ 없음          → 언어 선택 화면 → 고른 언어로 POST /api/study/session
```

**이 흐름의 첫 분기는 아래 `개정 (2026-10-02)`이 고쳤다.** "열린 세션"이 아니라 "이어서 할 수
있는 세션"이다. 아래 절이 이 블록보다 우선한다.

-   **열린 세션이 있으면 묻지 않는다.** 원칙 2(앱을 열면 바로 학습)를 지킨다. 세션이 이미 언어를
    들고 있으므로 물어볼 것이 없다.
-   Study Screen 상단바에 **`언어 바꾸기`를 두지 않는다.** 언어를 바꾸려면 세션을 끝내야 하고
    (ADR-023 결정 7), 학습 중에 누르기 쉬운 자리에 "세션을 끝내는 버튼"을 하나 더 만들지 않는다.
-   **완료 화면에도 언어 전환 버튼을 두지 않는다.** 이 ADR의 초안은 거기에 `다른 언어로`를
    두려 했으나 `03_UI_UX_SPEC.md`의 `완료 화면`이 **"새 세션 시작 버튼을 두지 않는다"**를 이미
    금지하고 있다(세션 행이 부풀고 "한 번 더 하시죠"라는 압박이 된다 --- `Session End`의
    overdue/streak punishment 금지의 결과다). 언어 전환 버튼은 정확히 그 버튼이다. 그 조항이
    옳으므로 초안을 철회한다.
-   **새 UI가 필요 없다.** 세션을 끝낸 뒤 상단바 앱 이름을 눌러 언어 선택 홈으로 가고 `로그인`을
    누르면, 열린 세션이 없으므로 **언어 선택 화면이 자연히 나온다**(위 흐름의 두 번째 분기).
    기존 경로가 그대로 답이다.
-   학습 **중에** 다른 언어를 고르면(다른 탭·다른 기기) `POST /session`이 409를 돌려주고 화면이
    선택지를 준다(ADR-023 결정 7). 그 분기만이 "세션을 끝내고 바꾸기"를 제안하는 자리이며,
    사용자가 이미 언어를 바꾸려고 행동한 뒤라서 권유가 아니다.

### 개정 (2026-10-02) --- 묻는 조건은 "열린 세션"이 아니라 "이어서 할 수 있는 세션"이다

**이 ADR의 결정 2 자체는 유지된다**(언어 전환 버튼을 상단바에도 완료 화면에도 두지 않고, 언어를
다시 묻는 길은 "세션을 끝내고 다시 로그인 진입"이다). 바뀐 것은 **묻는 조건** 하나다.

``` text
초안   GET /api/study/session 의 session !== null 이면 묻지 않는다
개정   GET /api/study/session 의 session !== null && resumable 이면 묻지 않는다
```

`resumable`은 **그 세션이 idle timeout 이내인가**를 서버가 계산해 응답에 실은 값이다. 계약은
`spec/mvp-01-core/05_API_SPEC.md`의 `resumable`이 canonical이다.

왜 초안이 틀렸는가. `GET /api/study/session`은 **idle timeout을 적용하지 않는 조회**다
(진행 표시가 그 endpoint가 `touch()`를 하지 않는 성질에 의존한다 --- `05_API_SPEC.md`). 그래서
며칠 전에 열어 둔 세션도 조회에는 열린 채로 나오고, 결정 2의 흐름은 그것을 "열린 세션"으로
보아 언어를 묻지 않았다.

``` text
묻지 않고 그 세션의 language로 들어간다
→ POST /session이 그 세션을 만료시키고 **같은 language로** 새 세션을 만든다
→ 다시 "열린 세션이 있는" 상태 → 언어 질문이 다시는 나오지 않는다
```

**사용자는 처음 고른 언어에 영구히 갇힌다.** 결정 2가 "언어를 바꾸는 길은 이 경로 하나"라고
정했으므로, 그 경로가 막히면 다른 언어로 가는 길이 **하나도 남지 않는다.** 화면에는 아무 오류도
보이지 않는다(학습은 정상으로 열린다). 2026-10-02 운영에서 확인했다 --- 운영 DB에 2026-09-15부터
열린 채인 세션이 있었고, 사용자가 "로그인해서는 영어를 공부할 수가 없다"고 신고했다.

판정을 **`POST /session`의 resume 분기와 같은 한 곳**에서 한다. 같은 비교를 두 곳에 따로 두면
조회가 "이어진다"고 답한 세션을 POST가 만료시키는 불일치가 생기고, 경계(정확히 timeout 분)에서
화면과 서버가 갈린다.

#### 버린 대안 (개정)

-   **`GET /session`이 idle timeout을 적용해 세션을 닫는다.** 이 조회가 상태를 바꾸지 않는
    성질에 진행 표시가 의존한다. `05_API_SPEC.md`가 **"여기에 상태 변경을 추가하지 않는다"**를
    이미 못박았고, 그 조항이 옳다. `resumable`은 timeout을 **적용**하지 않고 **계산**만 한다.
-   **frontend가 `last_activity_at`과 timeout을 비교한다.** timeout 값은 서버 설정이고 어떤
    응답에도 싣지 않는다(정책값을 frontend에 복사하지 않는다는 기존 규칙). 내려보내기 시작하면
    그 규칙에 예외가 생긴다.
-   **frontend가 "오래된 세션"을 자체 기준(예: 날짜가 다르면)으로 판정한다.** 서버의 만료 기준과
    어긋나는 두 번째 정책이 생긴다. 어긋나는 쪽이 어느 쪽이든 조용히 틀린다.
-   **언어를 항상 묻는다.** 원칙 2(앱을 열면 바로 학습)를 깨고, 같은 세션을 이어가는 가장 흔한
    경우에 버튼 한 번을 더 받는다.
-   **완료 화면에 언어 전환 버튼을 둔다(초안으로 되돌리기).** 철회 근거(`03_UI_UX_SPEC.md`의
    `완료 화면`이 금지한 "새 세션 시작 버튼")가 그대로 유효하다. 막힌 것은 버튼이 없어서가
    아니라 **묻는 조건이 틀려서**였다.

### 상단바 표에 더하는 행

``` text
화면                     오른쪽
언어 선택 홈              로그인
일본어 홈, 영어 홈        로그인
일본어 demo               후리가나 토글, 로그인
영어 demo                 로그인                  (후리가나 토글 없음. 재생 버튼은 문장 옆이다)
영어 Study Screen         학습 기록, 로그아웃      (후리가나 토글 없음)
```

-   **후리가나 토글은 일본어 화면에만 있다.** 영어 문장에 ruby가 없으므로(ADR-023 결정 6) 토글이
    바꿀 것이 없다.
-   **재생 버튼은 상단바에 두지 않는다.** 문장마다 다른 대상을 읽으므로 전역 메뉴가 아니다
    (`결정 4`).

---

## 결정 3 --- demo 진도 localStorage key를 언어별로 가른다

``` text
nc.demo.v1      -> nc.demo.ja.v1   (개명)
                   nc.demo.en.v1   (신규)
```

-   **key를 둘로 가른다.** 한 key에 `{ja: {...}, en: {...}}`를 담으면 `isValid`가 두 fixture를 한
    번에 검증해야 하고, 한쪽이 깨지면 다른 쪽까지 버려진다. 지금 `isValid`는 "형식이 틀리면 조용히
    처음부터"이고 그 단위는 작을수록 좋다.
-   **옛 `nc.demo.v1` 값을 옮기지 않는다.** 기존 규칙 그대로다(`spec/04_SECURITY_AND_DATA.md`:
    "형식을 호환되지 않게 바꾸면 버전을 올리고 옛 key는 옮기지 않는다"). 방문자는 하루쯤 쓰고
    말고, 사용자 본인의 demo 진도는 학습 기록이 아니다.
-   **지우지도 않는다.** 옛 key를 삭제하는 코드를 두면 `local-store.ts`가 `LOCAL_STORE_KEYS` 밖의
    key를 다루게 되고, 그 성질을 AST 검사가 단정하고 있다.
-   `localSlot` 호출은 **key마다 정확히 한 번**이라는 규칙 그대로다. demo 모듈이 두 번 부른다 ---
    key가 둘이기 때문이고, 한 key를 두 번 부르는 것이 아니다.
-   불변식 18의 "세 용도"를 **"네 key, 세 용도"**로 고친다. 용도는 늘지 않았다(후리가나 설정,
    가나 진도, demo 진도).

### demo fixture도 둘이 된다

``` text
frontend/src/demo/ja/fixture-data.ts    기존 파일을 옮긴다 (내용 동일, id 99eaa6b996c0202e 유지)
frontend/src/demo/en/fixture-data.ts    신규. seed/en/에서 같은 스크립트로 만든다
frontend/src/demo/                      화면·진행·진도 코드는 공유한다. 언어별로 복제하지 않는다
```

-   **화면 코드를 복제하지 않는다.** demo 화면이 하는 일(탭, 설명 시트, 번역, 자기평가, probe,
    다시 보기, 완료)은 언어와 무관하다. 다른 것은 fixture와 후리가나 토글 유무뿐이다.
-   `scripts/build_demo_fixture.py`에 `--language`를 더한다. 선택 규칙(greedy set cover, cap 200)과
    `--check` 재생성 일치는 그대로다.
-   영어 fixture에는 ruby가 없다. fixture 스크립트가 `language = 'en'`이면 후리가나 계산을
    건너뛴다(ADR-023 결정 6과 같은 분기).

---

## 결정 4 --- 소리: 브라우저 `speechSynthesis`만, `localService` 음성만

### 왜 `localService`인가 --- 이것이 이 결정의 핵심이다

Web Speech API의 음성 중 일부는 **브라우저가 외부 서버에 요청해서 합성한다**(Chrome의 Google
음성 등). `SpeechSynthesisVoice.localService`가 `false`면 그 음성이다.

``` text
불변식 13   공개 화면(홈·demo·가나)은 서버 요청 0건이다
검사 (f)    e2e에서 frontend origin 밖 요청 0건을 확인한다   (ADR-022 결정 2)
```

-   불변식 13의 "서버"는 API origin이라고 정의되어 있으므로, 네트워크 음성이 Google로 가는 것은
    글자 그대로는 위반이 아니다. **그러나 검사 (f)는 frontend origin 밖 요청 전부를 센다.**
    네트워크 음성을 허용하면 영어 demo의 e2e가 깨지거나, 깨지지 않게 하려고 검사를 느슨하게
    고쳐야 한다. **검사를 느슨하게 고치지 않는다** --- 그 검사가 지금 격리를 지탱한다.
-   그래서 **`voice.localService === true`인 음성만 쓴다.** 로컬 합성은 네트워크로 나가지 않는다.
-   **쓸 수 있는 음성이 없으면 재생 버튼을 그리지 않는다.** 비활성 버튼으로 두지 않는다 --- 누를 수
    없는 버튼이 왜 있는지 설명해야 하고, 그 설명이 화면마다 반복된다.

### 음성 선택

``` text
1  speechSynthesis.getVoices() 중 voice.localService === true 이고 voice.lang이 'en'으로 시작하는 것
2  그 안에서 voice.lang === 'en-US' 를 우선한다. 없으면 목록 순서 첫 번째
3  하나도 없으면 재생 기능 전체를 끈다 (버튼 없음)
```

-   **`getVoices()`는 처음 호출에서 빈 배열을 돌려줄 수 있다.** `voiceschanged` 이벤트를 한 번
    기다린다. 그 전까지는 버튼을 그리지 않고, 이벤트가 오면 그때 그린다. 타임아웃을 두지 않는다 ---
    이벤트가 영영 안 오는 브라우저는 음성이 없는 브라우저다.
-   **음성 이름을 코드에 하드코딩하지 않는다**(`Samantha`, `Google US English` 등). 기기마다 다르고,
    하드코딩하면 그 기기 밖에서 조용히 동작하지 않는다.
-   `rate`·`pitch`는 **기본값을 쓴다.** "느리게 듣기" 같은 조절을 지금 만들지 않는다. 목표가
    "실제 속도의 대사를 알아듣는 것"이라 느린 재생은 목표에서 멀어진다. 필요해지면 그때 넣는다.

### 어디에 두는가

``` text
영어 Study Screen   문장 옆. 문장 전체를 읽는다
설명 시트           example_sentence 옆. 그 예문만 읽는다
영어 demo           위 두 자리와 같다
일본어 화면         없다
```

-   **일본어에 재생 버튼을 두지 않는다.** 범위를 통제하기 위해서다. `speechSynthesis`는 `lang`만
    바꾸면 일본어도 읽으므로 나중에 여는 것은 작은 변경이고, 그때 일본어 로컬 음성의 품질을 보고
    정한다. 이번에 열면 일본어 쪽 e2e·상단바·demo를 전부 다시 건드려야 한다.
-   **번역(한국어)은 읽지 않는다.** 목적이 영어 청취다.

### 학습 신호가 아니다

``` text
재생은 LearningEvent를 만들지 않는다
item_exposures를 만들지 않는다
user_mastery / review_states / listening_mastery 를 바꾸지 않는다
서버로 아무것도 보내지 않는다
재생 여부를 브라우저에 저장하지도 않는다
```

사용자 결정(2026-10-01)이다. 불변식 25이며, 불변식 16의 목록(`02_LEARNING_POLICY.md`의
`학습 신호가 아닌 것`)에 한 줄을 더한다.

-   **`listening_mastery`는 계속 NULL이다.** 재생을 눌렀다는 사실로 듣기 능력을 추정하지 않는다 ---
    들었는지, 알아들었는지, 몇 번 돌렸는지 아무것도 모른다.
-   `mvp-01-core/00_SCOPE.md`의 "Audio 일체가 MVP-01 범위 밖이다" 블록에서 **`TTS 없음`과
    `audio button 없음` 두 줄만** 해제된다. `audio API 없음`, `audio event 없음`,
    `listening review 없음`은 그대로다.

### 모듈 경계

``` text
frontend/src/ui/speech.ts   speechSynthesis 식별자가 나오는 유일한 모듈
                            export: isSpeechAvailable(), speak(text), renderSpeakButton(...)
                            공개 화면(demo)과 로그인 영역(Study) 양쪽에서 쓴다
                            API 모듈에 닿지 않으므로 공개 그래프에 있어도 된다
```

-   **AST 검사에 한 줄을 더한다**: `speechSynthesis` / `SpeechSynthesisUtterance` 식별자는
    `ui/speech.ts` 밖에 없다. `local-store.ts`의 `localStorage`와 같은 방식이다.
-   기존 "계산된 속성 접근 금지"(`window[...]`, `globalThis[...]`)가 우회를 이미 막는다.
-   **화면을 떠나면 재생을 멈춘다.** 화면의 `signal`이 abort되면 `speechSynthesis.cancel()`을
    부른다. 안 하면 다음 화면에서 이전 문장이 계속 들린다.
-   같은 버튼을 다시 누르면 **멈춘다**(toggle). 두 문장이 겹쳐 나오지 않게 새 재생 전에도 항상
    `cancel()`을 먼저 부른다.

### 버린 대안

-   **서버 TTS로 음성 파일을 만들어 저장.** 품질이 일정하고 듣기 probe까지 설계할 수 있지만, 새
    외부 API·비용·스토리지·백업 대상이 생기고 명세 범위가 크게 는다. 사용자가 이 안을 거절했다.
-   **네트워크 음성 허용 + 검사 (f)에 예외.** 격리 검사에 구멍을 내는 변경이고, 그 구멍으로
    무엇이 더 나갈 수 있는지 추적할 수단이 없다.
-   **재생 기록을 이벤트로 남기기(`audio_played`).** 사용자가 "재생 버튼만, 신호 아님"을 골랐다.
    쓰지 않을 이벤트를 쌓으면 `learning_events`의 event type 목록이 늘고, 그 목록은
    `04_DB_SPEC.md`가 canonical로 관리한다.

---

## 결과

### 바뀌는 frontend 모듈

``` text
src/routes.ts            중첩 route 표, ctx.language, 옛 경로 리다이렉트
src/home/                언어 선택 홈 + 언어별 홈
src/demo/ja/ en/         fixture 분리. 화면 코드는 공유
src/local-store.ts       LOCAL_STORE_KEYS가 네 개
src/private.ts           언어 선택 화면, 세션 language, 409 분기
src/ui/speech.ts         신규
```

### 바뀌는 문서

``` text
spec/mvp-01-core/00_SCOPE.md         Audio 블록에서 두 줄 해제
spec/mvp-01-core/01_USER_FLOW.md     언어 선택이 들어간 흐름 셋
spec/mvp-01-core/02_LEARNING_POLICY.md  학습 신호가 아닌 것에 재생 한 줄
spec/mvp-01-core/03_UI_UX_SPEC.md    route 표, 언어 선택 홈, 언어별 홈, 상단바, 재생 버튼, Demo,
                                     언어 선택 화면 (완료 화면은 바뀌지 않는다)
spec/mvp-01-core/05_API_SPEC.md      세션 language와 409
spec/04_SECURITY_AND_DATA.md         공개 화면 범위, localStorage key 네 개, speechSynthesis 경계
spec/02_ARCHITECTURE.md              frontend 모듈 목록
spec/mvp-03-english/12_TEST_PLAN.md  리다이렉트, localService 분기, 떠날 때 cancel, 이벤트 0건
AGENTS.md                            audio/TTS 금지의 부분 해제
```

### 알려진 한계

-   **로컬 음성의 품질과 존재 여부가 기기마다 다르다.** iOS Safari는 로컬 영어 음성이 있고,
    데스크톱 Linux는 없을 수 있다. 없으면 버튼이 없고, 그 차이를 사용자에게 설명하지 않는다.
-   **합성 음성은 실제 원어민 발화가 아니다.** 축약·연음·플랩 T 같은 실제 구어 현상이 TTS에서는
    약하게 나타난다. 목표(미드 알아듣기)에 직결되는 훈련은 아니며, 철자와 소리를 잇는 보조다.
    `spec/05_LEARNING_SYSTEM_VISION.md`의 `Listening`("TTS는 보조. 최종 목표는 spontaneous real
    speech")이 이미 이 한계를 적고 있다.
-   **재생 실패를 사용자에게 알리지 않는다.** `speechSynthesis`는 실패를 조용히 삼키는 경우가 많고,
    그 실패에 사용자가 할 수 있는 일이 없다.
