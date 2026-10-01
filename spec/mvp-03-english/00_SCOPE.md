# MVP-03 Scope --- English (delta)

## 이 문서의 지위

-   `spec/mvp-03-english/`는 **MVP-01 + MVP-02 명세에 더하는 차이(delta)**다. 독립된 명세가
    아니다.
-   MVP-03의 구현 source of truth는 **`spec/mvp-01-core/*` + `spec/mvp-02-onboarding/*` +
    `spec/mvp-03-english/*`**다.
-   기존 규칙을 바꾸는 내용은 `spec/mvp-01-core/*`와 `spec/00~06`의 **제자리**에서 고치고
    (`spec/CHANGELOG.md`), 이 디렉터리에는 범위 delta(이 문서), 영어 콘텐츠 기준
    (`01_ENGLISH_CONTENT.md`), 테스트 계획(`12_TEST_PLAN.md`), 합격 기준
    (`13_ACCEPTANCE_CRITERIA.md`)만 둔다.
-   이 문서가 바꾼다고 적지 않은 MVP-01·MVP-02 규칙은 **그대로다.**
-   되돌리기 비싼 결정은 ADR에 둔다.

    ``` text
    ADR-023  다언어 콘텐츠 모델 (language 축, 컬럼 리네임, reading nullable, seed 안정 키와 증분 적재,
             언어별 prompt 유일성, 일본어 전용 기능의 경계, 세션 언어)
    ADR-024  영어 콘텐츠 공급 (외부 자료와 라이선스, 선별 절차, item 모델링, seed 배치, 영어 프롬프트,
             언어별 정규화와 길이 상한)
    ADR-025  언어 선택 홈과 route 중첩, demo 진도 key 분리, 브라우저 TTS
    ```

-   결정의 출처는 **사용자 결정(2026-10-01)**이고 `updates/U-006-english-learning.md`는 그 결정을
    기록한 요청일 뿐이다. 구현 근거는 이 명세다.

## 왜 하는가 (사용자 결정 2026-10-01)

사용자의 목표는 **시험 점수가 아니라 원어민 대화와 미드·팟캐스트 이해**다. 현재 수준은 TOEIC 700점대
후반, OPIc IM2이고 읽기는 되지만 실시간 대화가 어렵다. 사용자 원문:

> "you가 뭔지도 알고 good이 뭔지도 알지만, 미국 여행갔을 때 외국인이 문제가 생긴 나한테
> 'you good?'라고 물어봤는데, 뭔 소리인지 몰랐어."

그래서 학습 대상은 **단어 목록이 아니라 실제 쓰이는 구어 표현**이고, 기존 FSRS·Learning
Engine·LLM 생성 파이프라인을 **새로 만들지 않고 그대로 쓴다.** 완전히 새 앱이 아니라 기능 추가다.

**앱 이름(`Nihongo Context`), Workers 이름, 저장소 이름은 바꾸지 않는다**(사용자 결정: "어차피 나
혼자 쓸거라서 그냥 무시하고 영어 학습 기능도 추가하면 돼").

## In Scope 추가

각 항목의 canonical 규칙은 오른쪽 조항이다. 이 문서는 목록만 둔다.

1.  **language 축** --- `learning_items` / `sentences` / `study_sessions` / `prompt_versions` /
    `generation_jobs`에 `language`를 더한다(`mvp-01-core/04_DB_SPEC.md`, ADR-023 결정 1).
2.  **컬럼·필드 리네임** --- `sentences.japanese` → `sentences.text`. API payload와 LLM 응답
    스키마와 seed 파일 키도 같이 바꾼다(`04_DB_SPEC.md`, `05_API_SPEC.md`, `08_LLM_SPEC.md`,
    ADR-023 결정 2).
3.  **`reading` nullable** --- 영어 item과 설명은 발음 표기를 하지 않는다(`04_DB_SPEC.md`,
    ADR-023 결정 3).
4.  **seed 안정 키와 증분 적재** --- `seed_id` 컬럼, 기존 행 backfill, loader의 `--incremental`
    (`04_DB_SPEC.md`의 `Seed Data`, ADR-023 결정 4). MVP-01이 남긴 `알려진 공백 --- 추가 적재
    의미론이 없다`를 해소한다.
5.  **언어별 prompt** --- `prompt_versions.language`, active 유일성 `(task_type, language)`,
    `prompts/<language>/`(`08_LLM_SPEC.md`, ADR-023 결정 5, ADR-024 결정 5).
6.  **세션 언어** --- 한 세션은 한 언어. 다른 언어 요청은 409(`05_API_SPEC.md`,
    `06_LEARNING_ENGINE.md`, ADR-023 결정 7).
7.  **영어 seed 1차** --- 300표현 / 문장 약 1000. 공개 코퍼스 목록 선별 + LLM 예문·설명 생성 후
    검수(`01_ENGLISH_CONTENT.md`, ADR-024).
8.  **언어 선택 홈과 route 중첩** --- `#/`는 언어 선택, `#/ja/...` `#/en/...`. 옛 경로 리다이렉트
    (`03_UI_UX_SPEC.md`의 `화면 이동`·`언어 선택 홈`, ADR-025 결정 1·2).
9.  **영어 demo** --- 일본어 demo와 같은 구조. fixture와 진도 key만 언어별이다
    (`03_UI_UX_SPEC.md`의 `Demo`, ADR-025 결정 3).
10. **문장 소리 재생** --- 브라우저 내장 `speechSynthesis`의 로컬 음성으로 영어 문장과 예문을
    읽는다. 학습 신호가 아니다(`03_UI_UX_SPEC.md`의 `소리 재생`, `02_LEARNING_POLICY.md`,
    ADR-025 결정 4).
11. **언어별 config와 정규화** --- `max_sentence_length_chars`를 언어별 맵으로,
    `normalized_hash`를 언어별 규칙으로(`14_CONFIGURATION.md`, `08_LLM_SPEC.md`, ADR-024 결정 6).

## Out of Scope 추가

MVP-03에서 다음을 하지 않는다.

``` text
서버 TTS · 오디오 파일 생성과 저장 · 음성 다운로드
듣기 probe · listening_mastery 갱신 · 듣기 전용 복습
재생 속도·음높이 조절, 음성 선택 UI
발음 평가 · STT · 마이크 (계속 없다)
영어 발음 표기 (IPA · 한글 근사)
일본어 화면의 소리 재생
영어용 가나 대응 화면 (파닉스, 발음기호 표)
item type enum 확장 (phrasal_verb / idiom / slang 등)
언어별 starting_level · 언어별 학습 통계 화면
세 번째 언어를 위한 구조 (languages 테이블, BCP 47 전체 허용)
회원가입 · 비밀번호 재설정 · 소셜 로그인 (계속 없다)
계정 동기화 (demo 진도·가나 진도·후리가나 설정을 서버로 보내기)
앱 이름 · PWA manifest · Workers 이름 · 저장소 이름 변경
외부 어휘 자료 원본의 저장소 커밋
새 frontend 의존성 · 프레임워크 · 애니메이션 라이브러리
영어 형태소 분석 · 영어 lemmatizer 도입
운영 DB reset
```

-   **backend의 새 의존성은 없다.** MVP-02가 추가한 형태소 분석기 외에 더하지 않는다. 영어 쪽에
    lemmatizer·NLP 라이브러리를 넣지 않는다 --- 영어 item의 `canonical_form`은 seed가 사람 손으로
    적은 값이고, span 검증은 지금처럼 code point index 비교다.
-   **frontend의 새 의존성은 없다.** `speechSynthesis`는 브라우저 내장 API다.
-   가나 학습과 후리가나는 **일본어 전용으로 유지**되며 기능 자체는 바뀌지 않는다.

## MVP-01·MVP-02 Out of Scope 유지와 그 예외

`mvp-01-core/00_SCOPE.md`의 `Out of Scope`, `mvp-02-onboarding/00_SCOPE.md`의 `Out of Scope 추가`,
`AGENTS.md`의 "MVP 구현 대상이 아님" 목록은 **아래 한 가지를 빼고 그대로다.**

**해제: `mvp-01-core/00_SCOPE.md`의 `Audio 일체가 MVP-01 범위 밖이다` 블록 중 두 줄.**

``` text
TTS 없음            -> 해제. 브라우저 내장 speechSynthesis의 로컬 음성만 (ADR-025 결정 4)
audio button 없음    -> 해제. 영어 문장·예문 옆 재생 버튼
audio API 없음       그대로. 서버에 audio endpoint를 만들지 않는다
audio event 없음     그대로. 재생은 LearningEvent를 만들지 않는다
listening review 없음 그대로. listening_mastery는 계속 NULL이다
```

-   `pronunciation`(발음 평가·음성 인식) 제외는 그대로다. 재생은 평가가 아니다.
-   `ANALYZE_SENTENCE`, embedding duplicate detector, golden eval harness, admin UI, export,
    register/sense/multidimensional difficulty, Busy/Deadline 모드, comprehensible-input 난이도
    밴드, source mix 비율은 계속 범위 밖이다.
-   **형태소 분석기의 범위는 넓어지지 않는다.** 일본어 콘텐츠를 적재·생성하는 시점의 후리가나
    계산 용도 그대로다(ADR-021). 영어에는 쓰지 않는다.

## 추가 불변식 (MVP-03)

MVP-01의 1\~12, MVP-02의 13\~20에 이어 붙인 번호다. 각 불변식을 구현 규칙으로 풀어 쓴 canonical
조항은 오른쪽이다.

21. **학습 대상 언어는 콘텐츠 엔티티의 축이다. 사용자별 학습 테이블에는 `language`를 두지
    않는다.** --- `04_DB_SPEC.md`의 각 테이블, ADR-023 결정 1·8.
22. **한 study session은 한 언어다.** 다른 언어로 바꾸려면 지금 세션을 끝낸다. 조용히 닫지
    않는다. --- `05_API_SPEC.md`의 `세션 언어와 409`, `06_LEARNING_ENGINE.md`, ADR-023 결정 7.
23. **후리가나·형태소 분석기·가나 학습은 일본어 전용이다.** 영어 문장의 `ruby_json`은 NULL이고
    DB CHECK가 강제한다. --- `04_DB_SPEC.md`의 `ruby_json`, ADR-023 결정 6.
24. **소리는 브라우저 내장 TTS의 `localService` 음성만 쓴다.** 재생 때문에 frontend origin 밖으로
    요청이 나가지 않는다. 쓸 음성이 없으면 버튼을 그리지 않는다. --- `03_UI_UX_SPEC.md`의
    `소리 재생`, `spec/04_SECURITY_AND_DATA.md`, ADR-025 결정 4.
25. **소리 재생은 학습 신호가 아니다.** LearningEvent·`item_exposures`·mastery를 만들지 않고
    서버로 보내지 않으며 브라우저에도 저장하지 않는다. --- `02_LEARNING_POLICY.md`의
    `학습 신호가 아닌 것`.
26. **운영 DB는 reset하지 않는다. migration은 비파괴만 쓴다** --- 컬럼 추가, 컬럼 리네임,
    NOT NULL 완화, 제약·index 교체까지이며 테이블·컬럼을 DROP하지 않는다. 기존 학습 기록을
    보존한다. --- `04_DB_SPEC.md`의 `MVP-03: 다언어 migration과 seed_id backfill`.
27. **외부 어휘 자료 원본을 저장소에 커밋하지 않는다.** 커밋하는 것은 선별 결과와 선별
    스크립트와 출처 표기다. --- `01_ENGLISH_CONTENT.md`, ADR-024 결정 1.
28. **공개 화면이 여섯으로 늘어도 서버 요청 0건과 API 모듈 비접촉은 그대로다**(불변식 13의
    범위 확장). 언어 선택 홈, 일본어 홈, 영어 홈, 일본어 demo, 영어 demo, 가나 학습. ---
    `spec/04_SECURITY_AND_DATA.md`의 `공개 화면 셋으로 확장`, ADR-025 결정 1.

## 알려진 공백 (MVP-03에서 결정하지 않는다)

**사실만 적는다. 추측으로 메우지 않는다.**

-   **`users.starting_level`이 계정에 하나뿐이다.** 일본어는 초급이고 영어는 중급인 상태를
    표현할 수 없다. 유일한 소비처는 생성 프롬프트의 `learner_level`이므로 두 언어에 같은 값이
    간다. 고치려면 `users`에 언어별 레벨을 두거나 새 테이블이 필요하고, 둘 다 실사용 후에
    판단할 값이다(ADR-023 결정 8).
-   **언어별 학습 통계가 없다.** `history` 화면은 지금 구조 그대로이고 언어로 나누지 않는다.
    advanced analytics 제외 규칙이 그대로 적용된다.
-   **영어 seed의 2차 확장 시점과 규모를 정하지 않았다.** 1차 300표현을 2\~4주 써 본 뒤
    판단한다. 증분 적재 수단은 이번에 만든다(In Scope 4).
-   **PHaVE의 2순위 이하 의미 sense를 1차에 넣지 않는다.** 언제 어떤 기준으로 넣을지 정하지
    않았다(ADR-024 결정 2).
-   **영어의 `duplicate_similarity_threshold`를 일본어와 같은 0.90으로 둔다.** 영어에서 이 값이
    적절한지 실측한 적이 없다(ADR-024 결정 6).
-   **1차 300표현에 들어가는 LLM 보완 항목의 하한 60은 승인값이다.** 근거는 "사용자가 든 예가
    빠지면 안 된다"는 것뿐이고 실측이 아니다.
-   **로컬 TTS 음성의 존재와 품질이 기기마다 다르다.** 어느 기기에서 재생 버튼이 보일지 명세가
    약속하지 않는다(ADR-025 결정 4의 `알려진 한계`).

## 수정하는 기존 문서

MVP-03 규칙을 제자리에서 고치는 문서다. 무엇을 바꿨는지는 `spec/CHANGELOG.md`에 있다.

``` text
spec/00_PRODUCT_VISION.md                  대상 언어 둘, 영어 쪽 목표
spec/01_PRODUCT_PRINCIPLES.md              원칙 8을 두 언어로
spec/02_ARCHITECTURE.md                    분석기는 일본어 전용, frontend 모듈 목록, speech 모듈
spec/03_DOMAIN_MODEL.md                    Language 절 (신규), LearningItem·Sentence의 language
spec/04_SECURITY_AND_DATA.md               공개 화면 여섯, localStorage key 네 개, speechSynthesis 경계
spec/05_LEARNING_SYSTEM_VISION.md          Listening의 TTS 보조 범위, Morphology는 일본어 전용
spec/06_LLM_ENGINEERING_PRINCIPLES.md      6번 prompt versioning에 언어
spec/mvp-01-core/00_SCOPE.md               Audio 블록의 두 줄 해제
spec/mvp-01-core/01_USER_FLOW.md           언어 선택이 들어간 흐름 셋
spec/mvp-01-core/02_LEARNING_POLICY.md     학습 신호가 아닌 것에 소리 재생
spec/mvp-01-core/03_UI_UX_SPEC.md          route 표, 언어 선택 홈, 언어별 홈, 상단바, 소리 재생,
                                           Demo의 언어별 fixture, 완료 화면의 다른 언어로
spec/mvp-01-core/04_DB_SPEC.md             language 컬럼, text 리네임, reading nullable, seed_id,
                                           prompt_versions 유일성, Seed Data, Demo Data, migration
spec/mvp-01-core/05_API_SPEC.md            payload의 text, 세션 language와 409, reading nullable
spec/mvp-01-core/06_LEARNING_ENGINE.md     Ready Pool·materialization·mix·backlog·exploration·
                                           cold start의 언어 범위
spec/mvp-01-core/08_LLM_SPEC.md            응답 스키마 text·reading nullable, avoid_examples,
                                           언어별 prompt와 정규화, ja 전용 ruby 계산
spec/mvp-01-core/09_BACKGROUND_JOBS.md     job의 language, enqueue가 언어를 고정한다
spec/mvp-01-core/10_ERROR_HANDLING.md      API 장애와 무관한 범위에 영어 demo
spec/mvp-01-core/11_OBSERVABILITY.md       로그·health에 language 차원
spec/mvp-01-core/12_TEST_PLAN.md           MVP-03 참조
spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md MVP-03 참조
spec/mvp-01-core/14_CONFIGURATION.md       max_sentence_length_chars 언어별 맵
AGENTS.md                                  source of truth에 mvp-03, audio/TTS 부분 해제
README.md                                  두 언어
.gitignore                                 data/wordlists/
```
