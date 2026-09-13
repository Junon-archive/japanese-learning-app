# MVP-02 Scope --- Onboarding (delta)

## 이 문서의 지위

-   `spec/mvp-02-onboarding/`은 **MVP-01 명세에 더하는 차이(delta)**다. 독립된 명세가
    아니다.
-   MVP-02의 구현 source of truth는 **`spec/mvp-01-core/*` + `spec/mvp-02-onboarding/*`**다.
    기존 규칙을 바꾸는 내용은 `spec/mvp-01-core/*`와 `spec/00~06`의 **제자리**에서 고쳤고
    (`spec/CHANGELOG.md`), 이 디렉터리에는 범위 delta(이 문서), MVP-02 테스트 계획
    (`12_TEST_PLAN.md`), MVP-02 합격 기준(`13_ACCEPTANCE_CRITERIA.md`)만 둔다.
-   이 문서가 바꾼다고 적지 않은 MVP-01 규칙은 **그대로다.**
-   `updates/`의 요청서(`U-001`~`U-005`)는 **명세가 아니다.** 결정의 출처는 사용자
    결정(2026-09-13)과 그 원칙 안에서 정한 Wave 1 보완 결정(2026-09-13)이며, 요청서는 사용자 결정을 기록한
    요청일 뿐이다. 구현 근거는 이 명세다.
-   되돌리기 비싼 결정은 ADR-021(후리가나: 분석기 선정, ruby 데이터 모델, 한자 run 정렬과 교정 계층,
    backfill, API 계약)과 ADR-022(선택 홈 route와 로그인 진입, 격리 검사, localStorage 모듈, 전환·시트·토글의
    구현 경계)에 둔다.
-   **계정 사용자는 상단 `로그인` 한 번으로 학습 화면에 들어간다. 방문자 대상 선택 홈은 사용자
    결정(2026-09-13)이다.** `spec/01_PRODUCT_PRINCIPLES.md`의 원칙 2(앱을 열면 바로 학습)는 고치지 않는다.

## In Scope 추가

각 항목의 canonical 규칙은 오른쪽 조항이다. 이 문서는 목록만 둔다.

1.  **선택 홈** --- 첫 화면을 로그인 대신 선택 홈으로 바꾼다
    (`mvp-01-core/03_UI_UX_SPEC.md`의 `선택 홈`).
2.  **상단바와 로그인 진입점** --- 모든 화면의 상단바, 누를 때만 로그인 상태를 확인하는
    `로그인` 버튼(`03_UI_UX_SPEC.md`의 `상단바`, `01_USER_FLOW.md`의 `Private Learning`, ADR-022).
3.  **문구 가이드** --- 전 화면 문구를 해요체 원칙으로 바꾼다(`03_UI_UX_SPEC.md`의
    `문구 가이드`). 말투만 해당한다.
4.  **화면 전환과 시트** --- 자체 CSS로 부드러운 화면 전환, item 설명 시트, 번역 인라인
    펼침, reduced-motion 대체(`03_UI_UX_SPEC.md`의 `화면 전환과 시트`).
5.  **후리가나** --- 학습 문장 속 한자의 읽기 표시. 기본은 끔이고 사용자가 켠다. 설정은
    브라우저 localStorage에만 둔다(`03_UI_UX_SPEC.md`의 `Translation/Furigana`). 읽기는
    형태소 분석기로 **seed 적재·worker 생성·기존 문장 backfill·demo fixture 생성 시점에**
    계산해 `sentences.ruby_json`에 저장하고 `render_segments[].ruby`로 전달한다(`04_DB_SPEC.md`의 `ruby_json`,
    `05_API_SPEC.md`, ADR-021).
6.  **가나 학습** --- 프론트엔드만으로 동작하는 히라가나·가타카나 학습. 범위 7종(청음, 탁음,
    반탁음, 요음, 촉음, 장음, 외래어), 퀴즈 2종(보고 읽기, 보고 고르기)
    (`03_UI_UX_SPEC.md`의 `가나 학습`).
7.  **demo 확장** --- `seed/`에서 스크립트로 고른 약 200문장, 방문자 진도의 localStorage
    저장, 완료 화면(`03_UI_UX_SPEC.md`의 `Demo`).
8.  **localStorage 사용 범위** --- 후리가나 설정, 가나 진도, demo 진도 세 용도
    (`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)`, ADR-022).
9.  **README 재작성**(방문자 우선)과 **`updates/` 요청 관리 체계** --- 루트 `README.md`,
    `AGENTS.md`. 공개 주소 규칙은 ADR-020 결정 6(개정).

## Out of Scope 추가

MVP-02에서 다음을 하지 않는다.

``` text
소리(발음 재생)와 획순
가나 학습의 SRS/FSRS·간격 반복 (라운드 안에서 틀린 문항을 한 번 더 묻는 것까지만)
회원가입 · 비밀번호 재설정 · 소셜 로그인 (계속 없다)
계정 동기화 (demo 진도·가나 진도·후리가나 설정을 서버로 보내거나 계정 진도와 합치기)
demo용 새 문장 작성과 LLM 생성 (seed/에서 고르기만 한다)
폰트 변경 (말투만 바꾼다)
프레임워크·애니메이션 라이브러리 추가, View Transitions API
새 frontend 의존성
브라우저와 API 요청 경로에서의 형태소 분석
LLM으로 reading(후리가나) 만들기
prompt 변경
```

-   backend의 새 의존성은 형태소 분석기와 그 사전뿐이다(ADR-021).
-   가나 학습의 **한글 발음 표기**는 텍스트 보조 표기다. MVP-01 Out of Scope의
    `pronunciation`(발음 평가·음성)을 열지 않는다.
-   가나 라운드 결과 화면의 "맞힌 수"는 그 라운드 안의 안내다. MVP-01의 학습 세션 완료 화면에
    통계·정답률을 넣지 않는다는 규칙(`03_UI_UX_SPEC.md`의 `완료 화면`)과
    `advanced analytics`, `social/gamification` 제외는 그대로다.

## MVP-01 Out of Scope 유지

`mvp-01-core/00_SCOPE.md`의 `Out of Scope`와 `AGENTS.md`의 "MVP 구현 대상이 아님" 목록은
그대로다. **해제는 형태소 분석기 하나이며**, 그것도 콘텐츠를 적재·생성하는 시점에 후리가나를
계산하는 용도에 한한다(`spec/06_LLM_ENGINEERING_PRINCIPLES.md`의 `MVP 구현 의무 범위` 주석).
분석기로 lemma·난이도·duplicate 판정 등 다른 lexical 기능을 만들지 않는다. audio/TTS,
`ANALYZE_SENTENCE`, embedding duplicate detector, admin UI, export 등 나머지 항목은 계속
범위 밖이다.

## 추가 불변식 (MVP-02)

MVP-01 실행 때 쓴 불변식 1\~12에 이어 붙인 번호다. 문장은 사용자 결정(2026-09-13) 원문이다.
각 불변식을 구현 규칙으로 풀어 쓴 canonical 조항은 오른쪽이다.

13. 홈·demo·가나 학습은 서버 요청 0건이다. API 모듈을 import하지 않는다.
    --- `spec/04_SECURITY_AND_DATA.md`의 `공개 화면 셋으로 확장 (MVP-02 확정)`과 `격리 검사 (MVP-02 확정)`,
    ADR-022.
14. 로그인 상태 확인은 사용자가 로그인 진입점을 누를 때만 한다.
    --- `03_UI_UX_SPEC.md`의 `상단바`, `01_USER_FLOW.md`의 `Private Learning`.
15. 후리가나는 적재·생성 시점에 결정적으로 계산해 저장한다. 요청 경로와 브라우저에서 분석하지
    않는다.
    --- `04_DB_SPEC.md`의 `ruby_json`, `08_LLM_SPEC.md`의 `검증 뒤 후리가나(ruby) 계산 (MVP-02 확정)`,
    `spec/02_ARCHITECTURE.md`(분석기 배치), ADR-021.
16. 후리가나 표시·토글, 가나 학습, demo 진행은 학습 이벤트·exposure·evidence를 만들지 않는다.
    --- `02_LEARNING_POLICY.md`의 `Auxiliary signal` 아래 `학습 신호가 아닌 것 (MVP-02)`.
17. ruby 표시가 원문 문자열, codepoint 좌표, tappable span 경계, 번역 reveal 규칙을 바꾸지
    않는다.
    --- `03_UI_UX_SPEC.md`의 `Translation/Furigana`. 좌표계는 `04_DB_SPEC.md`의
    `sentence_item_spans`, 번역 reveal은 `05_API_SPEC.md`의 `Sentence Presentation Payload`.
18. localStorage는 후리가나 설정, 가나 진도, demo 진도에만 쓴다. secret이나 서버 데이터를 넣지
    않는다. 저장이 없어도 정상 동작한다.
    --- `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)`.
19. 운영 DB는 reset하지 않는다. migration은 additive만 쓰고 기존 학습 기록을 보존한다.
    --- `04_DB_SPEC.md`의 `운영 DB에 migration을 적용하는 경로 (MVP 확정)`과
    `MVP-02: additive migration과 후리가나 backfill (MVP-02 확정)`, ADR-021.
20. demo fixture는 `seed/`에서 스크립트로만 만들고 재생성 결과와 일치한다. demo는 Learning
    Engine·FSRS·mastery를 프론트엔드에 복제하지 않는다.
    --- `03_UI_UX_SPEC.md`의 `Demo`.

## 수정한 기존 문서

MVP-02 규칙을 제자리에서 고친 문서다. 무엇을 바꿨는지는 `spec/CHANGELOG.md`에 있다.

``` text
spec/mvp-01-core/01_USER_FLOW.md           선택 홈, 로그인 확인 시점, demo·가나 흐름
spec/mvp-01-core/02_LEARNING_POLICY.md     후리가나·가나·demo는 학습 신호가 아님
spec/mvp-01-core/03_UI_UX_SPEC.md          문구 가이드, 전환·시트, 상단바, 선택 홈, 후리가나, 가나 학습, demo
spec/mvp-01-core/04_DB_SPEC.md             sentences.ruby_json, Seed Data, Demo Data, backfill
spec/mvp-01-core/05_API_SPEC.md            render_segments[].ruby, API 미사용 화면, explanation_revealed 시점
spec/mvp-01-core/08_LLM_SPEC.md            검증 뒤 ruby 계산, worker 부팅 검사
spec/mvp-01-core/10_ERROR_HANDLING.md      API 장애와 무관한 범위 확장
spec/mvp-01-core/11_OBSERVABILITY.md       후리가나 계산 결과 관측 (추가 절)
spec/mvp-01-core/12_TEST_PLAN.md           demo 서술 조정, MVP-02 참조
spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md 이름 겹침 개명, MVP-02 참조
spec/mvp-01-core/14_CONFIGURATION.md       reading_default_visible과 후리가나 설정 구분
spec/02_ARCHITECTURE.md                    분석기 배치, MVP-02 모듈 위치
spec/04_SECURITY_AND_DATA.md               공개 화면 셋, 격리 검사, localStorage 사용 범위
spec/05_LEARNING_SYSTEM_VISION.md          형태소 분석기 도입 범위 주석
spec/06_LLM_ENGINEERING_PRINCIPLES.md      형태소 분석기 해제 주석
spec/future/CONTENT_SYSTEM.md              형태소 분석기 도입 범위 주석
spec/reference/ui/                         MVP-02 목업
docs/decisions/ADR-020                     결정 6 개정 (README 사이트 주소 1개)
docs/decisions/ADR-015                     계층표에 app/furigana.py, guard G14 한 줄
AGENTS.md, README.md                       source of truth와 문서 계층
```
