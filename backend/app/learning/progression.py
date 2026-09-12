"""`user_item_learning_state` --- context ladder, passive 신호, incidental 승격, probe.

`context_stage` 전이 규칙의 canonical 정의는 07_SRS_SPEC.md의 `Context Progression`
-> `전이 규칙 (MVP 확정)`이다(ADR-012). 이 모듈의 `advance_context_stage()`가 그
규칙을 수행하는 유일한 자리이고, 부르는 쪽은 exposure를 확정하는 단일 경로다 ---
ladder를 움직이는 자리와 노출을 세는 자리가 다르면 두 값이 어긋난다.

mastery도 FSRS도 여기서 바뀌지 않는다. probe skip은 evidence가 아니므로
`mastery.record_explicit_evidence`를 부르지 않는다(02_LEARNING_POLICY.md의 `Skip`).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.enums import ContextStage, EventType, ExplicitSignal
from app.models.learning import UserItemLearningState

# ladder 순서 (07_SRS_SPEC.md). `anchor < near_original < varied < new_context`.
# **canonical 선언은 여기 하나다** --- `context_repair`의 stage 비교(selection.py)와
# 전이 규칙이 같은 순서를 봐야 한다.
STAGE_LADDER: tuple[ContextStage, ...] = (
    ContextStage.ANCHOR,
    ContextStage.NEAR_ORIGINAL,
    ContextStage.VARIED,
    ContextStage.NEW_CONTEXT,
)

# explicit `몰랐음`. 이것만이 ladder를 내린다. click이나 probe 제시는 여기 없다 ---
# 무신호는 실패가 아니라 그냥 노출이고, 표의 단위가 signal이 아니라 exposure이므로
# 무신호도 ladder를 올린다(ADR-012).
UNKNOWN_SIGNAL_EVENTS: tuple[EventType, ...] = (
    EventType.SELF_REPORT_UNKNOWN,
    EventType.MASTERY_PROBE_UNKNOWN,
)

# 행이 생기는 시점은 그 item을 처음 만나는 때다. 07_SRS_SPEC.md의 progression은
# `Exposure 1 -> anchor`에서 시작하고, `anchor_sentence_id`가 "최초 학습 문맥"이므로
# 그 최초 문맥의 stage가 곧 초기값이다. 뒤쪽 stage에서 시작하면 첫 노출이 이미
# varied/new_context인 것처럼 기록된다.
INITIAL_CONTEXT_STAGE = ContextStage.ANCHOR


def stage_rank(stage: ContextStage) -> int:
    """ladder 위치. `context_repair` 판정의 `context_stage < S_fail` 비교가 쓴다."""
    return STAGE_LADDER.index(stage)


def _one_step(stage: ContextStage, *, delta: int) -> ContextStage:
    """한 칸 이동. 바닥은 `anchor`, 천장은 `new_context`다."""
    return STAGE_LADDER[min(len(STAGE_LADDER) - 1, max(0, stage_rank(stage) + delta))]


# incidental click을 학습 target으로 승격시키는 신호. `알고 있었음`은 없다 ---
# 이미 아는 표현을 SRS 신규 item으로 강제 등록하지 않는다(02_LEARNING_POLICY.md).
PROMOTING_SIGNALS: frozenset[ExplicitSignal] = frozenset(
    {ExplicitSignal.UNKNOWN, ExplicitSignal.UNCERTAIN}
)


def _get_or_create(
    db: Session, *, user_id: int, learning_item_id: int, now: datetime
) -> UserItemLearningState:
    state = db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user_id,
            UserItemLearningState.learning_item_id == learning_item_id,
        )
    ).scalar_one_or_none()
    if state is None:
        state = UserItemLearningState(
            user_id=user_id,
            learning_item_id=learning_item_id,
            context_stage=INITIAL_CONTEXT_STAGE,
            updated_at=now,
        )
        db.add(state)
        db.flush()
    return state


def bump_no_signal(db: Session, *, user_id: int, learning_item_id: int, now: datetime) -> None:
    """무신호 presentation 1회를 기록한다 (07_SRS_SPEC.md의 `No-signal review`).

    `passive_exposures_before_probe`가 이 값을 보고 probe 대상을 고른다. 무신호는
    rating이 아니므로 여기서 mastery도 FSRS도 바뀌지 않는다 --- `deferred_until`은
    `app/srs/`의 소유다.
    """
    state = _get_or_create(db, user_id=user_id, learning_item_id=learning_item_id, now=now)
    state.passive_no_signal_count = state.passive_no_signal_count + 1
    state.updated_at = now
    db.flush()


def advance_context_stage(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    shown_stage: ContextStage,
    failed: bool,
    now: datetime,
) -> ContextStage:
    """meaningful exposure 1건이 확정된 item의 ladder를 움직인다 (07_SRS_SPEC.md).

    ``` text
    S_shown = 방금 기록된 item_exposures.context_stage
    S_cur   = user_item_learning_state.context_stage

    failed(= explicit `몰랐음`)  S_cur <- min(S_cur, one_step_down(S_shown))
    아니면                       S_cur <- max(S_cur, one_step_up(S_shown))
    ```

    `알고 있었음` / `애매함` / **무신호**는 모두 올린다. 위 표의 단위가 signal이
    아니라 exposure 수이기 때문이다. 내리는 것은 explicit `몰랐음` 하나뿐이다.

    `min` / `max`인 이유는 낮은 stage의 presentation이 이미 진행한 ladder를 끌어
    내리지 않게 하기 위해서다 --- Ready Pool에 남아 있던 낮은 stage candidate나
    `Pool Fallback` 2단계의 anchor reinforcement는 성공해도 stage를 되돌리지 않는다.
    반대로 실패는 **실제로 본 문맥**을 기준으로 한 단계 내려간다(ADR-012).

    행이 없으면 `anchor`에서 시작한다. 호출은 exposure 기록과 같은 트랜잭션·같은
    idempotency guard 아래에 있어야 한다 --- 재시도가 ladder를 두 번 밀면 안 된다.
    """
    state = _get_or_create(db, user_id=user_id, learning_item_id=learning_item_id, now=now)
    current = state.context_stage
    if failed:
        updated = min(current, _one_step(shown_stage, delta=-1), key=stage_rank)
    else:
        updated = max(current, _one_step(shown_stage, delta=1), key=stage_rank)

    if updated is not current:
        state.context_stage = updated
        state.updated_at = now
        db.flush()
    return updated


def promote_incidental(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    sentence_id: int,
    signal: ExplicitSignal,
    now: datetime,
) -> bool:
    """incidental click 뒤에 온 self-report로 학습 target 승격 여부를 정한다.

    click 자체로는 이 함수가 호출되지 않는다 --- click은 raw event로만 남는다.
    `알고 있었음`이면 아무 상태도 만들지 않는다.

    새로 승격된 경우에만 True다. 이미 target이면 False이므로 호출부가 신규 등록을
    두 번 하지 않는다.

    승격이 실제로 일어나면 `sentence_id`가 그 item의 **최초 학습 문맥**이 된다
    (07_SRS_SPEC.md의 `anchor_sentence_id 지정` 1번). 사용자가 실제로 만나 물어본
    문장이기 때문이다. 이것이 없으면 anchor가 `sentences.id ASC`로 뽑힌 낯선 문장이
    되고, target이 아닌 item의 self-report는 exposure를 만들지 않으므로(ADR-013) 그
    문맥이 통째로 사라진다. **NULL일 때만 쓴다** --- 이미 있는 anchor는 덮지 않는다.
    """
    if signal not in PROMOTING_SIGNALS:
        return False

    state = _get_or_create(db, user_id=user_id, learning_item_id=learning_item_id, now=now)
    if state.is_active_learning_target:
        return False

    state.is_active_learning_target = True
    if state.anchor_sentence_id is None:
        state.anchor_sentence_id = sentence_id
    state.updated_at = now
    db.flush()
    return True


def record_probe_outcome(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    response: ExplicitSignal | None,
    now: datetime,
) -> None:
    """probe 결과를 기록한다. `response = None`이 건너뛰기다.

    skip을 `ExplicitSignal`로 표현할 수 없게 두는 것이 핵심이다. skip은 mastery
    evidence도 FSRS grade도 아니고 무신호이므로, 타입상 `record_explicit_evidence`에
    넘어갈 수가 없다.

    답한 경우의 mastery 갱신은 호출부가 `mastery.record_explicit_evidence`로 따로
    한다. 여기서는 하지 않는다 --- 두 곳에서 갱신하면 evidence가 이중 집계된다.
    """
    state = _get_or_create(db, user_id=user_id, learning_item_id=learning_item_id, now=now)
    # 답했든 건너뛰었든 물어본 것은 사실이다. probe cooldown은 이 시각을 본다.
    state.last_probe_at = now
    if response is None:
        state.probe_skip_count = state.probe_skip_count + 1
    state.updated_at = now
    db.flush()
