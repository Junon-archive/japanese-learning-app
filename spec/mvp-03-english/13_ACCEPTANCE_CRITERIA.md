# MVP-03 Acceptance Criteria (delta)

`spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md`와 `spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md`의
기준은 **모두 유지한다**(회귀). 이 문서는 MVP-03에서 더하는 기준이다. 각 기준 아래 `확인`은
무엇으로 충족을 판정하는지이며, 이름은 `12_TEST_PLAN.md`의 절을 가리킨다.

수치 취급은 이전과 같다. 기준에 실험 수치를 박지 않는다. `(ADR-023)`, `(ADR-024)`, `(ADR-025)`는
그 기준의 결정 배경이다.

**회귀가 이번 마일스톤의 최대 위험이다.** 컬럼 리네임과 route 변경이 이미 운영에서 도는 일본어
학습 전체를 지나간다. 그래서 1\~3번이 맨 앞에 있다.

## 회귀 --- 일본어 학습이 그대로다

1.  **운영 DB의 학습 기록이 보존된다.** migration 후 `review_states`, `item_exposures`,
    `user_mastery`, `learning_events`, `study_sessions`의 행 수와 값이 migration 전과 같고,
    `sentences.text`가 옛 `japanese` 값과 같으며, 기존 모든 행의 `language`가 `'ja'`다.
    migration에 DROP TABLE·DROP COLUMN이 없다. (불변식 26, ADR-023)
    확인: `test_migrations.py`의 데이터 보존 항목, 운영 배포 전후 비교.
2.  **MVP-01·MVP-02의 모든 테스트가 통과한다.** 리네임으로 고친 테스트는 단언 내용이 아니라
    이름만 바뀐다.
    확인: `make lint typecheck test`, `npm test`, `make test-e2e` 전량.
3.  **일본어 학습 화면의 동작이 바뀌지 않는다.** 후리가나 토글, 설명 패널의 reading, 가나 학습,
    일본어 demo 진행이 MVP-02와 같다. 일본어 문장의 `normalized_hash`가 바뀌지 않았다.
    확인: `test_normalization_language.py`의 일본어 불변 항목, 기존 e2e, 화면 확인.

## 다언어 모델

4.  콘텐츠 엔티티 다섯(`learning_items`, `sentences`, `study_sessions`, `prompt_versions`,
    `generation_jobs`)이 `language`를 NOT NULL로 가지고 CHECK가 `ja|en`만 허용하며
    `server_default`가 없다. (ADR-023)
    확인: `test_language_scope.py`.
5.  **사용자별 학습 테이블 여덟 개에 `language` 컬럼이 없다.** (불변식 21)
    확인: `test_language_scope.py`의 이름 열거 단언, 변이 검증 21.
6.  영어 문장에 `ruby_json`을 넣을 수 없고(DB CHECK), 영어 item·설명의 `reading`이 NULL일 수
    있다. (불변식 23, ADR-023 결정 3·6)
    확인: `test_language_scope.py`.
7.  `prompt_versions`의 active가 `(task_type, language)`당 하나이고, 같은 task_type이라도 두
    언어가 동시에 active일 수 있다. 한 언어의 active 행이 없으면 **그 언어 job만**
    `dead_letter`다. (ADR-023 결정 5)
    확인: `test_language_scope.py`, `test_jobs_*.py`.

## 세션 언어

8.  `POST /api/study/session`이 `language`를 필수로 받는다(없거나 허용값 밖이면 422). 기본값이
    없다. `GET /api/study/session` 응답에 `language`와 `resumable`이 있다. `resumable`은 그
    세션이 idle timeout 이내인지를 **서버가 계산한** 값이고, **조회는 timeout을 넘긴 세션도
    닫지 않는다**(`ended_at`이 여전히 NULL이다). 경계 판정이 `POST /session`의 resume 분기와
    같다. (불변식 22, `05_API_SPEC.md`의 `resumable`)
    확인: `test_study_api.py`.
9.  **이어서 할 수 있는** 세션과 다른 언어를 보내면 **409이고 세션이 닫히지 않는다**
    (`ended_at`이 여전히 NULL). 응답이 열린 세션의 id와 언어를 알려준다. 화면은 오류가 아니라
    두 선택지를 보여주고, `마치고 바꾸기`를 눌러야 `/finish`가 불린다. (ADR-023 결정 7)
    확인: `test_study_api.py`, `language-select.test.ts`.
10. **일본어 세션의 Ready Pool·materialization·exploration·probe·backlog에 영어가 섞이지
    않는다.** 특히 영어 due item을 `backlog_threshold`보다 많이 쌓아 두어도 일본어 세션이
    backlog 모드로 바뀌지 않는다. 영어 세션에서 좌우를 바꿔도 같다. (불변식 22)
    확인: `test_engine_language_scope.py`, 변이 검증 22.
11. 로그인 후 **이어서 할 수 있는 세션**(`GET /api/study/session`의 `resumable`)이 있으면 언어를
    묻지 않고 그 언어로 학습이 이어진다. 없으면 --- 열린 세션이 아예 없거나, 있어도 idle
    timeout을 넘겼으면 --- 언어 선택 화면이 나오고, 고른 언어로 세션이 시작된다(옛 세션의
    언어가 아니다). 화면이 `session !== null`로 가르지 않는다. 선택 결과를 저장해 두고 다음에
    건너뛰지 않는다. (ADR-025 결정 2의 `개정 (2026-10-02)`)
    확인: `language-select.test.ts`, `test_study_api.py`.

## 영어 콘텐츠

12. 영어 seed가 **300표현 / 문장 약 1000**이고, 11가지 loader 검증을 전부 통과한다.
    `topic_tags`가 고정 집합 안에 있고, 영어 항목에 `reading` 키가 없다. (ADR-024,
    `01_ENGLISH_CONTENT.md`)
    확인: `test_seed_en.py`, 파일에서 센 개수.
13. **영어 콘텐츠를 적재·생성할 때 형태소 분석기를 부르지 않는다.** 영어 문장의 `ruby_json`이
    NULL이고 `ruby.*` 로그가 0건이다. `backfill_ruby.py`의 대상에 영어 문장이 들어가지 않는다.
    (불변식 23)
    확인: `test_seed_en.py`·`test_llm_validation.py`의 호출 0회 단언, 변이 검증 23.
14. 생성 validation이 언어별로 갈린다: 길이 상한이 `max_sentence_length_chars[language]`이고,
    `explanation.reading`이 ja에서 필수·en에서 null이어야 하며(검사 14), duplicate 비교가 같은
    언어 안에서만 일어난다. (`08_LLM_SPEC.md`)
    확인: `test_llm_validation.py`, `test_normalization_language.py`.
15. **영어 설명의 `nuance`가 격식 수준과 쓰임을 담는다.** 기계로 판정하지 않는다 --- 사용자가
    표본 30개를 보고 "이 설명이 있었으면 그때 알아들었겠다"고 판단하면 충족이다.
    (`01_ENGLISH_CONTENT.md`)
    확인: 사용자 표본 검수(5단계).
16. `learning_items.type`에 영어용 값이 추가되지 않았고, 영어 item도 `word|grammar|expression`
    셋 중 하나다. (ADR-024 결정 3)
    확인: `test_language_scope.py`, `test_seed_en.py`.

## 증분 적재

17. `--incremental`이 이미 있는 `seed_id`를 건너뛰고 새 것만 넣으며 **기존 행을 UPDATE하지
    않는다.** 한 항목이 실패하면 전부 롤백된다. 두 번째 실행은 멱등이다. (ADR-023 결정 4)
    확인: `test_seed_incremental.py`.
18. `backfill_seed_id.py`가 기존 일본어 seed 행에 올바른 `seed_id`를 채우고, **대조가 어긋나면
    아무것도 쓰지 않고 exit 2**다. dry-run이 기본이고 `--apply`는 백업을 강제한다.
    확인: `test_backfill_seed_id.py`.
19. MVP-01이 남긴 `알려진 공백 --- 추가 적재 의미론이 없다`가 명세에서 해소되었고, **운영 DB를
    reset하지 않고 영어 seed를 넣을 수 있다.**
    확인: 운영 배포에서 실제 적재 성공, `04_DB_SPEC.md`의 `증분 적재`.

## 홈과 route

20. `#/`가 언어 선택 홈이고 카드가 둘(일본어·영어)이다. `#/ja`에 카드 둘, `#/en`에 카드 하나다.
    카드에 숫자나 커버리지 퍼센트가 없다. 앱 이름은 `Nihongo Context` 그대로다. (ADR-025 결정 2)
    확인: `routes.test.ts`, `test_home_browser.py`, 화면 확인.
21. 옛 경로 `#/demo`·`#/kana`·`#/kana/<하위>`가 `#/ja/...`로 **replaceState 리다이렉트**되고
    history에 항목을 더하지 않는다. 모르는 hash는 `#/`다. (ADR-025 결정 1)
    확인: `routes.test.ts`, e2e.
22. **공개 화면 여섯 모두 서버 요청 0건이고 API 모듈에 닿지 않는다.** 디렉터리 기준 격리 검사가
    새 화면을 자동으로 포함한다. (불변식 28)
    확인: `demo-isolation.test.ts` (b), e2e (f), 변이 검증 28.
23. 영어 demo와 일본어 demo의 진도가 서로 섞이지 않고, 옛 `nc.demo.v1`을 읽지도 지우지도
    않는다. `LOCAL_STORE_KEYS`가 정확히 네 개다. (불변식 18, ADR-025 결정 3)
    확인: `local-storage-scope.test.ts`, e2e.
24. 후리가나 토글이 일본어 화면에만 있고 영어 화면에 없다. 영어 설명 패널에 reading 줄이 없다
    (빈 줄이나 `-`가 아니라 **없다**).
    확인: `topbar.test.ts`, 설명 패널 테스트, 화면 확인.

## 소리

25. **재생 때문에 frontend origin 밖으로 나가는 요청이 0건이다.** `localService === true`인
    음성만 쓰고, 쓸 음성이 없으면 **버튼을 그리지 않는다**(비활성 버튼이 아니다). (불변식 24,
    ADR-025 결정 4)
    확인: `speech.test.ts`, e2e (f)의 재생 후 요청 0건, 변이 검증 24.
26. **재생이 학습 신호를 만들지 않는다.** LearningEvent·`item_exposures`·mastery를 만들지 않고
    서버로 보내지 않으며 localStorage에도 쓰지 않는다. `listening_mastery`가 계속 NULL이다.
    `learning_events`의 event type 목록이 늘지 않았다. (불변식 25)
    확인: `speech.test.ts`, e2e 요청 0건, 변이 검증 25.
27. 재생 버튼이 영어 문장과 설명 시트의 예문 옆에만 있고 상단바·일본어 화면·번역에는 없다.
    화면을 떠나면 재생이 멈춘다. 자동 재생이 없다.
    확인: `speech.test.ts`, 화면 확인.
28. 서버에 audio endpoint가 없고 오디오 파일을 만들거나 저장하지 않는다. 재생 속도·음높이·음성
    선택 UI가 없다. (`mvp-03-english/00_SCOPE.md`의 Out of Scope)
    확인: 라우터 목록, 소스 확인.

## 저장소 위생

29. **외부 어휘 자료 원본이 저장소에 없다.** `data/wordlists/`가 gitignore되어 있고 git이
    추적하는 파일에 그 경로가 없다. `seed/en/README.md`가 네 자료의 출처·저자·연도·라이선스를
    적고 있다. `seed/en`의 예문이 외부 자료의 예문과 같지 않다. (불변식 27, ADR-024 결정 1)
    확인: `test_repo_hygiene.py`, 변이 검증 27.
30. 공개 저장소 규칙이 그대로다 --- 실제 API 호스트·터널 이름·Workers 이름·계정 서브도메인·
    포트·서버 경로·IP·계정 ID가 커밋된 파일에 없다. README의 사이트 주소 하나만 예외다
    (ADR-020 결정 6).
    확인: 기존 위생 검사.

## 실사용 평가 (기술 검증 뒤)

31. **2\~4주 실사용.** 영어 세션을 실제로 돌려 다음을 사용자가 판단한다. 기계 검증이 아니다.
    -   seed 300개 중 "이미 알던 것"이 체감상 얼마나 되는가 (많으면 선별 3단계를 조정한다)
    -   `nuance`가 실제로 막히던 지점을 설명하는가
    -   생성 문장이 구어체인가, 교과서체로 돌아가지 않는가 (돌아가면 영어 prompt를 고친다)
    -   재생이 쓸모 있는가, 기기에서 실제로 동작하는가
    -   300개가 2\~4주를 버티는가 (못 버티면 증분 적재로 2차를 넣는다)
    확인: 사용자 보고. 결과는 `updates/`의 새 요청으로 이어진다.

## 이번에 판정하지 않는 것

``` text
합성 음성의 발음 정확도·자연스러움
영어 커버리지 퍼센트 (측정하지 않기로 했다 — 01_ENGLISH_CONTENT.md)
언어별 starting_level (알려진 공백 — 00_SCOPE.md)
언어별 학습 통계 화면 (범위 밖)
영어 duplicate_similarity_threshold의 적정값 (알려진 공백)
PHaVE 2순위 이하 sense의 적재 시점 (알려진 공백)
```
