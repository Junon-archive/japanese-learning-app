# U-005 demo 확장과 방문자 진도 저장

| 항목 | 값 |
|---|---|
| 번호 | U-005 |
| 제목 | demo 확장과 방문자 진도 저장 |
| 상태 | 배포 대기 |
| 우선순위 | 높음 |
| 요청일 | 2026-09-13 |
| 관련 명세 | `spec/mvp-01-core/01_USER_FLOW.md`, `03_UI_UX_SPEC.md`, `12_TEST_PLAN.md`, `spec/04_SECURITY_AND_DATA.md` |
| 커밋 | 명세 b1ea50d, 7178f41, 78a3b38, 0b405c9 · 머지 1305fc2 · 직접 526a48d |

---

## 1. 배경 --- 사용자 결정 (2026-09-13)

-   demo를 3문장에서 약 200문장으로 늘리고, 방문자 진도를 브라우저에 저장한다.
-   방문자는 하루쯤 써 보고 떠난다.
-   목표는 "충분히 체험할 만한 양 + 다시 열면 이어서"다.
-   선택 홈의 로그인 흐름을 정할 때 데모 확장과 진도 저장을 채택했다(`U-001`).

## 2. 원하는 것 --- 사용자 결정 (2026-09-13)

### 분량

-   약 200문장으로 seed의 200개 표현을 모두 한 번 이상 탭해 볼 수 있게 한다.
-   문장은 기존 `seed/`에서 고른다. LLM 호출, 새 문장 작성, 비용이 없다.

### fixture 생성

-   저장소 스크립트가 `seed/`에서 결정적으로 문장을 골라 정적 데이터를 만든다.
    -   선택 규칙: 모든 item을 덮는 최소에 가까운 문장 집합(동률은 seed_id 순), 상한 200문장
    -   검사에서 제외된 문장 때문에 200문장 안에서 모든 item을 덮지 못하면 멈추지 않는다. 덮지
        못한 item 목록을 보고에 넣고 계속한다.
-   포함하는 것
    -   원문, 번역
    -   tappable span
    -   설명(`reading`, 핵심 뜻, 문맥 뜻, 뉘앙스, 예문)
    -   ruby(`U-003`)
-   생성할 때 결정적 검사를 적용한다: span과 원문 대조, 설명 누락, 문장당 target 수.
    -   어긋나는 문장은 제외하고 제외 목록을 출력한다.
-   커밋된 fixture와 스크립트 재생성 결과가 일치하는지 테스트한다. seed가 바뀌면 fixture도 다시 만든다.

### 후리가나 적용 (`U-003` 적용 대상 4)

-   fixture 생성 스크립트가 같은 정렬 모듈로 ruby를 계산해 정적 데이터에 넣는다.
-   분석기 출력과 fixture가 일치하는지 테스트한다.

### 번들과 로딩

-   fixture는 demo route에 들어갈 때 동적 import로 불러온다. 홈을 가볍게 유지한다.
-   예상 크기: 원문 약 150 KB, gzip 약 40 KB
-   동적 import가 생기므로 demo 격리 검사를 넓힌다.
    -   정적 import와 동적 import 모두 `api.ts`, `endpoints.ts`, `env.ts`에 닿지 않는지 검사한다.
    -   요청 0건 e2e를 유지한다.
-   MVP-01 backlog의 "demo 격리 검사가 동적 import를 놓칠 가능성"은 이 요청에서 해소한다
    (`backlog.md`).

### demo 진행 규칙: 프론트엔드의 단순 규칙이다

-   순서
    -   기본은 fixture 순서다(난이도 → 빈도 → seed_id).
    -   "몰랐음/애매함"을 고른 표현의 문장은 정해진 문장 수 뒤에 한 번 더 보여준다.
-   기존 demo의 체험 요소는 모두 유지한다.
    -   탭 → 설명
    -   번역 reveal
    -   자기평가
    -   probe
    -   다시 보기
-   probe와 다시 보기의 간격은 demo 전용 상수로 명세에 적는다. 코드에서는 한 모듈에만 둔다.
    이것은 학습 정책값이 아니다.
-   화면에 "체험 중이에요. 기록은 이 브라우저에만 남아요." 같은 안내를 둔다(말투 가이드, `U-001`).
-   200문장을 끝내면 끝났다는 화면을 보여준다. 이어서 할 행동도 안내한다: 처음부터 다시, 글자 배우기.

### 진도 저장

-   저장 위치는 localStorage다(가나 학습·후리가나 설정과 같은 규칙).
-   저장하는 것
    -   현재 위치
    -   표현별 자기평가
    -   다시 보기 대기열
    -   본 문장 수
-   key와 형식
    -   key에 버전을 붙인다.
    -   fixture가 바뀌어 형식이 맞지 않으면 조용히 처음부터 시작한다.
-   모든 접근을 try/catch로 감싼다. 저장이 불가능하면 메모리만으로 정상 동작한다.
-   진도 초기화 버튼을 둔다.

### 명세 변경

-   `01_USER_FLOW.md`의 "Demo interaction state는 browser memory/session 수준에서만 유지"를 바꾼다.
    새 규칙: **"demo 진도는 그 브라우저의 localStorage에만 저장한다."**
-   `04_SECURITY_AND_DATA.md`의 demo 격리 조항에 동적 import와 localStorage 규칙을 더한다.

### 불변식 (MVP-02 추가 불변식 13·16·18·20)

-   13\. 홈·demo·가나 학습은 서버 요청 0건이다. API 모듈을 import하지 않는다.
-   16\. 후리가나 표시·토글, 가나 학습, demo 진행은 학습 이벤트·exposure·evidence를 만들지 않는다.
-   18\. localStorage는 후리가나 설정, 가나 진도, demo 진도에만 쓴다. secret이나 서버 데이터를 넣지
    않는다. 저장이 없어도 정상 동작한다.
-   20\. demo fixture는 `seed/`에서 스크립트로만 만들고 재생성 결과와 일치한다. demo는 Learning
    Engine·FSRS·mastery를 프론트엔드에 복제하지 않는다.

## 3. 원하지 않는 것 --- 사용자 결정 (2026-09-13)

-   실제 Learning Engine, FSRS, mastery를 프론트엔드에 복제하지 않는다.
-   demo용 새 문장 작성이나 LLM 생성을 하지 않는다.
-   demo 진도를 서버로 보내지 않는다. 계정 진도와 합치지 않는다.
-   fixture를 손으로 고치지 않는다(스크립트로만 만든다).

## 4. 참고 --- 사용자 결정 (2026-09-13)

-   seed 원본: `seed/`(`seed/README.md`).
-   ruby 계산: `U-003`. 말투와 완료 화면 안내: `U-001`. 글자 배우기: `U-004`.

## 5. 완료 확인 방법 --- 사용자 결정 (2026-09-13)

-   커밋된 fixture와 스크립트 재생성 결과가 일치한다.
-   분석기 출력과 fixture의 ruby가 일치한다.
-   생성 시 제외된 문장 목록과 덮지 못한 item 목록이 출력된다.
-   정적 import와 동적 import 모두 `api.ts`, `endpoints.ts`, `env.ts`에 닿지 않는다.
-   demo는 서버 요청 0건이다(e2e).
-   저장이 불가능하면 메모리만으로 정상 동작한다.
-   fixture 형식이 바뀌면 조용히 처음부터 시작한다.
-   200문장을 끝내면 완료 화면과 이어서 할 행동(처음부터 다시, 글자 배우기)이 나온다.

정식 합격 기준은 Wave 1의 `spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md`다.

---

## 6. 영향 명세·충돌 --- Claude 작성

### 충돌

-   `spec/mvp-01-core/01_USER_FLOW.md`의 `Public Demo`: "Demo interaction state는 browser
    memory/session 수준에서만 유지한다." (반영됨, b1ea50d)
-   `spec/04_SECURITY_AND_DATA.md`의 `Public Demo 구조`: "Demo interaction state는 browser
    memory/session 수준에서만 유지한다." 같은 취지다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `Demo`: "backend API를 호출하지 않으며 demo 상태는 browser
    memory/session 수준에서만 유지한다." 같은 취지다. (반영됨, b1ea50d)

세 문장이 같은 규칙을 반복한다. Wave 1에서 canonical을 한 곳에 두고 나머지는 참조하게 한다.

### 영향

-   `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `Demo`: 진행 규칙, 체험 안내, 완료 화면, 진도 초기화.
    (반영됨, b1ea50d, 78a3b38, 0b405c9)
-   demo 전용 상수(다시 보기 간격, probe 간격)와 fixture 선택 규칙을 명세에 적는다. 두 상수는 학습
    정책값이 아니다. 둘 곳은 Wave 1에서 정한다. (반영됨, b1ea50d, 78a3b38)
-   `spec/mvp-01-core/12_TEST_PLAN.md`의 `Demo isolation`, `Demo E2E`: 동적 import 검사, 재생성
    일치 테스트는 `spec/mvp-02-onboarding/12_TEST_PLAN.md`에 둔다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md`의 "Demo는 backend/DB/LLM과 구조적으로 분리":
    유지한다. 확장 기준은 MVP-02 합격 기준에 둔다. (반영됨, b1ea50d)
-   `spec/02_ARCHITECTURE.md`의 "Public Demo는 static frontend fixture": 유지한다. fixture가 `seed/`에서
    생성된다는 출처를 더한다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/04_DB_SPEC.md`의 `Seed Data`와 `spec/CHANGELOG.md` [53](seed 추가 적재
    의미론 미결정): fixture는 seed 파일을 읽을 뿐 DB에 적재하지 않으므로 [53]을 결정하지 않는다.

## 7. 결정 필요 질문 --- Claude 작성

없음(확정).

## 8. 작업 계획 --- Claude 작성

| Wave | 레인 | 작업 |
|---|---|---|
| 1 | main | spec-sync 반영(demo 진도 규칙, 격리 확장, demo 전용 상수, fixture 선택 규칙) |
| 3 | `demo` | seed → fixture 생성 스크립트(정렬 모듈로 ruby 포함, 제외 목록 출력), 일치 테스트, 동적 import 로딩, demo 진행 규칙, localStorage 진도·초기화·완료 화면, 동적 import까지 덮는 격리 검사, 요청 0건 e2e |
| 4 | main | fixture 통계 보고, `backlog.md` #35 상태 확인, `ROADMAP.md` 상태를 `배포 대기`로 갱신(`done/` 이동은 사용자 배포 확인 후) |

실제와 달라진 곳:

-   분량: 약 200문장이 아니라 171문장으로 seed의 200개 표현을 모두 덮었다(제외 0, 덮지 못한 표현 0)(1305fc2).
-   `backlog.md` #35는 이미 `MVP-02에서 해소(U-005)` 상태다. 문자열을 조합한 동적 import는 격리 검사가 실패로 막는다(5a95fc2).
-   demo 진도 검증을 선형 시간으로 바꾸는 수정을 main에 직접 넣었다(526a48d).
-   배포 참고: `infra/DEPLOY.md`의 17절 "MVP-02 업데이트"(프론트 재배포, 확인 체크리스트)(655f5b6).
