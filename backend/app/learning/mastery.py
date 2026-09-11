"""Mastery EMA. mastery 값을 바꾸는 **유일한** 모듈이다 (ADR-007 G5).

`02_LEARNING_POLICY.md`의 explicit evidence만 여기로 들어온다. click /
explanation reveal / translation reveal / sentence_viewed / passive exposure /
probe skip은 raw event로만 남고 이 모듈을 부르지 않는다 --- 그래야
`clicked = unknown`도 `not clicked = known`도 성립하지 않는다.

FSRS 컬럼은 건드리지 않는다. mastery score와 scheduling state는 다른 테이블이고
다른 소유자다(ADR-003, ADR-007).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.enums import ExplicitSignal
from app.models.learning import UserMastery

# 계산 코드의 신원이다. 운영자가 조정하는 정책값이 아니므로 config 키로 두지 않는다.
# 알고리즘이 바뀌면 이 상수가 바뀌고, 저장된 값이 어느 계산으로 나왔는지 구분된다.
MASTERY_ALGORITHM_VERSION: str = "ema-v1"

# 02_LEARNING_POLICY.md의 표 그대로다. `알고 있었음`이 1.0이 아닌 이유는
# 자기보고 한 번이 완전한 이해의 증거가 아니기 때문이다.
OBSERVATION: dict[ExplicitSignal, float] = {
    ExplicitSignal.UNKNOWN: 0.0,
    ExplicitSignal.UNCERTAIN: 0.4,
    ExplicitSignal.KNOWN: 0.8,
}


def ema(old: float | None, observation: float, alpha: float) -> float:
    """`alpha`는 인자다. 여기서 config를 읽지 않는다 --- 테스트가 값을 주입해야
    하고, 그래야 alpha를 무시하는 구현이 테스트를 통과하지 못한다.

    `old`가 NULL이면 첫 evidence가 그대로 값이 된다. NULL은 "능력 0"이 아니라
    "아직 evidence 없음"이므로 0.0으로 시작해 끌어올리지 않는다.
    """
    if old is None:
        return observation
    return old * (1.0 - alpha) + observation * alpha


def record_explicit_evidence(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    signal: ExplicitSignal,
    now: datetime,
    alpha: float,
) -> UserMastery:
    """explicit evidence 1건으로 comprehension mastery를 갱신한다.

    `evidence_count`는 **mastery update에 실제 쓰인 explicit evidence 개수**다.
    meaningful exposure count가 아니므로 이 모듈은 `item_exposures`를 읽지 않는다.

    `listening_mastery`는 대입하지 않는다. MVP에 audio가 없어 측정 자체가 없고,
    NULL은 "능력 0"이 아니라 "측정하지 않음"이다.
    """
    observation = OBSERVATION[signal]
    mastery = db.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == user_id,
            UserMastery.learning_item_id == learning_item_id,
        )
    ).scalar_one_or_none()

    if mastery is None:
        mastery = UserMastery(
            user_id=user_id,
            learning_item_id=learning_item_id,
            comprehension_mastery=ema(None, observation, alpha),
            evidence_count=1,
            mastery_algorithm_version=MASTERY_ALGORITHM_VERSION,
            last_updated_at=now,
        )
        db.add(mastery)
    else:
        mastery.comprehension_mastery = ema(mastery.comprehension_mastery, observation, alpha)
        mastery.evidence_count = mastery.evidence_count + 1
        mastery.mastery_algorithm_version = MASTERY_ALGORITHM_VERSION
        mastery.last_updated_at = now

    db.flush()
    return mastery
