"""fsrs 6.x 라이브러리 바인딩 (ADR-003).

`fsrs` import는 `app/srs/` 밖으로 나가지 않는다(G3). 나머지 코드가 보는 것은
`ReviewState` 컬럼과 `ExplicitSignal`뿐이다.

`Card`는 매 review마다 `review_states` 컬럼에서 재구성하고 `card_id`는 버린다 ---
행의 identity는 `(user_id, learning_item_id)` unique 하나다(ADR-003).
"""

from __future__ import annotations

from fsrs import Card, Rating, Scheduler, State

from app.config import AppConfig
from app.models.enums import ExplicitSignal
from app.models.learning import ReviewState

# 스케줄을 만든 파라미터 집합의 식별자. 파라미터를 바꾸면 이 값을 올린다.
FSRS_PARAMS_VERSION: str = "fsrs/6.3.2/default"

# 07_SRS_SPEC.md의 explicit signal 매핑. probe 응답도 같은 매핑을 쓴다.
# `Rating.Easy`는 MVP UI에 없으므로 여기에도 없다.
RATING_BY_SIGNAL: dict[ExplicitSignal, Rating] = {
    ExplicitSignal.UNKNOWN: Rating.Again,
    ExplicitSignal.UNCERTAIN: Rating.Hard,
    ExplicitSignal.KNOWN: Rating.Good,
}


def rating_for_signal(signal: ExplicitSignal) -> Rating:
    """explicit signal 3값만 rating이 된다.

    인자 타입이 `EventType`도 문자열도 아닌 이유가 불변식 #2다. click / reveal /
    probe skip / no-click은 `ExplicitSignal`로 **표현할 수 없으므로** 이 함수에
    도달할 수 없다. 무신호는 `record_no_signal_review`로 간다.
    """
    return RATING_BY_SIGNAL[signal]


def build_scheduler(config: AppConfig) -> Scheduler:
    """fuzzing만 설정하고 나머지는 라이브러리 기본값을 그대로 쓴다.

    `learning_steps` / `maximum_interval`을 건드리지 않는다. interval을 줄여
    최소 노출 5회를 채우는 것은 불변식 #4 위반이며, 그 목적은 Learning Engine의
    `reinforcement` presentation이 담당한다(07_SRS_SPEC.md).
    """
    return Scheduler(enable_fuzzing=config.srs.fsrs_enable_fuzzing)


def to_card(state: ReviewState) -> Card:
    """`review_states` -> `Card` (ADR-003 매핑표)."""
    return Card(
        card_id=None,
        state=State(state.state),
        step=state.step,
        stability=state.stability,
        difficulty=state.difficulty,
        due=state.next_review_at,
        last_review=state.last_review_at,
    )


def write_card(state: ReviewState, card: Card) -> None:
    """`Card` -> `review_states` (ADR-003 매핑표). `card_id`는 저장하지 않는다."""
    state.state = int(card.state)
    state.step = card.step
    state.stability = card.stability
    state.difficulty = card.difficulty
    state.next_review_at = card.due
    state.last_review_at = card.last_review
