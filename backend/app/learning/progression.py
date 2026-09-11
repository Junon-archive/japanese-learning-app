"""`user_item_learning_state` --- passive 신호, incidental 승격, probe 기록.

이 모듈은 `context_stage`를 **읽고 기록만** 한다. 누가 언제 다음 stage로 올리는지는
명세 공백이며(07_SRS_SPEC.md의 progression 표는 "기본 정책"이지 전이 규칙이 아니다),
여기서 발명하지 않는다.

mastery도 FSRS도 여기서 바뀌지 않는다. probe skip은 evidence가 아니므로
`mastery.record_explicit_evidence`를 부르지 않는다(02_LEARNING_POLICY.md의 `Skip`).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.enums import ContextStage, ExplicitSignal
from app.models.learning import UserItemLearningState

# 행이 생기는 시점은 그 item을 처음 만나는 때다. 07_SRS_SPEC.md의 progression은
# `Exposure 1 -> anchor`에서 시작하고, `anchor_sentence_id`가 "최초 학습 문맥"이므로
# 그 최초 문맥의 stage가 곧 초기값이다. 뒤쪽 stage에서 시작하면 첫 노출이 이미
# varied/new_context인 것처럼 기록된다.
INITIAL_CONTEXT_STAGE = ContextStage.ANCHOR

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


def promote_incidental(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    signal: ExplicitSignal,
    now: datetime,
) -> bool:
    """incidental click 뒤에 온 self-report로 학습 target 승격 여부를 정한다.

    click 자체로는 이 함수가 호출되지 않는다 --- click은 raw event로만 남는다.
    `알고 있었음`이면 아무 상태도 만들지 않는다.

    새로 승격된 경우에만 True다. 이미 target이면 False이므로 호출부가 신규 등록을
    두 번 하지 않는다.
    """
    if signal not in PROMOTING_SIGNALS:
        return False

    state = _get_or_create(db, user_id=user_id, learning_item_id=learning_item_id, now=now)
    if state.is_active_learning_target:
        return False

    state.is_active_learning_target = True
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
