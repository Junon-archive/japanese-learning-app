# ADR-003 --- FSRS Library Binding

Status: Accepted

Decision: FSRS 라이브러리는 PyPI distribution `fsrs` 6.3.2를 쓴다.
`pip install py-fsrs`는 실패한다 --- py-fsrs는 GitHub 프로젝트명일 뿐
배포명은 `fsrs`다. `Rating.Easy`는 MVP UI에서 사용하지 않는다
(`spec/mvp-01-core/07_SRS_SPEC.md`).

fsrs 6.x `Card`는 `card_id, state, step, stability, difficulty, due,
last_review`만 갖는다. `04_DB_SPEC.md`가 가정한 `reps`, `lapses`,
`scheduled_days`는 존재하지 않는다.

## 결정 사항

-   **`reps` / `lapses`: 유지한다.** 단 FSRS가 주는 값이 아니라
    애플리케이션이 review 기록 시 직접 증가시키는 자체 카운터다
    (`lapses`는 `Again` 기록 시 증가). `07_SRS_SPEC.md`의 no-signal
    review 규칙과 `12_TEST_PLAN.md`의 lapse 검증이 이 값을 참조하므로
    제거하지 않는다. 비용은 정수 두 컬럼이다.
-   **`scheduled_days`: 스키마에서 제거한다.** fsrs 6에서 스케줄은
    절대시각 `Card.due`이고 `scheduled_days`는 `due - last_review`의
    파생값이다. 중복 저장하지 않는다.
-   **`step`을 추가한다.** fsrs 6의 learning/relearning step index이며
    이것 없이는 Card를 복원할 수 없다. `state = Review`일 때 NULL이다.
-   **`Card.card_id`는 저장하지 않는다.** `review_states`의 identity는
    `(user_id, learning_item_id)` unique다(`04_DB_SPEC.md`). Card는 매
    review마다 DB 컬럼에서 재구성하고 `card_id`는 버린다. 외부 식별자를
    하나 더 두면 canonical identity가 둘이 된다.
-   **fuzzing은 MVP에서 끈다** (`Scheduler(enable_fuzzing=False)`).
    fuzzing은 대규모 덱의 due 쏠림을 흩는 ± jitter이며 사용자 1명
    규모에서는 이득이 없고 테스트 재현성만 깎는다. 이는 `interval을
    억지로 cap하지 않는다`(07_SRS_SPEC.md)와 충돌하지 않는다 --- cap이
    아니라 FSRS가 계산한 interval을 jitter 없이 그대로 쓰는 것이므로
    오히려 스케줄을 더 충실히 따른다. 값은
    `14_CONFIGURATION.md`(`srs.fsrs_enable_fuzzing: false`)에 둔다.

## Card ↔ review_states 매핑

``` text
Card.card_id     -> (저장하지 않음)
Card.state       -> state              smallint  1=Learning 2=Review 3=Relearning
Card.step        -> step               int null
Card.stability   -> stability          float null
Card.difficulty  -> difficulty         float null
Card.due         -> next_review_at     timestamptz not null
Card.last_review -> last_review_at     timestamptz null

(FSRS 밖, 애플리케이션이 유지)
                    user_id, learning_item_id   unique
                    reps, lapses                int not null default 0
                    fsrs_params_version
                    deferred_until              timestamptz null
                    meaningful_exposure_count   (canonical source는 item_exposures)
```

`ReviewLog`는 MVP에서 별도 테이블로 저장하지 않는다. 필요한 기록은
기존 event/exposure 테이블이 이미 갖고 있다.
