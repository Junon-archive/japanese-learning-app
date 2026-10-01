# MVP-03 Test Plan (delta)

`spec/mvp-01-core/12_TEST_PLAN.md`와 `spec/mvp-02-onboarding/12_TEST_PLAN.md`의 모든 항목은
그대로 유지한다(회귀). 이 문서는 MVP-03에서 **더하는** 테스트와 **이름이 바뀌어 고쳐야 하는**
테스트만 적는다. 규칙의 canonical은 각 항목 끝에 적은 조항이다.

-   **수치를 테스트에 복사하지 않는다.** 길이 상한은 `config/default.yaml`의
    `content.max_sentence_length_chars`를 참조하고, seed 규모는 파일에서 센다.
-   **변이 검증은 불변식 21\~28의 핵심 단언에만 한다**(아래 `변이 검증`). 기존 MVP-01·MVP-02
    항목의 추가 변이 검증은 하지 않는다.
-   아래 새 파일 이름은 권장이다. 구현이 이름을 바꾸면 이 문서도 같은 변경에서 고친다.
-   결정 배경: 다언어 모델은 ADR-023, 영어 콘텐츠는 ADR-024, 홈·route·TTS는 ADR-025다.

## 명령

``` text
backend    make lint typecheck test
frontend   cd frontend && npm test && npm run build
e2e        make test-e2e
fixture    uv run python scripts/build_demo_fixture.py --language ja --check
           uv run python scripts/build_demo_fixture.py --language en --check
seed(en)   uv run python scripts/build_en_seed.py --check     커밋된 seed/en과 재생성 결과 비교
backfill   uv run python scripts/backfill_seed_id.py                dry-run (쓰기 없음)
           uv run python scripts/backfill_seed_id.py --apply --pg-bin <DIR>
```

**`build_en_seed.py --check`는 외부 자료(`data/wordlists/`)가 있을 때만 의미가 있다.** 자료가
없으면 그 검사를 **skip하고 skip 사유를 출력한다** --- 실패로 처리하지 않는다. 자료는 저장소에
없으므로(불변식 27) CI와 새 체크아웃에서는 늘 skip이다. 이것이 "선별 결과만 커밋한다"의 비용이고,
`seed/en/*.yaml` 자체의 형식·내용 검사는 자료 없이 도는 아래 `영어 seed 검증`이 맡는다.

## 이름 변경에 따른 기존 테스트 수정

**새 테스트가 아니라 기존 테스트의 기계적 수정이다.** 목록을 적는 이유는 빠뜨리면 조용히 통과하는
것이 아니라 **컴파일·수집 단계에서 실패**하기 때문이다(그래서 안전하다).

``` text
Sentence.japanese -> Sentence.text          모델을 쓰는 모든 backend 테스트와 factories
payload "japanese" -> "text"                 test_study_api.py, e2e, frontend types/화면 테스트
LLM 응답 fixture "japanese" -> "text"        llm_fixtures.py, test_llm_*.py
seed 파일 키 japanese: -> text:              test_seed_loader.py와 seed/ja/*.yaml
avoid_japanese -> avoid_examples             test_jobs_generate_sentence_batch.py
empty_japanese -> empty_text                 test_llm_validation.py
#/demo -> #/ja/demo, #/kana -> #/ja/kana     routes.test.ts, e2e, test_home_browser.py
nc.demo.v1 -> nc.demo.ja.v1                  local-storage-scope.test.ts, demo 테스트
```

-   `test_migrations.py`의 해시 비교는 MVP-02에서 "pre-migration 컬럼으로 제한"한 방식 그대로
    **이번 migration 이전 컬럼 집합**으로 다시 제한한다. 리네임된 컬럼은 비교에서 뺀다.

## Backend Unit

### 다언어 모델 (불변식 21)

위치: 새 `backend/tests/test_language_scope.py`, 기존 `test_migrations.py`.

-   `learning_items`, `sentences`, `study_sessions`, `prompt_versions`, `generation_jobs`에
    `language`가 NOT NULL이고 CHECK가 `ja|en`만 허용한다. **`server_default`가 없다**(누락한
    INSERT가 실패한다).
-   **사용자별 학습 테이블에 `language` 컬럼이 없다.** `user_mastery`, `review_states`,
    `user_item_learning_state`, `item_exposures`, `user_sentence_candidates`,
    `user_sentence_candidate_targets`, `study_presentations`, `learning_events`를 **이름으로
    열거해 단언한다** --- 나중에 누가 편의상 추가하는 것을 막는 것이 이 테스트의 목적이다.
    (`04_DB_SPEC.md`의 `공통 규칙`)
-   `CHECK (sentences.language = 'ja' OR sentences.ruby_json IS NULL)`가 실제로 거부한다
    (영어 행에 ruby를 넣는 INSERT가 IntegrityError).
-   `learning_items.reading`과 `sentence_item_explanations.reading`에 NULL을 넣을 수 있다.
-   `UNIQUE (seed_id) WHERE seed_id IS NOT NULL`: 같은 `seed_id` 두 번은 실패하고, `seed_id`가
    NULL인 행은 여럿이어도 된다.
-   `prompt_versions`: `(task_type, language) WHERE active`가 유일하다. **같은 task_type이라도
    언어가 다르면 둘 다 active일 수 있다**(이것이 이 변경의 요점이다).

### migration 왕복과 비파괴 (불변식 26)

위치: `backend/tests/test_migrations.py`.

-   빈 DB에서 `upgrade head` → `downgrade` → `upgrade head`가 성공한다(기존 규칙).
-   **데이터가 있는 DB에서 upgrade가 데이터를 보존한다.** 이전 revision으로 만든 DB에 문장·item·
    학습 기록을 넣고 upgrade한 뒤: 행 수가 같고, `text` 값이 옛 `japanese` 값과 같고, 모든
    `language`가 `'ja'`이고, `review_states`·`item_exposures`가 그대로다.
-   migration이 **DROP TABLE / DROP COLUMN을 하지 않는다**(migration 파일을 소스로 단언).

### 언어별 정규화 (ADR-024 결정 6)

위치: 새 `backend/tests/test_normalization_language.py`.

-   **일본어 규칙이 바뀌지 않았다.** 기존 seed 문장 몇 개의 해시가 **현재 DB에 저장된 값과
    같다**(고정 기대값을 테스트에 적지 않고 seed loader를 두 번 돌려 같은지 본다).
-   영어: `Come on.`과 `come on.`과 `  come   on. `이 같은 해시다.
-   영어: 공백을 전부 지우지 않는다 --- `a nice house`와 `anicehouse`가 **다른** 해시다.
-   `normalized_sentence_text`가 언어 인자를 받고, **분기가 이 함수 안에만 있다**(소스에서
    `casefold` 호출 위치가 이 모듈 하나임을 단언).
-   duplicate corpus가 언어로 좁혀진다: 같은 문자열의 ja 문장과 en 문장이 공존할 수 있다.

### 영어 seed 검증 (`01_ENGLISH_CONTENT.md`의 `검증`)

위치: 새 `backend/tests/test_seed_en.py`. **외부 자료 없이 돈다** --- `seed/en/*.yaml`만 읽는다.

-   11가지 검증이 각각 실패 입력을 거부한다(항목당 양성 대조군 하나).
-   `topic_tags`의 모든 원소가 고정 집합 안에 있다. 집합은 loader 상수를 참조하고 테스트에
    복사하지 않는다.
-   영어 항목에 `reading` 키가 없다. 일본어 항목에는 있다.
-   `frequency_rank`가 파일 안에서 유일하고 1 이상이다.
-   문장 길이가 `max_sentence_length_chars.en` 이하다(config에서 읽는다).
-   span 좌표가 code point index로 표면형과 정확히 일치한다(일본어와 **같은 함수**를 쓴다는 것을
    포함해 단언).
-   **후리가나 계산을 부르지 않는다.** 영어 적재 경로에서 분석기 어댑터가 호출되지 않음을 test
    double로 단언한다(불변식 23).

### 증분 적재 (ADR-023 결정 4)

위치: 새 `backend/tests/test_seed_incremental.py`.

-   기본 모드는 `origin = seed` 행이 있으면 거부한다(기존 동작 유지).
-   `--incremental`: 이미 있는 `seed_id`를 건너뛰고 새 것만 넣는다. **기존 행을 UPDATE하지
    않는다**(기존 행의 `lemma`를 파일에서 바꿔도 DB 값이 그대로).
-   한 항목이 실패하면 **전부 롤백**된다(부분 적재 없음).
-   `seed_order`가 **그 언어의 기존 최대값 다음부터** 이어진다. 재사용하지 않는다.
-   증분 적재도 `user_sentence_candidates`를 만들지 않는다.
-   item → sentence 순서: 문장이 같은 실행에서 방금 넣은 item을 참조할 수 있다.
-   두 번째 실행은 넣는 것이 0이고 성공으로 끝난다(멱등).

### seed_id backfill (ADR-023 결정 4)

위치: 새 `backend/tests/test_backfill_seed_id.py`. 형태는 `test_backfill_ruby.py`와 같다.

-   dry-run이 기본이고 아무것도 쓰지 않는다.
-   `--apply`는 백업을 강제하고, 백업 실패면 쓰기 없이 exit 2.
-   **대조가 어긋나면 아무것도 쓰지 않고 exit 2.** seed 파일의 N번째 `lemma`를 바꿔 두면
    전체가 실패한다(한 행만 건너뛰지 않는다).
-   성공 시 모든 seed 행의 `seed_id`가 파일의 값과 같다.
-   두 번째 실행은 대상 0, 백업 없음, exit 0(멱등).

### 언어별 prompt 선택 (ADR-023 결정 5)

위치: 기존 `test_jobs_*.py`에 추가.

-   worker가 job의 `(job_type, language)`로 active 행을 읽는다.
-   **한 언어의 active 행이 없으면 그 언어 job만 `dead_letter`이고 다른 언어는 정상 처리된다.**
-   `provenance_json.prompt_version`에 언어가 들어간 version 문자열이 기록된다.

### 생성 validation의 언어 분기 (`08_LLM_SPEC.md`)

위치: 기존 `test_llm_validation.py`에 추가.

-   길이 상한이 job의 언어로 갈린다: 100자 영어 문장은 통과하고 100자 일본어 문장은
    `sentence_too_long`이다.
-   검사 14 `reading_language_mismatch`: ja인데 `reading`이 null이면 탈락, en인데 non-null이면
    탈락, 각각 반대는 통과.
-   **영어 job은 ruby를 계산하지 않는다**(분석기 어댑터 호출 0회, 저장된 `ruby_json`이 NULL).

### 엔진의 언어 범위 (불변식 22, `06_LEARNING_ENGINE.md`의 `언어 범위`)

위치: 새 `backend/tests/test_engine_language_scope.py`.

두 언어 콘텐츠와 두 언어 학습 기록을 모두 만든 뒤 **일본어 세션에서** 다음을 단언한다.

-   Ready Pool에 영어 candidate가 없다.
-   materialization이 영어 문장으로 candidate를 만들지 않는다.
-   exploration 후보에 영어 item이 없다.
-   **backlog 수에 영어 due item이 포함되지 않는다.** 영어 due를 `backlog_threshold`보다 많이
    쌓아 두어도 일본어 세션의 mix가 backlog 모드로 바뀌지 않는다(이것이 이 불변식의 핵심이다).
-   probe 대상에 영어 item이 없다.
-   영어 세션에서 좌우를 바꿔 같은 단언을 한다.

### 세션 언어 API (`05_API_SPEC.md`의 `세션 언어와 409`)

위치: 기존 `test_study_api.py`에 추가.

-   `POST /session`에 `language`가 없거나 허용값 밖이면 422.
-   열린 세션 없음 → 그 언어로 생성.
-   같은 언어 → resume (같은 세션 id).
-   **다른 언어 → 409이고 body에 `open_session.id`와 `language`가 있다. 세션이 닫히지 않고
    `ended_at`이 여전히 NULL이다**(조용히 닫지 않는다는 규칙의 단언).
-   `/finish` 뒤 다른 언어로 보내면 성공한다.
-   idle timeout을 넘긴 세션이 있으면 다른 언어여도 409가 아니라 새 세션이다.
-   `GET /session` 응답에 `language`가 있다.

### payload (`05_API_SPEC.md`)

-   presentation payload의 문장 필드 이름이 `text`다.
-   **영어 문장의 `render_segments[].ruby`가 전부 `[]`이고 필드가 생략되지 않는다.**
-   `/click` 응답의 `reading`이 영어에서 `null`이고 필드가 생략되지 않는다.

## Frontend Unit

### 격리 검사 확장 (불변식 24·28)

위치: 기존 `demo-isolation.test.ts`.

-   (b)의 디렉터리 기준이 그대로이므로 **화면이 늘어도 자동으로 포함된다.** 그 사실을
    `src/home/`, `src/demo/ja/`, `src/demo/en/`, `src/kana/` 아래 모듈 수가 0이 아님을 확인해
    단언한다(디렉터리가 비어 검사가 공회전하는 것을 막는다).
-   **(d)에 한 줄 추가:** `speechSynthesis` / `SpeechSynthesisUtterance` 식별자가
    `ui/speech.ts` 밖에 없다. 양성 대조군: 합성 소스의 `window.speechSynthesis.speak(u)`를
    위반으로 낸다.
-   `ui/speech.ts`가 API 모듈에 닿지 않는다(공개 그래프에 있어도 되는 근거).

### localStorage key 네 개 (불변식 18)

위치: 기존 `local-storage-scope.test.ts`.

-   `LOCAL_STORE_KEYS`가 정확히 네 개이고 이름이 명세와 같다.
-   `localSlot` 호출이 key마다 정확히 한 번이고 소유 위치에만 있다. demo 모듈이 두 key를
    소유한다.
-   private 그래프 안의 `localSlot` 호출이 `nc.furigana.v1` 하나뿐이다(변경 없음).
-   **두 demo 진도가 서로 섞이지 않는다:** `nc.demo.ja.v1`에 값을 쓰고 영어 demo를 열면 처음부터
    시작한다.
-   `nc.demo.v1`(옛 key)을 **읽지도 지우지도 않는다**(소스에 그 문자열이 없다).

### route 중첩과 리다이렉트 (ADR-025 결정 1)

위치: 기존 `routes.test.ts`.

-   표의 일곱 경로가 각각 올바른 화면·언어로 간다.
-   `#/demo` → URL이 `#/ja/demo`로 **replaceState**되고 그 화면이 뜬다. `#/kana/hiragana` →
    `#/ja/kana/hiragana`.
-   **리다이렉트가 history에 항목을 더하지 않는다**(뒤로 가기가 옛 경로로 돌아가지 않는다).
-   모르는 hash → 언어 선택 홈, URL `#/`.
-   화면 모듈이 `ctx.language`를 받고 **소스에 `'ja'`/`'en'` 리터럴을 스스로 두지 않는다**
    (route 표와 fixture 모듈 밖에서).

### 소리 재생 (불변식 24·25, `03_UI_UX_SPEC.md`의 `소리 재생`)

위치: 새 `frontend/tests/unit/speech.test.ts`.

-   **`localService === false`인 음성만 있으면 버튼을 그리지 않는다.** 이것이 이 기능의 핵심
    단언이다.
-   `localService === true`인 `en-US`가 있으면 그것을 고른다. `en-GB`만 있으면 그것을 고른다.
-   영어 음성이 하나도 없으면 버튼이 없다.
-   `getVoices()`가 처음에 빈 배열이고 나중에 `voiceschanged`가 오면 그때 버튼이 생긴다.
-   재생 전에 항상 `cancel()`이 먼저 불린다. 같은 버튼 재클릭은 멈춤이다.
-   **화면 `signal` abort 시 `cancel()`이 불린다.**
-   음성 이름 문자열(`Samantha` 등)이 소스에 없다.
-   **재생이 어떤 네트워크 호출도 하지 않고 localStorage에도 쓰지 않는다**(스텁으로 단언).
-   일본어 화면 모듈이 `renderSpeakButton`을 부르지 않는다.

### 언어 선택 화면 (`03_UI_UX_SPEC.md`)

위치: 새 `frontend/tests/unit/language-select.test.ts`.

-   `GET /api/study/session`에 열린 세션이 있으면 **선택 화면을 건너뛰고** 그 언어로 Study
    Screen이다.
-   없으면 선택 화면이 뜨고, 고르면 그 `language`로 `POST /session`을 보낸다.
-   409면 안내와 버튼 둘이 뜬다. `이어서 하기`는 열린 세션의 언어로 가고 `/finish`를 부르지
    않는다. `마치고 바꾸기`는 `/finish` 뒤 새 `POST /session`을 보낸다.
-   **"마지막에 고른 언어"를 저장하지 않는다**(선택 후 localStorage 쓰기 0건).
-   Study Screen·완료 화면 상단바에 언어 전환 버튼이 없다.

### 후리가나 토글의 언어 제한

-   영어 Study Screen과 영어 demo의 상단바에 후리가나 토글이 없다.
-   일본어 쪽은 그대로 있다.

## E2E (browser)

위치: 기존 `test_home_browser.py`, `test_demo_e2e_browser.py`에 추가 + 새
`test_english_demo_browser.py`.

-   **(f) 확장:** 여섯 공개 화면 모두에서 frontend origin 밖 요청이 0건이다. **영어 demo에서
    재생 버튼을 눌러도 0건이다**(불변식 24의 e2e 단언). 테스트 브라우저에 로컬 음성이 없으면
    버튼이 없으므로, 그때는 "버튼이 없다"를 단언하고 **skip하지 않는다.**
-   `#/demo`로 열면 URL이 `#/ja/demo`가 된다.
-   영어 demo를 끝까지 보고 새로고침해도 일본어 demo는 처음부터다(진도 분리).
-   언어 선택 홈 → 영어 홈 → 영어 demo 경로가 동작하고 카드가 하나다.

## 변이 검증 (불변식 21\~28)

각 변이가 **적어도 한 테스트를 실패시켜야 한다.** 실패하지 않으면 그 불변식에 테스트가 없는
것이다.

``` text
21  user_mastery에 language 컬럼을 추가한다                  -> test_language_scope
22  backlog 집계에서 language 필터를 뺀다                     -> test_engine_language_scope
22  POST /session의 다른 언어 분기를 "기존 세션 finish 후 생성"으로 바꾼다 -> test_study_api
23  영어 job에서도 후리가나를 계산한다                        -> test_llm_validation / test_seed_en
23  sentences의 ruby CHECK를 뺀다                            -> test_language_scope
24  localService 필터를 뺀다                                 -> speech.test.ts
25  재생에서 LearningEvent를 보낸다                           -> speech.test.ts / e2e 요청 0건
26  migration에 DROP COLUMN을 넣는다                          -> test_migrations
27  data/wordlists를 .gitignore에서 뺀다                      -> 아래 저장소 위생
28  demo/en 모듈이 api.ts를 import한다                        -> demo-isolation (b)
```

## 저장소 위생 (불변식 27)

위치: 새 `backend/tests/test_repo_hygiene.py` 또는 기존 위생 테스트에 추가.

-   `data/wordlists/`가 `.gitignore`에 있고, **git이 추적하는 파일 중 그 경로가 하나도 없다**
    (`git ls-files`로 확인).
-   `seed/en/README.md`가 존재하고 네 자료의 출처·저자·연도·라이선스를 적고 있다(키워드 존재
    확인 수준).
-   **`seed/en/*.yaml`의 예문이 외부 자료의 예문과 같지 않다.** 외부 자료가 있을 때만 도는
    검사이고 없으면 skip한다(`01_ENGLISH_CONTENT.md`의 `금지`).

## 하지 않는 테스트

``` text
합성 음성의 소리 품질·발음 정확도      기계가 판정할 수 없다
영어 설명 내용의 사실 정확도           5단계 사람 검수가 맡는다 (01_ENGLISH_CONTENT.md)
외부 자료 자체의 내용 검증             우리 자료가 아니다
seed 300개 전수의 "이미 아는 표현" 여부  사용자만 안다
언어별 커버리지 퍼센트                 측정하지 않기로 했다
```
