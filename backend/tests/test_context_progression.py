"""contextual repetition이 실제로 진행하는가 (12_TEST_PLAN.md의 Integration).

Wave 2 검증에서 드러난 회귀를 그대로 재현하는 파일이다. 같은 item에 아직 노출되지
않은 validated 문장을 여러 개 두고 여러 라운드를 돌렸을 때 관측된 것은 이것이었다.

``` text
STAGES:    ['anchor'] * 8
SENTENCES: [4, 4, 4, 4, 4, 4, 4, 4]
```

최소 5회 meaningful exposure가 **전부 같은 anchor 문장**으로 채워진다는 뜻이고,
그러면 `01_PRODUCT_PRINCIPLES.md`와 `07_SRS_SPEC.md`가 요구하는 contextual
repetition이 성립하지 않는다. 원인은 `context_stage`를 올리거나 내리는 코드가 어디에도
없었던 것이다(ADR-012).

여기서 고정하는 것은 둘이다.

``` text
실패가 없으면      ladder가 오르고 제시 문장이 실제로 바뀐다
계속 `몰랐음`이면  anchor에 머문다 --- 전이의 부재가 아니라 증거에 따른 결과이고,
                   한 번이라도 다른 응답이 나오면 즉시 오른다
```

정책값을 리터럴로 적지 않는다. candidate도 손으로 만들지 않는다 --- Ready Pool은
언제나 materialization이 만든다(06_LEARNING_ENGINE.md의 `테스트에서의 candidate 구성`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.models import LearningItem, ReviewState, SentenceItem, User, UserItemLearningState
from app.models.enums import ContextStage, ExplicitSignal, PresentationRole, ReviewReason
from app.services import interactions, presentation, study_session
from tests import factories
from tests.clock import MutableClock
from tests.conftest import override_config

pytestmark = pytest.mark.integration

# 검증자가 돌린 라운드 수. 정책값이 아니라 "최소 노출을 넘기고도 남을 만큼"이다.
ROUNDS = 8
# 그만큼 돌리려면 stage가 요구하는 미노출 문맥이 있어야 한다.
SENTENCES = ROUNDS


@dataclass(frozen=True)
class _Shown:
    stage: ContextStage
    sentence_id: int
    role: PresentationRole
    reason: ReviewReason | None


def _cfg() -> AppConfig:
    return override_config(get_config())


def _sentence_item_id(db: Session, *, sentence_id: int, item: LearningItem) -> int:
    return db.execute(
        sa.select(SentenceItem.id).where(
            SentenceItem.sentence_id == sentence_id,
            SentenceItem.learning_item_id == item.id,
        )
    ).scalar_one()


def _learning_state(db: Session, *, user: User, item: LearningItem) -> UserItemLearningState:
    return db.execute(
        sa.select(UserItemLearningState).where(
            UserItemLearningState.user_id == user.id,
            UserItemLearningState.learning_item_id == item.id,
        )
    ).scalar_one()


def _review_state(db: Session, *, user: User, item: LearningItem) -> ReviewState | None:
    return db.execute(
        sa.select(ReviewState).where(
            ReviewState.user_id == user.id,
            ReviewState.learning_item_id == item.id,
        )
    ).scalar_one_or_none()


def _target_item(db: Session, user: User, *, lemma: str) -> LearningItem:
    """학습 target이지만 아직 한 번도 제시되지 않은 item + 문맥 여러 개.

    `user_item_learning_state`를 factory로 세우는 이유는 `new` role의 전제(승격됐고
    exposure가 0건)를 만드는 다른 경로가 Wave 2에 없기 때문이다. 문장은 전부
    Ready invariant를 만족한다.
    """
    item = factories.make_learning_item(db, lemma=lemma)
    for index in range(SENTENCES):
        factories.make_ready_sentence(db, [item], surfaces=[f"{lemma}{index}"])
    factories.make_learning_state(db, user, item, is_active_learning_target=True)
    return item


def _run_round(
    db: Session,
    user: User,
    item: LearningItem,
    *,
    clock: MutableClock,
    cfg: AppConfig,
    signal: ExplicitSignal | None,
) -> _Shown:
    """세션 하나에서 그 item을 한 번 제시하고 닫는다. 보인 stage와 문장을 돌려준다."""
    session = study_session.start_or_resume(db, user=user, now=clock.now(), cfg=cfg).session
    view = presentation.next_presentation(
        db, user=user, session_id=session.id, now=clock.now(), cfg=cfg
    )
    assert view is not None, "제시할 문장이 없다"
    if signal is not None:
        interactions.self_report(
            db,
            user_id=user.id,
            presentation_id=view.presentation_id,
            sentence_item_id=_sentence_item_id(db, sentence_id=view.sentence_id, item=item),
            signal=signal,
            client_event_id=uuid.uuid4(),
            now=clock.advance(timedelta(seconds=10)),
            cfg=cfg,
        )
    presentation.complete_presentation(
        db, user_id=user.id, presentation_id=view.presentation_id, now=clock.now(), cfg=cfg
    )
    study_session.finish(db, user_id=user.id, session_id=session.id, now=clock.now(), cfg=cfg)
    return _Shown(
        stage=view.context_stage,
        sentence_id=view.sentence_id,
        role=view.presentation_role,
        reason=view.review_reason,
    )


def _advance_to_due(db: Session, user: User, item: LearningItem, clock: MutableClock) -> None:
    """다음 라운드로 시계를 민다 (G8/G9).

    스케줄과 deferral 중 **늦은 쪽**까지다. 무신호 라운드는 `deferred_until`을
    걸어 같은 세션의 즉시 반복을 막으므로(07_SRS_SPEC.md), 그것을 넘기지 않으면
    다음 라운드에서 고를 것이 없다.
    """
    state = _review_state(db, user=user, item=item)
    moments = [clock.now() + timedelta(days=1)] if state is None else []
    if state is not None:
        moments.append(state.next_review_at.astimezone(UTC))
        if state.deferred_until is not None:
            moments.append(state.deferred_until.astimezone(UTC) + timedelta(seconds=1))
    target = max(moments)
    if target > clock.now():
        clock.set(target)
    else:
        clock.advance(timedelta(minutes=1))


def _drive(
    db: Session,
    user: User,
    item: LearningItem,
    *,
    clock: MutableClock,
    cfg: AppConfig,
    signal: ExplicitSignal | None,
    rounds: int = ROUNDS,
) -> list[_Shown]:
    shown: list[_Shown] = []
    for _ in range(rounds):
        shown.append(_run_round(db, user, item, clock=clock, cfg=cfg, signal=signal))
        _advance_to_due(db, user, item, clock)
    return shown


def _stage_rank(stage: ContextStage) -> int:
    return [
        ContextStage.ANCHOR,
        ContextStage.NEAR_ORIGINAL,
        ContextStage.VARIED,
        ContextStage.NEW_CONTEXT,
    ].index(stage)


def test_repeated_success_climbs_the_ladder_and_changes_the_sentence(
    db_session: Session,
) -> None:
    """실패 없이 반복하면 stage가 오르고 제시 문장이 anchor 하나에 고정되지 않는다.

    이것이 회귀의 정확한 반대다. `['anchor'] * 8`과 같은 문장 8회가 나오면 실패한다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = _target_item(db_session, user, lemma="任せる")

    shown = _drive(db_session, user, item, clock=clock, cfg=cfg, signal=ExplicitSignal.KNOWN)

    stages = [entry.stage for entry in shown]
    sentences = [entry.sentence_id for entry in shown]
    assert stages[0] is ContextStage.ANCHOR, "첫 제시는 anchor다"
    assert shown[0].role is PresentationRole.NEW, "첫 제시는 `new`다(ADR-013)"
    # 단조 증가. 실패가 없으므로 내려가는 구간이 있으면 안 된다.
    ranks = [_stage_rank(stage) for stage in stages]
    assert ranks == sorted(ranks)
    assert stages[-1] is ContextStage.NEW_CONTEXT, f"ladder를 오르지 못했다: {stages}"
    # 07_SRS_SPEC.md의 progression 표는 최소 노출 안에서 new_context에 닿는다.
    # 그보다 늦으면 최소 노출이 전부 낮은 stage로 채워진다.
    assert (
        ranks.index(_stage_rank(ContextStage.NEW_CONTEXT))
        < cfg.learning.minimum_meaningful_exposures
    ), f"최소 노출 안에 새 문맥에 닿지 못했다: {stages}"

    anchor_sentence_id = _learning_state(db_session, user=user, item=item).anchor_sentence_id
    # anchor / near_original은 anchor 문장 자신을 쓴다. `varied` 이상은 매번
    # 아직 보지 않은 문장이므로 서로 달라야 하고 anchor여서도 안 된다.
    beyond = [
        entry.sentence_id
        for entry in shown
        if _stage_rank(entry.stage) >= _stage_rank(ContextStage.VARIED)
    ]
    assert len(beyond) == len(set(beyond)) >= 2, f"새 문맥이 반복됐다: {sentences}"
    assert anchor_sentence_id not in beyond, f"새 문맥이 anchor로 채워졌다: {sentences}"


def test_repeated_unknown_stays_on_the_anchor_until_one_answer_differs(
    db_session: Session,
) -> None:
    """계속 `몰랐음`이면 anchor에 머문다. 그것은 증거에 따른 결과다(ADR-012의 `한계`).

    그리고 한 번이라도 `몰랐음`이 아닌 결과가 나오면 **즉시** ladder를 오른다.
    두 단정을 함께 두는 이유는, 앞의 것만 있으면 "전이 코드가 아예 없는" 구현도
    통과하기 때문이다.
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = _target_item(db_session, user, lemma="任せる")

    failed = _drive(db_session, user, item, clock=clock, cfg=cfg, signal=ExplicitSignal.UNKNOWN)

    assert [entry.stage for entry in failed] == [ContextStage.ANCHOR] * ROUNDS
    anchor_sentence_id = _learning_state(db_session, user=user, item=item).anchor_sentence_id
    assert [entry.sentence_id for entry in failed] == [anchor_sentence_id] * ROUNDS

    recovered = _run_round(
        db_session, user, item, clock=clock, cfg=cfg, signal=ExplicitSignal.UNCERTAIN
    )

    assert recovered.stage is ContextStage.ANCHOR
    assert _learning_state(db_session, user=user, item=item).context_stage is (
        ContextStage.NEAR_ORIGINAL
    )


def test_a_failure_after_climbing_reaches_context_repair(db_session: Session) -> None:
    """`context_repair`가 **상태를 손으로 만지지 않고** 도달한다.

    Wave 2 검증에서는 8라운드 연속 `몰랐음`에도 reason이 전부 `fsrs_due`였고
    `context_repair`는 0회였다. stage가 내려가지 않으니 조건 b
    (`context_stage < S_fail`)가 영원히 거짓이었기 때문이다(ADR-012).

    여기서는 성공으로 ladder를 올린 뒤 꼭대기에서 한 번 실패한다. 그 실패가 exposure
    확정과 같은 자리에서 stage를 한 칸 내리고, 다음 materialization이 우선순위 1인
    `context_repair` candidate를 만든다. 되돌린 문맥의 노출이 실제로 일어나면 조건
    1-c가 스스로 꺼져 더 만들지 않는다(06_LEARNING_ENGINE.md).
    """
    cfg = _cfg()
    clock = MutableClock()
    user = factories.make_user(db_session)
    item = _target_item(db_session, user, lemma="任せる")

    climbed = _drive(
        db_session, user, item, clock=clock, cfg=cfg, signal=ExplicitSignal.KNOWN, rounds=3
    )
    assert climbed[-1].stage is ContextStage.VARIED
    assert _learning_state(db_session, user=user, item=item).context_stage is (
        ContextStage.NEW_CONTEXT
    )

    failure = _run_round(
        db_session, user, item, clock=clock, cfg=cfg, signal=ExplicitSignal.UNKNOWN
    )
    assert failure.stage is ContextStage.NEW_CONTEXT
    # 실패는 **실제로 본 문맥**을 기준으로 한 칸 내려간다.
    assert _learning_state(db_session, user=user, item=item).context_stage is ContextStage.VARIED

    _advance_to_due(db_session, user, item, clock)
    repair = _run_round(db_session, user, item, clock=clock, cfg=cfg, signal=None)

    assert repair.role is PresentationRole.REVIEW
    assert repair.reason is ReviewReason.CONTEXT_REPAIR
    assert repair.stage is ContextStage.VARIED
    assert repair.sentence_id != failure.sentence_id

    _advance_to_due(db_session, user, item, clock)
    following = _run_round(db_session, user, item, clock=clock, cfg=cfg, signal=None)

    assert following.reason is not ReviewReason.CONTEXT_REPAIR
