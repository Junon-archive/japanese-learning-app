# MVP-02 Acceptance Criteria (delta)

`spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md`의 기준은 **모두 유지한다**(회귀). 이 문서는 MVP-02에서
더하는 기준이다. 각 기준 아래 `확인`은 무엇으로 충족을 판정하는지다. 테스트 이름은
`12_TEST_PLAN.md`의 절을 가리킨다.

수치 취급은 MVP-01과 같다. 기준에 실험 수치를 박지 않는다. demo 전용 상수와 가나 라운드 규칙의 값은
`mvp-01-core/03_UI_UX_SPEC.md`가 canonical이고, 기준은 "화면이 그 값을 따르는가"를 본다.

`(ADR-021)`, `(ADR-022)`는 그 기준의 결정 배경이다. 검사 방식·파일·명령은 `12_TEST_PLAN.md`에 있다.

## 선택 홈과 로그인 진입

1.  hash가 없거나 `#/`로 열면 선택 홈이 나오고, 방문자가 무슨 앱인지 바로 알 수 있다(상단바의 앱
    이름과 `로그인`, 한 줄 소개, 카드 2개). 카드에 문장 수 숫자가 없다.
    확인: `test_home_browser.py`, `home.test.ts`, 화면 확인.
2.  선택 홈, Demo, 가나 학습에서 서버 요청이 0건이다.
    확인: `test_home_browser.py`와 `test_frontend_invariants.py` (f)의 API 요청 기록, 변이 검증 13.
3.  세 공개 화면의 코드가 `api.ts`, `endpoints.ts`, `env.ts`, `private.ts`에 정적 import로도 동적 import로도
    닿지 않고, entry 청크에 API base URL이 없다. 판정은 fail-closed이며(풀리지 않는 지정자, bare 지정자, `?` 쿼리
    지정자는 위반) `src/`에 `spec/04_SECURITY_AND_DATA.md`의 격리 검사 (d) 목록(비리터럴 `import()`, `env.ts` 밖의
    `import.meta.env`, `api.ts` 밖의 네트워크 원시 API, 동적·script 요소 생성, 함수가 아닌 타이머 인자, `require()`,
    HTML 삽입 싱크, 동적 이벤트·URL 속성, 동적 값의 페이지 이동 등)이 없다. (ADR-022)
    확인: `demo-isolation.test.ts`의 격리 검사 (a)\~(e)와 양성 대조군, 변이 검증 13.
4.  API 서버가 꺼져 있어도 선택 홈, Demo, 가나 학습이 정상 동작하고, 세 화면에서 frontend origin 밖으로 나가는
    요청(API origin·제3자 origin)이 0건이다.
    확인: `test_frontend_invariants.py` (f).
5.  공개 화면을 열 때 로그인 상태를 확인하지 않고, 상단바 `로그인`을 누를 때만 한 번 확인한다. `fetchMe`는
    `main.ts`의 동적 import 한 곳으로만 닿는 `private.ts` 안에 있고, `openLogin` 호출은 `ui/topbar.ts`의 로그인 버튼
    click 리스너 안 한 곳뿐이다. 하위 경로로 부팅하거나 타이머를 진행해도 요청이 없다. 떠난 화면은 새 화면 진입 요청(`fetchMe`, study session 시작)을
    시작하지 않는다.
    (ADR-022)
    확인: `login-entry.test.ts` 부팅 런타임 단정·늦은 응답, `study.test.ts`의 세션 시작 늦은 응답(토스트·`/next` 없음), `test_home_browser.py`, 변이 검증 14.
6.  `로그인`을 누른 결과가 로그인됨이면 Study Screen, 401이면 Login, 403이면 버튼 없이 출처 거부 문구, 그 밖의 연결 실패면 그 자리의 안내와
    `fetchMe`만 다시 부르는 `다시 시도하기`, 로그인 영역 코드 적재 실패면 버튼 없이 상단바 `로그인`을 다시 누르라는 안내이며 공개 화면은
    계속 쓸 수 있다.
    확인: `login-entry.test.ts` 로그인 진입 결과.
7.  Login 폼은 두 필드와 버튼 하나이고 폼 안에 demo 진입 버튼이 없다. 로그인 실패 문구는 사유와 무관한
    한 문구이며 서버의 401도 그대로 단일하다. 회원가입·비밀번호 재설정·소셜 로그인 진입점이 없다.
    확인: `routes.test.ts`·login 화면 테스트, MVP-01 integration의 login 실패 동일성 항목.
8.  상단바가 모든 화면에 있고, 앱 이름을 누르면 선택 홈이다. 공개 화면 오른쪽은 `로그인`, Study
    Screen 오른쪽은 `학습 기록`·`로그아웃`·후리가나 토글, Demo 오른쪽은 후리가나 토글·`로그인`(완료 화면은 `로그인`만), History
    오른쪽은 `로그아웃`뿐이고 Login 오른쪽은 비어 있다. 로그인 확인 실패(403·연결 실패) 화면과 로그인 영역 불러오기 실패 화면의 오른쪽은 `로그인`이고 누르면 로그인 진입을 처음부터 다시 한다.
    확인: `topbar.test.ts`, 화면 확인, `test_home_browser.py`.
9.  Login·Study·History에서 새로고침하면 선택 홈이고, 다시 `로그인`을 누르면 곧바로 Study Screen이다.
    로그아웃하면 선택 홈이다.
    확인: `test_home_browser.py`, `logout.test.ts`.
10. 공개 화면 사이에서 브라우저 뒤로 가기가 동작하고, 모르는 hash는 선택 홈(URL `#/`)이다. (ADR-022)
    확인: `routes.test.ts`, `test_home_browser.py`.

## 문구와 화면 전환

11. 화면 문구가 `03_UI_UX_SPEC.md`의 `화면 문구 표`와 같다. 보안 문구(로그인 실패)의 의미와 고정
    문구의 뜻이 유지된다.
    확인: 각 화면 테스트의 문구 단언, security-reviewer의 로그인 실패 문구 확인.
12. item 설명은 아래에서 올라오는 시트이고, 번역은 문장 아래 인라인 펼침이며 번역 노드는 reveal
    응답 뒤에만 생긴다.
    확인: `interactions.test.ts`, `sheet.test.ts`, `test_demo_e2e_browser.py`.
13. `explanation_revealed`는 떠나지 않은 학습 화면의 DOM에 설명 내용이 삽입된 직후에 보내며 시트 애니메이션을
    기다리지 않는다. `/click` 응답 전에 화면을 떠났으면 보내지 않는다. 시트를 닫고 같은 표현을 다시 탭해도 `item_clicked`와 `explanation_revealed`는 presentation + item당
    1회이고 `/click`을 다시 부르지 않는다.
    확인: `explanation.test.ts`(애니메이션 종료 이벤트가 없는 가짜 DOM), `interactions.test.ts`의 재열기와 떠난 뒤
    도착한 응답(`explanation-revealed` 0건), `study.test.ts`의 학습 기록으로 떠난 뒤 도착한 `/click` 응답(시트 없음, `explanation-revealed` 0건).
14. `prefers-reduced-motion: reduce`이면 이동 없이 짧은 fade만 남는다.
    확인: `test_frontend_invariants.py`의 reduced-motion 에뮬레이션.
15. 프레임워크·애니메이션 라이브러리·새 frontend 의존성이 없고 View Transitions API를 쓰지 않는다.
    확인: `frontend/package.json`·`package-lock.json`의 dependency 변경 없음, 소스에
    `startViewTransition` 없음.

## 후리가나

16. 기본은 끔이고, 켜면 학습 문장 안의 한자에 저장된 읽기가 표시된다(학습 표현이 아닌 한자 포함).
    `03_UI_UX_SPEC.md`의 "모든 한자"의 예외(수사와 조수사, 사전 읽기 없음, tappable 경계를 넘는 토큰)에는
    표시하지 않는다.
    확인: `test_furigana_browser.py`, `test_ruby_alignment.py`의 숫자·읽기 없음·경계 항목.
17. 설정은 `nc.furigana.v1`에만 있고 Study Screen과 Demo가 공유하며 새로고침 뒤에도 유지된다. 저장을 쓸
    수 없어도 끔으로 시작해 토글이 동작한다. (ADR-022)
    확인: `furigana.test.ts`, `test_furigana_browser.py`, `test_frontend_invariants.py`의 저장 차단.
18. probe 중에도 학습 문장의 후리가나가 설정대로 보이고, 설명 예문·`canonical_form`·probe 표현에는
    후리가나가 없다.
    확인: `segments.test.ts`, `furigana.test.ts`의 표시 범위, `test_study_api.py`(probe·`/click`에 ruby 없음).
19. 토글은 `document.documentElement`의 CSS class 전환이다. 문장을 다시 렌더링하지 않고 상호작용 handle을
    다시 만들지 않으며 요청을 보내지 않는다. `rt`는 항상 렌더된다. (ADR-022)
    확인: `furigana.test.ts`, `segments.test.ts`, 변이 검증 17.
20. ruby 표시가 원문 문자열, codepoint 좌표, tappable span 경계, 번역 reveal 규칙을 바꾸지 않는다.
    확인: `segments.test.ts`, `test_ruby_alignment.py` 경계, `test_ruby_persistence.py` 원문 불변, `test_render.py`
    R1\~R4, 변이 검증 17.
21. 후리가나 표시·토글, 가나 학습, demo 진행이 LearningEvent·exposure·evidence를 만들지 않고 서버로
    가지 않는다. 후리가나를 켠 상태의 상호작용 event가 끈 상태와 같다.
    확인: `test_furigana_browser.py`의 요청 비교, 변이 검증 16, learning-verifier 게이트.
22. ruby는 seed 적재, worker 생성(검증 통과 뒤), backfill, demo fixture 생성 시점에 같은 계산 함수
    (`app/furigana.py`)로 계산해 `sentences.ruby_json`에 저장한다. API 요청 경로와 브라우저는 분석하지 않고,
    분석기는 API 이미지에 없다. (ADR-021)
    확인: `test_seed_loader.py`, `test_jobs_persistence.py`, `test_ruby_persistence.py`, G14와 런타임 탐침,
    `test_infra_compose.py`의 Dockerfile 명령, 변이 검증 15.
23. ruby span이 tappable span 경계를 넘지 않고, 넘게 되는 토큰은 읽기를 생략하고 관측된다. seed
    전체의 생략 비율이 `mvp-01-core/11_OBSERVABILITY.md`의 판정 기준 이하다. (ADR-021)
    확인: `test_ruby_alignment.py`의 경계·생략 비율, seed 적재의 stdout 요약.
24. 후리가나 계산 실패가 문장 채택(ready)을 막지 않고(`ruby_json = NULL`, validated) `ruby.failed`로 관측된다.
    분석기가 없으면 worker가 부팅에 실패한다. 저장값이 무효하면(히라가나가 아닌 읽기 포함) 응답은 200이고
    ruby가 비며 `ruby.invalid_stored`로 관측된다. (ADR-021)
    확인: `test_jobs_persistence.py`·`test_ruby_persistence.py`의 계산 실패, `test_jobs_worker.py`의 부팅,
    `test_study_api.py`의 R6.
25. 교정 계층(tappable 표현은 `explanation.reading` 우선, 그 밖은 교정 표)이 적용되고, 불일치를
    `reading_mismatch`와 `explanation_override` 두 종류로 출력·로그에 보고한다. 설명 데이터를 자동으로
    고치지 않는다. (ADR-021)
    확인: `test_ruby_alignment.py`의 교정 계층·불일치 보고, 종료 보고의 불일치 목록.
26. migration은 additive이고, 학습 기록이 있는 DB를 upgrade해도 기존 행이 보존된다. 운영 DB reset이
    없다. MVP-02 migration은 `sentences.ruby_json JSONB NULL` 추가 하나다. (ADR-021)
    확인: `test_migrations.py`, 변이 검증 19.
27. backfill은 기본 dry-run, `--apply`에서만 쓰기, 가린 대상 DSN 출력, 쓰기 전 백업·검증 강제(건너뛰기
    옵션 없음), 멱등(동시 실행 포함), 학습 테이블 비접근이다. 대상은 `ruby_json IS NULL`뿐이고 재계산 옵션이
    없다. 계산 실패가 하나라도 있으면 쓸 행 수와 무관하게 exit 2다. (ADR-021)
    확인: `test_backfill_ruby.py`, 변이 검증 19.
28. prompt가 바뀌지 않았고 LLM이 reading(후리가나)을 만들지 않는다. backend 새 의존성은 형태소 분석기와
    그 사전뿐이며 dependency group `furigana`에 있다. (ADR-021)
    확인: `backend/app/llm/prompts/` diff 없음, `pyproject.toml`·`uv.lock` diff.

## 가나 학습

29. 히라가나와 가타카나 각각 청음·탁음·반탁음·요음·촉음·장음을 담고, 외래어(확장 표기 포함, 한국어
    뜻)는 가타카나에 있다. 분량은 `03_UI_UX_SPEC.md`의 `가나 학습`의 `범위`를 따른다. 히라가나 탭의
    외래어는 안내와 가타카나 이동 버튼이다.
    확인: `kana-data.test.ts`, 화면 확인.
30. 정적 데이터의 개수, 중복, 로마자 형식, 한글 표기 누락을 unit test가 검사하고 통과한다.
    확인: `kana-data.test.ts`.
31. 정답은 로마자(헵번식, 장음 부호 없음)와 한글 소리 근사를 함께 보여준다.
    확인: `test_kana_browser.py`, 화면 확인.
32. 퀴즈는 보고 읽기와 보고 고르기 두 가지이고, 촉음·장음·외래어는 단어 단위로 묻는다. 보고 고르기는
    같은 범위에서 고른 로마자 4지선다다.
    확인: `kana-quiz.test.ts`, `test_kana_browser.py`.
33. 라운드가 `03_UI_UX_SPEC.md`의 `가나 학습`의 `라운드` 문항 수를 넘지 않고, 틀린 문항을 라운드 끝에
    한 번 더 묻는다. 결과에 바로 맞힌 수가 나온다. SRS/FSRS를 쓰지 않는다. 다시 물은 문항을 또 틀리면
    "한 번 더 나와요" 안내를 내지 않는다.
    확인: `kana-quiz.test.ts`, `kana-screen.test.ts`.
34. 진도(글자·단어별 맞음/틀림 수, 마지막 학습 시각)가 `nc.kana.v1`에 남고, 라운드 끝에 다시 묻는 문항의
    응답도 센다. 형식이 맞지 않으면 조용히 초기화되며, 저장을 쓸 수 없어도 정상 동작한다. 진도 초기화
    버튼이 있고 인라인 확인을 거친다. (ADR-022)
    확인: `kana-progress.test.ts`, `test_kana_browser.py`, `test_frontend_invariants.py`의 저장 차단.
35. 소리·획순 기능이 없다.
    확인: 화면 확인, scope-guard 게이트.

## Demo

36. demo fixture는 `seed/`에서 스크립트로만 만들고, 커밋된 fixture가 재생성 결과와 같다. 선택 규칙과
    상한을 따르며, 제외한 문장 목록과 덮지 못한 item 목록을 출력한다. 생성은 `scripts/build_demo_fixture.py`,
    생성 파일은 `frontend/src/demo/` 아래다. tappable 수 상한은 `config/default.yaml`에서 읽고, ruby 계산이 실패한
    문장은 ruby 없이 포함하며 보고한다.
    확인: `test_demo_fixture.py`, `build_demo_fixture.py --check`, 변이 검증 20, 종료 보고의 fixture 통계.
37. fixture의 ruby가 분석기 출력과 같고 형식이 `render_segments[].ruby`와 같다. (ADR-021)
    확인: `test_demo_fixture.py`의 ruby 일치.
38. fixture는 Demo route의 동적 import로 불러오며 선택 홈 번들에 들어가지 않는다. (ADR-022)
    확인: `demo-isolation.test.ts` (c), build 산출물의 청크 확인.
39. 탭→설명, 번역, 자기평가, probe, 같은 문장 다시 보기를 체험할 수 있다. 새 문맥 재등장을 약속하지
    않고, 12분 진행바·`오늘 학습 완료 / 더 학습하기`·연장이 없으며, 진행 표시는
    `본 문장 수 / 전체 문장 수`다. 신고 UI는 요청 없이 "체험에서는 신고가 저장되지 않아요."를 보여준다.
    확인: `demo.test.ts`, `test_demo_e2e_browser.py`.
40. 다시 보기와 probe가 `03_UI_UX_SPEC.md`의 demo 전용 상수대로 동작하고(자기평가와 probe의
    "몰랐음/애매함" 모두 다시 보기를 만든다), 두 상수가 코드의 한 모듈에만 있다. "표현"은 learning item이고
    probe는 같은 표현을 한 번만 묻는다.
    확인: `demo.test.ts`, `demo-progress.test.ts`.
41. 진도(fixture 식별자, 현재 위치, 표현별 자기평가, 다시 보기 대기열, 본 문장 수, probe로 물은 표현, 다시 보기를 마친 문장)가 `nc.demo.v1`에 남아
    다시 열면 이어지고, 형식이나 fixture 식별자가 맞지 않으면 조용히 처음부터이며, 저장을 쓸 수 없으면
    메모리로 정상 동작한다. 진도 초기화 버튼이 있고 인라인 확인을 거친다. 진도를 서버로 보내지 않는다.
    (ADR-022)
    확인: `demo-progress.test.ts`, `test_demo_e2e_browser.py`, `test_frontend_invariants.py`의 저장 차단.
42. 모든 문장을 보면 완료 화면이 나오고 `글자 배우기`(→ `#/kana`)와 `처음부터 다시`를 안내한다. 새 문장이 끝났을 때
    남은 다시 보기는 곧바로 대기열 순서대로 보여준 뒤 완료한다.
    확인: `demo.test.ts`, `test_demo_e2e_browser.py`.
43. 화면에 체험 안내(기록은 이 브라우저에만 남는다)가 있다.
    확인: `demo.test.ts`의 문구 단언.
44. demo가 Learning Engine·FSRS·mastery를 프론트엔드에 복제하지 않는다.
    확인: learning-verifier와 scope-guard 게이트 리뷰.

## localStorage

45. localStorage 접근은 `src/local-store.ts` 한 모듈이 `nc.furigana.v1`, `nc.kana.v1`, `nc.demo.v1` 세 key의
    `localSlot`(key당 하나, 소유 위치 고정, key는 문자열 리터럴)으로만 하고(계산된 속성 접근 포함 다른 경로 없음),
    로그인 영역 안의 slot은 `nc.furigana.v1`뿐이며, 다른 브라우저 저장소(`sessionStorage`, `indexedDB`,
    `document.cookie`, `caches`, `window.name`, `navigator.storage`)를 쓰지 않고 history state 인자는 `null`뿐이다. secret·인증 값·로그인 여부·`login_id`·서버 응답 데이터를 넣지 않고, 읽은
    값은 형식·값 범위·fixture 소속을 검증해 틀리면 조용히 초기화하며, 모든 접근이 실패에도 정상 동작한다.
    (ADR-022)
    확인: `local-store.test.ts`, `local-storage-scope.test.ts`, 변이 검증 18, security-reviewer 게이트.

## 문서와 공개 정보

46. `AGENTS.md`와 루트 `README.md`의 문서 계층이 `spec/mvp-01-core/*` + `spec/mvp-02-onboarding/*`
    (delta)를 source of truth로 말한다. `AGENTS.md`의 "MVP 구현 대상이 아님"에서 형태소 분석기만
    해제되어 있다.
    확인: 문서 확인, scope-guard 게이트.
47. 루트 README가 방문자 우선 구성(한 줄 소개, 바로 써보기, 공부 흐름, 구성도, 기술 스택, 비용과
    개인정보, 개발자용, 로드맵 링크)을 갖고 스크린샷이 없다.
    확인: 문서 확인(MVP-02 마무리 단계).
48. 커밋되는 모든 파일에 **운영 환경의 실제** 호스트·포트·경로·IP·계정(API 호스트명, 터널 이름과 서비스명,
    Workers 이름, 계정 ID 포함)이 없고, 운영 사이트 주소는 README의 1개뿐이다. 예외: loopback 기본값
    (`localhost`, `127.0.0.1`)과 로컬 개발 포트, 문서 예시 자리표시자(`<API_HOST>`, `example.com` 류), 제3자 참고
    URL(화면 전환 참고 사이트 등). (ADR-020 결정 6 개정)
    확인: security-reviewer 게이트의 전체 파일 점검.
49. MVP-01 합격 기준이 회귀 없이 유지된다.
    확인: `make lint typecheck test`, `cd frontend && npm test`, `make test-e2e` 통과.
50. 불변식 13\~20의 변이 검증이 모두 해당 테스트를 빨갛게 만든다(20의 복제 금지 부분은 리뷰).
    확인: `12_TEST_PLAN.md`의 `변이 검증` 결과를 게이트 보고에 기록.
