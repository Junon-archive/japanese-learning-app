# MVP-01 backlog

MVP-01에서 다음 사이클로 미룬 항목이다. **명세가 아니고 구현 지시도 아니다.** 다룰 때는 요청서(U-NNN)로
올려 `updates/README.md`의 처리 흐름을 따른다.

-   `#N`은 `spec/mvp-01-core/13_ACCEPTANCE_CRITERIA.md`의 합격 기준 항목을 위에서부터 센 순번이다.
-   `spec/CHANGELOG.md [N]`은 changelog 본문의 `[N]` 항목이다.
-   원문 기록을 찾을 수 없는 세부는 "세부 미기록"으로 적는다.
-   상태: `대기` / `MVP-02에서 해소(U-NNN)`

## 1. 검증

### 1.1 변이 검증 후보 (11건)

테스트가 정말 그 합격 기준을 잡는지 의심되는 곳이다. 제안 변이를 넣었을 때 테스트가 실패해야 한다.

| 합격 기준 | 테스트 | 의심 이유 | 제안 변이 | 상태 |
|---|---|---|---|---|
| backup/restore 최소 1회 검증 (#42) | `backend/tests/test_db_backup_restore.py::test_backup_then_restore_check_passes_all_six_checks` | 5번 확인(login/history)을 스크립트가 출력한 문자열로만 단정한다 | 스크립트가 API를 부르지 않고 같은 줄만 출력하게 한다 | 대기 |
| restart 후 state 유지 (#40) | `backend/tests/test_restart_persistence.py::test_state_survives_restarting_the_api_and_worker_processes` | 프로세스 내부 상태에 기댄 구현을 정말 잡는지 확인하지 않았다 | auth session 조회를 모듈 전역 dict 캐시로 바꾼다 | 대기 |
| 모든 provider 호출이 worker에서만 발생 (#25) | `backend/tests/test_no_provider_in_request_path.py::test_a_fresh_api_process_loads_neither_the_provider_module_nor_the_sdk` | 별도 프로세스가 login/session/next(빈 pool)만 밟는다 | history handler 안에 함수 내부 `from app.llm import provider`를 넣는다(`docs/decisions/ADR-007-module-boundaries-and-clock.md`의 guard G4가 잡는지도 함께 본다) | 대기 |
| 모바일에서 세션 시작/진행/종료 가능 (#1) | `backend/tests/e2e/test_pwa_installable.py::test_the_study_screen_works_on_a_phone_viewport` | 토큰 탭과 Next를 탭이 아니라 `.click()`으로 누른다 | 토큰 handler가 `pointerType === 'touch'`면 무시하게 한다 | 대기 |
| Demo는 backend/DB/LLM과 구조적으로 분리 (#35) | `frontend/tests/unit/demo-isolation.test.ts` | 정규식 기반 import 그래프라 문자열을 조합한 동적 import를 놓친다 | `demo.ts`에 `import('../' + 'api')`를 넣는다 | MVP-02에서 해소(U-005) |
| 생성된 문장의 모든 tappable item에 설명이 있음 (#28) | `backend/tests/test_llm_validation.py::test_9_every_tappable_item_needs_an_explanation` | 테스트 본문을 확인하지 않았다 | 검사 9를 target item에만 적용한다 | 대기 |
| 같은 노출이 두 번 평가되지 않음 (#18) | `backend/tests/test_evidence_concurrency.py::test_concurrent_self_reports_on_an_item_in_review_record_one_evidence` | 테스트 본문을 확인하지 않았다 | 선행 검사를 끄고 IntegrityError를 409로 매핑하지 않게 한다 | 대기 |
| 기본 history를 자기 데이터만으로 조회 가능 (#22) | `backend/tests/test_history_api.py`의 자기 데이터 테스트들 | "어떤 요청으로도"에 대해 query 파라미터 공격을 보지 않는다 | history가 `user_id` query 파라미터를 받아 쓰게 한다 | 대기 |
| history가 잘렸는지를 응답이 말함 (#23) | `backend/tests/e2e/test_history_browser.py::test_rows_exactly_at_the_limit_are_not_reported_as_truncated` | 테스트 본문을 확인하지 않았다 | frontend가 `rows.length === limit`으로 판정하게 한다 | 대기 |
| background batch generation/validation/Ready Pool 동작 (#26) | `backend/tests/test_worker_pool_integration.py::test_the_review_context_job_creates_the_candidate_for_that_stage` | 테스트 본문을 확인하지 않았다 | 생성 문장의 `context_stage`를 anchor로 고정한다 | 대기 |
| 하루 provider 사용량 한도에 도달하면 신규 generation이 멈추고 학습 세션은 계속 진행됨 (#33) | `backend/tests/test_jobs_worker.py::test_a_study_session_keeps_running_while_the_ceiling_is_reached` | 가짜 runner와 손으로 넣은 candidate로 돈다 | 더 강한 판인 `test_worker_pool_integration.py` 쪽만 변이해 보면 충분하다 | 대기 |

### 1.2 설명과 실제 단언이 어긋난 테스트 (4건)

이름·주석이 말하는 것과 실제로 단언하는 것이 다르다. 주석은 고치지 않았다.

| 테스트 | 설명이 말하는 것 | 실제 | 상태 |
|---|---|---|---|
| `backend/tests/test_scenarios.py::test_scenario_c_reinforcement_stays_available_below_the_minimum` | 주입한 최소 노출 값으로 확인한다 | 실제로는 기본값을 주입한다 | 대기 |
| `backend/tests/test_core_e2e.py`, `backend/tests/e2e/test_core_e2e_browser.py`, `backend/tests/e2e/test_frontend_invariants.py` | `MINIMUM_EXPOSURES`를 주입해 엔진이 config를 읽는지 본다 | 해당 변이를 넣어도 통과했다(변이 세부 미기록) | 대기 |
| `backend/tests/test_learning_selection.py::test_below_the_threshold_the_configured_ratios_are_used` | 기준 미만에서 설정된 비율을 쓴다 | 해당 변이를 넣어도 통과했다(변이 세부 미기록) | 대기 |
| `backend/tests/test_auth_cli.py::test_create_user_rejects_a_password_below_the_minimum` | 명세 하한 미만 password를 거부한다 | 명세 하한이 아니라 구현 상수를 기준으로 단언한다 | 대기 |

### 1.3 도달할 수 없는 handler

-   **validation 검사 10의 handler는 도달할 수 없어 검증되지 않았다.** 신규 target 수 상한과 전체
    target 수 상한이 같은 config 키에서 오는 동안 검사 10은 구조적으로 발화하지 않는다. 상한이
    분리되면 그때 handler 경로 테스트가 필요하다. 근거: `spec/CHANGELOG.md [29]`. 상태: 대기

## 2. 명세 공백 (5건)

규칙을 정하지 않고 사실만 명세에 기록한 것이다.

| 공백 | 근거 | 상태 |
|---|---|---|
| 출력 토큰 상한이 없다 | `spec/CHANGELOG.md [54]` | 대기 |
| 예외로 끝난 provider 호출이 사용량에 계상되지 않는다 | `spec/CHANGELOG.md [55]` | 대기 |
| SDK timeout이 claim lease보다 길 수 있다 | `spec/CHANGELOG.md [55]` | 대기 |
| 한도 integer의 허용 범위가 없다(0이면 생성이 영구히 멈춘다) | `spec/CHANGELOG.md [56]` | 대기 |
| seed를 추가로 적재할 수 없다 | `spec/CHANGELOG.md [53]` | 대기 |

## 3. 품질 (4건)

| 항목 | 근거 | 상태 |
|---|---|---|
| 2-target candidate의 reason 병합으로 reinforcement 지분이 왜곡된다(스키마 변경 필요) | `spec/CHANGELOG.md [44]` 뒤의 reason 병합 기록 | 대기 |
| seed loader가 생성 검증 규칙을 적용하지 않는다 | 세부 미기록 | 대기 |
| skip과 self-report가 동시에 오면 드물게 500이 난다(read-or-create race) | `spec/CHANGELOG.md [40]` 절의 read-or-create 한계 기록, `spec/mvp-01-core/10_ERROR_HANDLING.md`의 `DB Failure` | 대기 |
| "몰랐음"을 반복하면 같은 문장이 연속으로 노출된다(anchor → near_original) | 세부 미기록 | 대기 |

## 4. 운영 확인 (2건)

자동 테스트로 확인할 수 없어 사용자가 운영 환경에서 확인할 항목이다.

| 합격 기준 | 확인할 것 | 상태 |
|---|---|---|
| 모바일에서 세션 시작/진행/종료 가능 (#1) | iOS 실기기에서 세션 종료까지 진행한다 | 대기 |
| Postgres 직접 인터넷 노출 없음 (#37) | 외부에서 DB 포트 접속이 실패하는지 확인한다 | 대기 |
