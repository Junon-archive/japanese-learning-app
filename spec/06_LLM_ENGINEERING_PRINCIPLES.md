# LLM Engineering Principles

1.  PostgreSQL이 상태 source of truth.
2.  전체 수천 개 mastery 목록을 매 요청에 보내지 않는다. 서버가
    `level summary + targets + weak items + relevant known + avoid/recent duplicates + topic/register/difficulty`만
    계산한다.
3.  문장 하나당 호출하지 않고 batch 생성.
4.  생성 시
    sentence/translation/items/reading/meaning/usage/register/provenance를
    가능한 한 함께 구조화하여 tap 시 live call을 피한다.
5.  Structured Outputs + server-side deterministic validation.
6.  prompt versioning: sentence_gen_v1, explain_item_v1,
    review_context_v1 등. **MVP-03: version은 언어별이다** --- `prompt_versions`가 `language`를
    가지고 active 유일성이 `(task_type, language)`다. version 문자열에도 언어를 적는다
    (`sentence_gen_v2` / `sentence_gen_en_v1`). `provenance_json.prompt_version`이 문자열
    하나라서 그 값만으로 어느 prompt였는지 알 수 있어야 하기 때문이다(ADR-023 결정 5).
7.  Prompt caching을 고려해 static instruction/schema/example을 앞에,
    dynamic user context를 뒤에 둔다. 실제 API 필드는 구현 시 최신 공식
    문서 확인.
8.  Model routing: deterministic code / cheaper model / stronger model을
    task에 맞게. 모델명 hard-code 금지.
9.  MVP에서 별도 LLM judge 필수 아님.
10. Cost guardrail: calls/task, input/output/cached tokens,
    cost/session, cost/sentence, cost/learned-item,
    tokens/learning-minute, retry/failure.
11. Ready Sentence Pool 유지.
12. 약 100개 규모 golden eval set을 장기 유지:
    correctness/naturalness/target/difficulty/explanation/register.
13. Duplicate: exact/normalized + simple similarity → 향후 embedding
    semantic similarity.
14. frequency/dictionary/morphology 같은 lexical truth는 가능한
    deterministic/reliable resource 활용. **MVP-03에서 영어 쪽이 이 원칙을 실제로 적용했다** ---
    무엇을 가르칠지는 LLM 추정이 아니라 공개 코퍼스 기반 빈도·구문 목록이 정한다. 다만 원본
    자료는 저장소에 넣지 않고 선별 결과만 커밋한다(불변식 27, ADR-024).
15. Provider abstraction 유지.
16. 모든 provider 호출은 background worker에서만 발생한다. user request
    handler에서 synchronous provider call 금지
    (`mvp-01-core/08_LLM_SPEC.md`).

## MVP 구현 의무 범위

위 원칙은 장기 설계다. 다음 항목은 **보존하되 MVP 구현 의무가 아니다.**

-   7번 prompt caching optimization
-   8번 정교한 model routing (MVP는 provider abstraction + 단일 모델로
    충분하다)
-   10번 중 `cost/learned-item`, `tokens/learning-minute` 같은 고급 지표
-   12번 약 100개 규모 golden evaluation harness
-   13번 중 embedding semantic similarity
-   14번 중 형태소 분석기 도입 (MVP는 생성 결과의 span을 code point
    index로 결정론적 검증하는 수준까지만 한다)
    -   MVP-02에서 해제: 콘텐츠를 **적재·생성하는 시점에 후리가나(ruby)를 계산하는 용도에
        한해** 형태소 분석기를 쓴다. API 요청 경로와 브라우저에서는 쓰지 않는다. 이 문서는
        구현 근거가 아니며 범위는 `mvp-02-onboarding/00_SCOPE.md`, 결정은 ADR-021이다. span
        검증 방식은 위 괄호 그대로다.
    -   MVP-03 주석: 그 해제는 **`language = 'ja'` 콘텐츠에만** 적용된다. 영어용 분석기·
        lemmatizer는 도입하지 않는다(`mvp-03-english/00_SCOPE.md`). 반면 **frequency는 영어에서
        실제로 쓴다** --- 외부 빈도 자료가 `metadata_json.frequency_rank`를 정한다(14번 본문).

MVP observability 필수 항목은 `mvp-01-core/11_OBSERVABILITY.md`를
따른다.

10번 cost guardrail의 지표는 **언어별로 나눠 보지 않는다.** 한도(`daily_request_limit`,
`daily_token_limit`)는 계정 전체에 하나이고 UTC 일 경계로 판정한다. 언어별 한도를 두면 한쪽이
남고 한쪽이 막히는 상태를 운영자가 관리해야 한다(`09_BACKGROUND_JOBS.md`).

Global/Future 문서에 숫자나 아이디어가 존재한다는 이유만으로 MVP에서
구현하지 않는다.
