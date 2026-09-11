"""FSRS review 기록 (07_SRS_SPEC.md).

이 모듈은 `review_states`만 쓴다. mastery는 `app/learning/mastery.py`가 별도로
갱신한다 --- FSRS scheduling state와 mastery score는 분리한다(불변식 #3).

트랜잭션은 소유하지 않는다(G7). 세션에 붙은 인스턴스를 바꾸고 flush까지만 하며,
commit은 호출하는 `services/`가 한 번 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from fsrs import Card, Rating
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models.enums import ExplicitSignal
from app.models.learning import ReviewState
from app.srs.fsrs_binding import (
    FSRS_PARAMS_VERSION,
    build_scheduler,
    rating_for_signal,
    to_card,
    write_card,
)


def _locked_review_state(db: Session, *, user_id: int, learning_item_id: int) -> ReviewState | None:
    """같은 item에 대한 동시 review가 서로의 FSRS 상태를 덮어쓰지 않게 잠근다."""
    return db.execute(
        sa.select(ReviewState)
        .where(
            ReviewState.user_id == user_id,
            ReviewState.learning_item_id == learning_item_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def record_explicit_review(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    signal: ExplicitSignal,
    now: datetime,
    config: AppConfig,
) -> ReviewState:
    """explicit signal 하나를 FSRS review로 기록한다.

    `reps` / `lapses` 증가는 애플리케이션 카운터이며(ADR-003) **이 함수 한 곳에만**
    존재한다. 다른 경로에서 올리면 lapse 수가 explicit evidence 수와 갈린다.
    """
    state = _locked_review_state(db, user_id=user_id, learning_item_id=learning_item_id)
    rating = rating_for_signal(signal)
    # 아직 스케줄이 없는 item은 지금 due인 새 카드로 시작한다.
    card = to_card(state) if state is not None else Card(card_id=None, due=now)
    # ReviewLog는 저장하지 않는다(ADR-003). 기록은 learning_events / item_exposures에 있다.
    reviewed, _log = build_scheduler(config).review_card(card, rating, now)

    if state is None:
        state = ReviewState(
            user_id=user_id,
            learning_item_id=learning_item_id,
            reps=0,
            lapses=0,
        )
        db.add(state)

    write_card(state, reviewed)
    state.fsrs_params_version = FSRS_PARAMS_VERSION
    state.reps += 1
    if rating is Rating.Again:
        state.lapses += 1

    db.flush()
    return state


def record_no_signal_review(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    now: datetime,
    config: AppConfig,
) -> ReviewState | None:
    """무신호 review: rating을 **추론하지 않는다** (불변식 #2, 07_SRS_SPEC.md).

    no-click은 Good도 Easy도 아니다. FSRS memory state(`stability` / `difficulty` /
    `state` / `step`)도 애플리케이션 카운터(`reps` / `lapses`)도 건드리지 않는다.
    하는 일은 `deferred_until` 하나뿐이며, 그 목적은 증거 없는 review가 FSRS를
    오염시키지 않으면서도 같은 due item이 같은 세션에서 무한히 다시 뽑히지 않게
    하는 것이다.

    `next_review_at`은 그대로이므로 item은 **여전히 due다.** 그것이 의도다.

    `review_states` 행이 없으면(`new` / `exploration` presentation) defer할 스케줄이
    없으므로 `None`을 돌려준다. 이때 `passive_no_signal_count`를 올리는 것은
    `user_item_learning_state`를 소유한 쪽의 일이다.
    """
    state = _locked_review_state(db, user_id=user_id, learning_item_id=learning_item_id)
    if state is None:
        return None

    state.deferred_until = now + timedelta(hours=config.learning.passive_review_deferral_hours)

    db.flush()
    return state
