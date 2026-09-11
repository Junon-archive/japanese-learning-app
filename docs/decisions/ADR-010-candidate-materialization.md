# ADR-010 --- user_sentence_candidates를 누가 만드는가

Status: Accepted

Decision: `user_sentence_candidates` row는 **Wave 2의 Learning Engine이
request 경로에서 직접 만든다.** seed loader도, 계정 생성 CLI도, Wave 3
background worker도 만들지 않는다. canonical 정의는
`spec/mvp-01-core/06_LEARNING_ENGINE.md`의
`Candidate Materialization`이다.

실행 시점은 `POST /api/study/session`(세션 생성/resume 직후)과
`POST /api/study/session/{id}/next`(선택된 category에 ready candidate가
없을 때)이며, 대상은 **요청을 보낸 인증 사용자 한 명**이다.

`/next`에서의 정확한 위치는 이후 `Pool Fallback` **0단계(요청당 1회, 실행
후 같은 deficit 순서로 재평가)**로 명확화했다. canonical 정의는
`spec/mvp-01-core/06_LEARNING_ENGINE.md`의 `Pool Fallback`이다.

새 테이블을 만들지 않는다. `user_sentence_candidates`에 아직 소비되지
않은 candidate에 대한 partial unique index만 추가한다.

## 문제

Ready Pool은 `user_sentence_candidates` 중 `status = ready` 집합이고
Learning Engine은 여기서만 고른다. 그런데 seed 적재는 global
content(`learning_items` / `sentences` / `sentence_items` /
`sentence_item_spans` / `sentence_item_explanations`)만 만들고 candidate는
만들지 않는다. 명세는 "seed 문장을 함께 두어 첫 세션의 new/exploration
pool을 확보한다"(`04_DB_SPEC.md`)고 말했지만 pool의 실체인 candidate를
누가 만드는지는 어디에도 없었다.

Wave 3 worker가 만든다고 해석하면 `12_TEST_PLAN.md`의 "seed 상태의 신규
사용자가 첫 세션을 시작할 수 있다"와 `13_ACCEPTANCE_CRITERIA.md`의 "신규
사용자가 seed 기반으로 첫 세션을 시작 가능"을 Wave 2에서 검증할 수 없고,
review candidate까지 worker 소관이면 Core E2E 9~12단계와 Regression
Scenario A~D도 Wave 2에서 재현할 수 없다.

## 버린 대안

**(a) seed loader가 candidate까지 만든다.** seed는 global content이고
candidate는 사용자별이다. 적재 시점에 사용자가 없을 수 있고, 나중에
만들어진 사용자는 아무것도 받지 못한다. content loader가 사용자별 학습
상태를 쓰는 것도 계층이 어긋난다.

**(b) 계정 생성 시점에 만든다.** (a)의 거울상이다. 계정 생성 뒤에
적재·생성된 콘텐츠가 영원히 반영되지 않는다. 계정 생성 CLI가 Learning
Engine에 의존하게 된다.

**(c) Wave 3 worker가 만든다.** 위 문제 그대로다. 게다가 worker가 해야
하는 일은 **없는 콘텐츠를 생성**하는 것(LLM)인데, 이미 있는 문장을
사용자에게 매핑하는 것은 LLM이 필요 없는 결정론적 DB 연산이다. 둘을 한
주체에 묶으면 pool이 비었을 때 항상 provider 비용이 든다.

## 근거

-   materialization은 provider 호출이 아니므로 `08_LLM_SPEC.md`의
    `LLM 호출 경계`를 어기지 않는다. 같은 문서가 request handler에
    허용한 `DB 읽기 / event 저장 / candidate 선택 / 필요 시 job enqueue`
    범위 안이다. 세션을 LLM 응답으로 block하지 않는다는 제약도 그대로
    지켜진다.
-   worker와 역할이 겹치지 않는다. worker는 `sentences`를 채우고,
    Learning Engine은 그것을 사용자에게 투영한다. worker가 만든 문장은
    **다음 materialization 실행에서** candidate가 된다.
-   `context_repair` 판정을 새 컬럼 없이 기존 데이터로 구성할 수 있다
    (가장 최근 `몰랐음` event의 presentation stage,
    `user_item_learning_state.context_stage`, `item_exposures`).

## 한계와 비용

-   `POST /api/study/session`과 pool 부족 시의 `/next`가 쓰기 작업을
    한다. 한 실행의 상한은 `candidate_materialization_batch_size`(role별)로
    묶는다. 상한이 없으면 첫 세션 한 번에 seed 전체가 candidate로
    복제된다.
-   MVP에는 문장 단위의 "anchor로부터의 거리" 지표가 없어
    `varied`와 `new_context`의 문장 선택 규칙이 같다. 두 stage의 구분은
    `user_item_learning_state.context_stage` progression이 담당하고,
    목적에 맞는 문맥을 실제로 생성하는 것은 Wave 3의
    `GENERATE_REVIEW_CONTEXT`다.
-   partial unique index
    `(user_id, sentence_id, presentation_role, context_stage)
    WHERE status IN ('queued','ready')`
    가 필요하다. `shown / consumed / quarantined / expired`를 제외하는
    이유는 같은 문장을 나중에 다시 candidate로 만들 수 있어야 하기
    때문이다(contextual review의 전제).
