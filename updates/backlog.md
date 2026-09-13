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

## 5. MVP-02에서 제기된 항목 (17건)

MVP-02 진행 중 제기되었으나 이번 범위에서 하지 않기로 한 항목이다.

| 항목 | 근거 | 상태 |
|---|---|---|
| CSP(Content-Security-Policy) 도입: API origin을 하드코딩하지 않고 정적 헤더에 주입하는 설계 필요 | MVP-02 보안 검토에서 제기. `spec/04_SECURITY_AND_DATA.md`의 `HTML 삽입과 URL 값 (MVP-02 확정)` | 대기 |
| API 프로세스에 로깅 설정이 없어 `ruby.invalid_stored`의 `sentence_id`가 운영 로그에 보이지 않는다 | MVP-02 Wave 2 구현에서 제기. `spec/mvp-01-core/11_OBSERVABILITY.md`의 후리가나 로그 이벤트 | 대기 |
| 같은 초에 백업이 두 번 만들어지면 백업 파일 이름이 충돌한다(backfill `--apply`를 동시에 돌리면 늦은 쪽이 exit 2로 끝나며 데이터는 안전하다) | MVP-02 Wave 2 구현에서 제기. `docs/decisions/ADR-021-furigana-ruby.md`의 backfill 스크립트 | 대기 |
| backfill 불일치 출력이 bidi 제어문자(U+202E 등)를 이스케이프하지 않는다(C0·C1·U+007F만 이스케이프) | MVP-02 Wave 2 게이트에서 제기. `spec/mvp-01-core/11_OBSERVABILITY.md`의 CLI 출력 이스케이프 | 대기 |
| 브라우저 e2e 격리 검사 (f)가 WebSocket 요청을 기록·차단하지 않는다(식별자 AST 검사 (d)가 막고 있어 이중 방어 중 한 겹만 빈다) | MVP-02 Wave 2 게이트에서 제기. `spec/04_SECURITY_AND_DATA.md`의 `격리 검사 (MVP-02 확정)` | 대기 |
| `local-store.ts`의 `read`가 메모리에 든 값의 참조를 그대로 돌려준다(현재 호출자는 복사해서 쓴다) | MVP-02 Wave 2 게이트에서 제기. `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)` | 대기 |
| 후리가나 켬/끔 e2e 비교(켠 상태의 요청이 끈 상태와 같다)에 self-report·probe 응답(evidence를 만드는 요청) 경로가 없다. 탭·설명·번역·다음 문장만 비교한다 | MVP-02 Wave 3 게이트에서 제기(검증 후보). `backend/tests/e2e/test_furigana_browser.py`, `spec/mvp-02-onboarding/12_TEST_PLAN.md`의 `test_furigana_browser.py` 행 | 대기 |
| demo 진도 검증 속도 테스트가 200ms 절대 기준이라 느린 CI에서 흔들릴 수 있다 | MVP-02 Wave 3 구현에서 제기. `frontend/tests/unit/demo-progress.test.ts` | 대기 |
| 가나 진도의 맞음/틀림 수 저장값이 최대 안전 정수이면 다음 응답의 값이 형식 검증을 통과하지 못해 그 페이지 동안 그 글자의 기록이 멈춘다(오류는 없다) | MVP-02 Wave 3 구현에서 제기. `frontend/src/kana/progress.ts`, `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)` | 대기 |
| demo fixture 스크립트가 구조 오류를 stderr에 낼 때 문구 안의 seed 값을 제어문자 이스케이프하지 않는다(stdout의 제외·미커버·ruby 실패 줄은 이스케이프한다) | MVP-02 Wave 3 구현에서 제기. `scripts/build_demo_fixture.py`, `spec/mvp-01-core/11_OBSERVABILITY.md`의 CLI 출력 이스케이프 | 대기 |
| `isDemoProgress`가 다시 보기 문장이 아닌 위치가 `seen - 1`인지 보지 않는다(본 문장 중 하나인지만 본다) | MVP-02 Wave 3 구현에서 제기. `frontend/src/demo/progress.ts`, `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)` | 대기 |
| e2e 도우미 `backend/tests/e2e/study_flow.py`의 `self_report`가 닫히는 중인 설명 시트의 버튼과 겹쳐 잘못 누를 수 있다(e2e에서 우회하고 있다) | MVP-02 Wave 3 구현에서 제기. `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `설명 시트` | 대기 |
| demo 화면 문구에 "새 문맥 재등장을 약속하지 않는다"를 직접 부정하는 단언이 없다(같은 문장 다시 보기만 단언한다) | MVP-02 Wave 3 구현에서 제기(검증 후보). `spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md`의 demo 체험 항목 | 대기 |
| localStorage 저장값에 `login_id`·서버 응답이 들어가지 않는다는 직접 테스트가 없다(정확한 키 집합 형식 검증이 막고 있다) | MVP-02 Wave 3 구현에서 제기(검증 후보). `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)` | 대기 |
| 가나 학습에 소리(발음 재생)·획순이 없다는 전용 테스트가 없다 | MVP-02 Wave 3 구현에서 제기(검증 후보). `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `가나 학습` | 대기 |
| 부하가 걸린 상태에서 PWA e2e의 `.login-form` 15초 대기가 시간 초과로 1회 실패했다(단독 재실행은 통과) | MVP-02 Wave 3 구현에서 제기. `backend/tests/e2e/test_pwa_installable.py`가 쓰는 로그인 도우미 `backend/tests/e2e/study_flow.py` | 대기 |
| wrangler 설정 파일로 `workers_dev`·`preview_urls` 끄기 고정(설정 파일 없는 `deploy`가 배포마다 두 설정을 다시 켜서 지금은 대시보드에서 손으로 끈다) | MVP-02 운영 배포(2026-09-14)에서 확인. `docs/decisions/ADR-020-production-topology.md`의 결정 5 `설정 파일로 옮기는 조건`, `infra/DEPLOY.md` 6.3 | 대기 |
