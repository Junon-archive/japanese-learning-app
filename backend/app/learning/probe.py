"""Probe 대상 선정과 세션 내 probe pacing.

두 문서가 반씩 담당한다. **어떤 item을 묻는가**는 `02_LEARNING_POLICY.md`의
`Probe 대상 우선순위`, **언제 묻는가**는 `06_LEARNING_ENGINE.md`의 `Probe Pacing`이
canonical이다. 이 모듈은 그 둘을 합쳐 "이번 presentation에 어떤 item을 물을
것인가"까지만 답한다.

경계:

-   `mastery_probe_shown` event 발급과 `probe_id` 부여는 **하지 않는다.**
    `probe_id`는 그 event의 정수 id이고(ADR-009) event 기록은 `services/`의
    일이다. 이 모듈은 트랜잭션도 소유하지 않는다(G7).
-   probe 응답 처리도 하지 않는다. skip 포함한 결과 기록은 이미
    `learning/progression.py`의 `record_probe_outcome`에 있다.
-   `app.srs`를 import하지 않고 FSRS 컬럼도 mastery 컬럼도 쓰지 않는다
    (ADR-007의 G1/G5). probe skip은 mastery evidence도 FSRS grade도 아니다.

**재호출하면 같은 답이 나오지 않는다.** probe를 하나 실으면 그 사실이 세션 event에
남아 다음 호출의 pacing과 제외 집합이 달라진다. 그래서 열린 presentation을 다시
받는 경로는 이 함수를 다시 부르지 않고 `05_API_SPEC.md`의 결정론적
`client_event_id`로 **기존 probe event를 조회**해야 한다.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.learning.mastery import OBSERVATION
from app.models.enums import EventType, ExplicitSignal
from app.models.learning import UserItemLearningState, UserMastery
from app.models.study import LearningEvent, StudyPresentation


class ProbePriority(enum.IntEnum):
    """`02_LEARNING_POLICY.md`의 `Probe 대상 우선순위`. 작을수록 먼저 묻는다.

    MVP 목록은 **2단**이다(ADR-011). v0.2의 `passive exposure가 반복됐지만 explicit
    evidence가 없는 item`은 독립 순위가 아니라 1번 **내부의 정렬 기준**이 되었고
    (`_passive_rank`), `서로 충돌하는 evidence가 있는 item`은 MVP에서 제외됐다 ---
    EMA 아래에서 known과 unknown이 섞이면 mastery가 가운데로 모여 2번이 이미 잡는다.
    """

    NO_EXPLICIT_EVIDENCE = 1
    UNCERTAIN = 2


@dataclass(frozen=True)
class ProbeTarget:
    learning_item_id: int
    priority: ProbePriority


@dataclass(frozen=True)
class ProbePacing:
    """`Probe Pacing`의 조건 1·2가 보는 세션 상태."""

    probes_shown: int
    # 이번 presentation을 **뺀** 수.
    presentations_before_current: int
    # None이면 이번 세션에 아직 probe가 없다.
    presentations_after_last_probe: int | None


# 조건 3의 제외 "방금 explicit feedback을 받은 item"을 세션 단위로 읽는다.
# self-report 3종이 그 explicit feedback이다.
#
# `mastery_probe_shown`을 함께 넣는 이유: 응답하지 않은 probe는 `last_probe_at`을
# 남기지 않으므로 cooldown이 잡지 못한다. 빼면 한 세션에서 같은 item을 두 번 묻게
# 된다. probe 응답(known/uncertain/unknown/skipped)은 `record_probe_outcome`이
# `last_probe_at`을 남기므로 cooldown이 이미 담당한다.
SESSION_FEEDBACK_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.SELF_REPORT_KNOWN,
        EventType.SELF_REPORT_UNCERTAIN,
        EventType.SELF_REPORT_UNKNOWN,
        EventType.MASTERY_PROBE_SHOWN,
    }
)


def choose_probe(
    db: Session,
    *,
    user_id: int,
    study_session_id: int,
    presentation_id: int,
    target_item_ids: Sequence[int],
    now: datetime,
    config: AppConfig,
) -> ProbeTarget | None:
    """이번 presentation에 실을 probe 대상. 조건 하나라도 어긋나면 None이다.

    `presentation_id`는 이번 presentation이다. pacing은 이 presentation을 **뺀**
    세션 상태를 보므로, 호출부가 presentation row를 만들기 전에 부르든 만든 뒤에
    부르든 같은 답이 나온다.
    """
    pacing = read_pacing(
        db,
        user_id=user_id,
        study_session_id=study_session_id,
        presentation_id=presentation_id,
    )
    if not pacing_allows_probe(pacing, config=config):
        return None
    return select_probe_target(
        db,
        user_id=user_id,
        study_session_id=study_session_id,
        target_item_ids=target_item_ids,
        now=now,
        config=config,
    )


def pacing_allows_probe(pacing: ProbePacing, *, config: AppConfig) -> bool:
    """`Probe Pacing`의 조건 1(상한)과 조건 2(간격).

    min(`mastery_probe_target_per_session_min`)은 **강제하지 않는다.** 관측 목표이지
    엔진 제약이 아니며, 채우려 들면 cooldown이나 간격을 깨야 한다.
    """
    if pacing.probes_shown >= config.learning.mastery_probe_target_per_session_max:
        return False
    gap = config.learning.probe_min_gap_presentations
    if pacing.presentations_after_last_probe is None:
        # "이번 presentation을 포함해 세션의 presentation 수 >= gap + 1"과 같다.
        # 세션의 첫 probe도 gap개 뒤로 미뤄져 첫 문장부터 probe가 나오지 않는다.
        return pacing.presentations_before_current >= gap
    return pacing.presentations_after_last_probe >= gap


def read_pacing(
    db: Session, *, user_id: int, study_session_id: int, presentation_id: int
) -> ProbePacing:
    """세션 event와 presentation만으로 pacing 상태를 재구성한다. 새 상태를 저장하지 않는다.

    presentation 순서는 `shown_at`이 아니라 **id**로 본다. 한 요청이 보는 시각은
    하나이므로(ADR-007) 같은 세션의 `shown_at`이 같을 수 있고, 그러면 "마지막 probe
    이후"가 흔들린다.
    """
    probes_shown = db.execute(
        sa.select(sa.func.count())
        .select_from(LearningEvent)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_session_id == study_session_id,
            LearningEvent.event_type == EventType.MASTERY_PROBE_SHOWN,
        )
    ).scalar_one()

    presentations_before = db.execute(
        sa.select(sa.func.count())
        .select_from(StudyPresentation)
        .where(
            StudyPresentation.study_session_id == study_session_id,
            StudyPresentation.id != presentation_id,
        )
    ).scalar_one()

    last_probe_presentation_id = db.execute(
        sa.select(sa.func.max(LearningEvent.study_presentation_id)).where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_session_id == study_session_id,
            LearningEvent.event_type == EventType.MASTERY_PROBE_SHOWN,
        )
    ).scalar_one()

    presentations_after_last_probe: int | None = None
    if last_probe_presentation_id is not None:
        presentations_after_last_probe = int(
            db.execute(
                sa.select(sa.func.count())
                .select_from(StudyPresentation)
                .where(
                    StudyPresentation.study_session_id == study_session_id,
                    StudyPresentation.id > last_probe_presentation_id,
                    StudyPresentation.id != presentation_id,
                )
            ).scalar_one()
        )

    return ProbePacing(
        probes_shown=int(probes_shown),
        presentations_before_current=int(presentations_before),
        presentations_after_last_probe=presentations_after_last_probe,
    )


def select_probe_target(
    db: Session,
    *,
    user_id: int,
    study_session_id: int,
    target_item_ids: Sequence[int],
    now: datetime,
    config: AppConfig,
) -> ProbeTarget | None:
    """`Probe 대상 우선순위`를 만족하고 제외에 걸리지 않는 item 중 하나.

    후보는 **이번 presentation의 target item**뿐이다. 화면에 없는 표현을 묻지
    않는다(`Probe Pacing` 조건 3).

    정렬은 `(priority, passive_rank, learning_item_id)`다.

    -   `passive_rank`는 ADR-011이 1번 순위 **안**에 둔 정렬 기준이다. 반복해서
        스쳐 지나갔는데 한 번도 말하지 않은 item이 확인 가치가 가장 크다.
    -   "오래 probe하지 않은"은 별도 정렬 키가 아니라 cooldown 제외가 이미 보장한다
        --- cooldown을 통과했다는 것이 곧 마지막 probe로부터
        `probe_skip_cooldown_days` 이상 지났거나 한 번도 묻지 않았다는 뜻이다.
    -   `learning_item_id ASC`는 결정론적 tie-break다.
    """
    item_ids = list(dict.fromkeys(target_item_ids))
    if not item_ids:
        return None

    recently_answered = _items_with_session_feedback(
        db, user_id=user_id, study_session_id=study_session_id, item_ids=item_ids
    )
    masteries = _masteries(db, user_id=user_id, item_ids=item_ids)
    states = _learning_states(db, user_id=user_id, item_ids=item_ids)
    cooldown = timedelta(days=config.learning.probe_skip_cooldown_days)

    ranked: list[tuple[tuple[int, int, int], ProbeTarget]] = []
    for item_id in item_ids:
        if item_id in recently_answered:
            continue
        state = states.get(item_id)
        if _in_cooldown(state, cooldown=cooldown, now=now):
            continue
        priority = _priority(masteries.get(item_id))
        if priority is None:
            continue
        sort_key = (priority.value, _passive_rank(state, config=config), item_id)
        ranked.append((sort_key, ProbeTarget(learning_item_id=item_id, priority=priority)))

    if not ranked:
        return None
    return min(ranked, key=lambda entry: entry[0])[1]


def _in_cooldown(
    state: UserItemLearningState | None, *, cooldown: timedelta, now: datetime
) -> bool:
    """마지막 probe로부터 `probe_skip_cooldown_days`가 지나지 않았으면 묻지 않는다.

    답했든 건너뛰었든 물어본 사실이 `last_probe_at`에 남는다. 경계는 포함이다 ---
    정확히 cooldown이 지난 순간은 다시 물을 수 있다.
    """
    if state is None or state.last_probe_at is None:
        return False
    return state.last_probe_at + cooldown > now


def _priority(mastery: UserMastery | None) -> ProbePriority | None:
    """위에서부터 처음 만족하는 우선순위. 아무것도 만족하지 않으면 묻지 않는다.

    `user_mastery` 행은 explicit evidence를 기록할 때만 생기므로, 행이 없거나
    `comprehension_mastery`가 NULL인 것이 곧 "아직 explicit evidence가 없다"다
    (ADR-011).
    """
    if mastery is None or mastery.comprehension_mastery is None:
        return ProbePriority.NO_EXPLICIT_EVIDENCE
    if _is_uncertain(mastery.comprehension_mastery):
        return ProbePriority.UNCERTAIN
    return None


def _passive_rank(state: UserItemLearningState | None, *, config: AppConfig) -> int:
    """같은 우선순위 안의 정렬 기준. 0이 먼저다 (ADR-011).

    반복해서 스쳐 지나갔는데 한 번도 말하지 않은 item이 확인 가치가 가장 크다.
    임계값은 `passive_exposures_before_probe`이며 경계는 포함이다.
    """
    if state is None:
        return 1
    if state.passive_no_signal_count >= config.learning.passive_exposures_before_probe:
        return 0
    return 1


def _is_uncertain(comprehension_mastery: float) -> bool:
    """`애매함`의 observation에 가장 가까운 값을 uncertain으로 본다.

    임계값을 새로 만들지 않는다. `02_LEARNING_POLICY.md`가 이미 세 explicit
    evidence의 observation 값을 고정해 두었으므로, mastery가 그 셋 중 어디에 가장
    가까운지로 판정하면 새 정책 숫자가 생기지 않는다. 같은 거리면 uncertain 쪽으로
    본다 --- 확신이 없을 때 묻는 것이 probe의 목적이다.
    """
    distance_to_uncertain = abs(comprehension_mastery - OBSERVATION[ExplicitSignal.UNCERTAIN])
    return all(
        distance_to_uncertain <= abs(comprehension_mastery - observation)
        for observation in OBSERVATION.values()
    )


def _items_with_session_feedback(
    db: Session, *, user_id: int, study_session_id: int, item_ids: Sequence[int]
) -> set[int]:
    rows = db.execute(
        sa.select(LearningEvent.learning_item_id)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_session_id == study_session_id,
            LearningEvent.event_type.in_(SESSION_FEEDBACK_EVENTS),
            LearningEvent.learning_item_id.in_(item_ids),
        )
        .distinct()
    ).scalars()
    return {row for row in rows if row is not None}


def _masteries(db: Session, *, user_id: int, item_ids: Sequence[int]) -> dict[int, UserMastery]:
    rows = db.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == user_id,
            UserMastery.learning_item_id.in_(item_ids),
        )
    ).scalars()
    return {row.learning_item_id: row for row in rows}


def _learning_states(
    db: Session, *, user_id: int, item_ids: Sequence[int]
) -> dict[int, UserItemLearningState]:
    rows = db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user_id,
            UserItemLearningState.learning_item_id.in_(item_ids),
        )
    ).scalars()
    return {row.learning_item_id: row for row in rows}
