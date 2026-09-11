# Specification Changelog

## v0.2 --- 2026-09-11

v0.1 MVP 명세에 지금까지 논의한 장기 설계를 추가했다.

추가/보강: comprehensible-input 비율, multidimensional difficulty,
sentence 이해와 item mastery 분리, morphology/lemma, sense 확장,
register/recognize-only, 설명 언어 progression, topic coverage,
Busy/Deadline habit, real-source mix, minimal LLM context, prompt
caching, model routing, \~100 golden eval, duplicate evolution, 비용
지표, Admin/export, YouTube LearningValue/comprehension/rewatch,
configuration.

## v0.2 Corrective Patch --- 2026-09-11

v0.2 compression으로 소실된 implementation detail을 복원하고, 명세 리뷰에서
드러난 P0/P1 구멍을 현재 제품 결정에 맞춰 in-place로 보완했다. 새 버전
번호를 만들지 않았다.

주요 내용:

-   **소실 detail 복원**: meaningful exposure positive definition,
    LearningEvent type 목록, `learning_events`의 FK/context column,
    `review_states`의 user/item identity, `sentences`의
    status/difficulty/provenance 필드, `prompt_versions.active`,
    empty pool fallback 절차, retry 세부 규칙, E2E 단계별 시나리오.
-   **Audio/Listening**: MVP-01에서 audio 전면 제외. `listening_mastery`는
    nullable float, 초기값 NULL, MVP에서 갱신하지 않음.
-   **Mastery**: nullable float `[0.0, 1.0]` + explicit evidence
    (0.0/0.4/0.8) + configurable EMA. auxiliary signal은 mastery를 직접
    바꾸지 않음. `evidence_count` 정의 분리.
-   **FSRS / no-signal**: explicit signal → Again/Hard/Good mapping,
    `Easy` 미사용. 무신호 review는 rating을 추론하지 않고
    `deferred_until`로만 처리하여 무한 due loop를 제거.
-   **Exposure / Context model**: `item_exposures`를 canonical source로
    도입(presentation당 1회), `user_item_learning_state`로 context
    progression 추적. 최소 5회 보장은 FSRS interval을 왜곡하지 않고
    `reinforcement` 노출로 달성.
-   **Ready Pool**: `user_sentence_candidates` /
    `user_sentence_candidate_targets` / `study_presentations` 도입.
    사용자별 role을 global sentence에 저장하던 `sentence_items.role`
    (`incidental` 포함) 제거.
-   **Contextual explanation**: `sentence_item_explanations` 신설 +
    Ready invariant 정의(tap 시 live LLM fallback 금지).
-   **Span**: `sentence_item_spans` 신설, Unicode code point index 고정,
    불연속 표현 지원, API가 render segment list 반환.
-   **Demo / Auth**: Demo는 완전한 static frontend fixture(API/DB/provider
    경로 없음). auth는 seed 계정 + Argon2id + `auth_sessions` +
    동일 registrable domain + CORS/CSRF 규칙 확정.
-   **Cold start / selection**: starter seed set 요구, deficit 기반
    category mix, review ordering, backlog 정의, pool fallback 확정.
-   **LLM lifecycle**: 모든 provider 호출은 worker 전용,
    deterministic validation 12개 항목, sense correctness 한계 명시,
    job idempotency/retry 확정. `ANALYZE_SENTENCE`는 Future로 이동.
-   **API contract**: 실제 request/response schema 수준으로 보강.
    번역은 reveal 이후에만 반환.
-   **MVP/Future boundary**: 실험 수치를
    `future/EXPERIMENTAL_PARAMETERS.md`로 이동(삭제 아님), acceptance에서
    실험 숫자 제거, observability MVP 필수 범위 축소.
