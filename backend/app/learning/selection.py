"""다음 presentation 선택과 Ready Pool 생성 (06_LEARNING_ENGINE.md).

이 모듈이 하는 일은 셋이다.

``` text
Candidate Materialization   global content를 이 사용자에게 투영해 Ready Pool을 만든다
Category Mix / Review Reason / Review Ordering   무엇을 다음에 보여줄지 고른다
Pool Fallback               고를 것이 없을 때의 순서
```

**provider를 부르지 않는다**(불변식 #1). materialization은 LLM 호출이 아니라
이미 `validated`인 문장을 사용자·역할·stage에 매핑하는 결정론적 DB 연산이므로
request 경로에서 해도 된다(ADR-010).

**`next_review_at`에 쓰지 않는다**(불변식 #4). 최소 5회 노출은 FSRS interval을
cap해서가 아니라 `reinforcement` reason을 골라서 채운다. FSRS 컬럼은 읽기만 한다.

트랜잭션은 소유하지 않는다(G7). 시각은 인자로 받는다(G8/G9).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import LearningConfig
from app.learning.exploration import (
    ExplorationSortKey,
    eligible_exploration_targets,
    exploration_sort_key,
)
from app.learning.progression import UNKNOWN_SIGNAL_EVENTS, stage_rank
from app.models.content import LearningItem, Sentence, SentenceItem, SentenceItemExplanation
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    ExplanationStatus,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.models.learning import (
    ReviewState,
    UserItemLearningState,
    UserMastery,
    UserSentenceCandidate,
    UserSentenceCandidateTarget,
)
from app.models.study import ItemExposure, LearningEvent, StudyPresentation
from app.models.user import User

# Category Mix 동률 tie-break (06_LEARNING_ENGINE.md). 값이 아니라 **순서**가
# 명세이므로 config로 빼지 않는다.
TIE_ORDER: Mapping[PresentationRole, int] = {
    PresentationRole.REVIEW: 0,
    PresentationRole.NEW: 1,
    PresentationRole.EXPLORATION: 2,
}

# ladder 순서와 `몰랐음` event 목록의 canonical 선언은 `learning/progression.py`다.
# 전이를 수행하는 쪽과 그 결과를 읽는 쪽(`context_repair` 판정)이 같은 값을 봐야 한다.

# deficit 비교 전 반올림 자릿수. 0.7*12-8 과 0.2*12-2 는 수학적으로 같은 0.4인데
# IEEE 754에서는 1e-16만큼 다르다. 반올림하지 않으면 명세가 정한 tie-break
# (review -> new -> exploration)가 실행되는 일이 사실상 없고, 순서가 부동소수점
# 오차로 정해진다.
_DEFICIT_DECIMALS = 9

# 소비되지 않은 candidate에만 걸린 partial unique index. materialization 재실행이
# 같은 candidate를 중복 생성하지 않게 하는 것은 이 index다(04_DB_SPEC.md, ADR-010).
_ACTIVE_CANDIDATE_KEY = ["user_id", "sentence_id", "presentation_role", "context_stage"]
_ACTIVE_CANDIDATE_PREDICATE = sa.text("status IN ('queued', 'ready')")

_MASTERY_IS_NULL = (0, 0.0)

# (next_review_at, mastery, learning_item_id)
ReviewOrderKey = tuple[datetime, tuple[int, float], int]


# --------------------------------------------------------------------------
# 값 타입
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionCounters:
    """이 세션에서 **이미 제시된** presentation 수. 이번에 제시할 것은 포함하지 않는다.

    `study_presentations`를 GROUP BY로 읽어서 만든다. in-memory 카운터를 쓰지 않는
    이유는 세션 resume과 서버 재시작에도 비율이 유지되어야 하기 때문이다.
    """

    by_role: Mapping[PresentationRole, int]
    by_review_reason: Mapping[ReviewReason, int]

    @classmethod
    def from_counts(
        cls,
        role_counts: Mapping[PresentationRole, int],
        reason_counts: Mapping[ReviewReason, int],
    ) -> SessionCounters:
        """빠진 키를 0으로 채운다. 조회부가 KeyError를 신경 쓰지 않게 한다."""
        return cls(
            by_role={role: role_counts.get(role, 0) for role in PresentationRole},
            by_review_reason={reason: reason_counts.get(reason, 0) for reason in ReviewReason},
        )

    @property
    def total(self) -> int:
        return sum(self.by_role.values())


@dataclass(frozen=True)
class Selection:
    """다음에 제시할 candidate. presentation row를 만드는 것은 `services/`다."""

    candidate_id: int
    sentence_id: int
    presentation_role: PresentationRole
    review_reason: ReviewReason | None
    context_stage: ContextStage
    target_item_ids: tuple[int, ...]


@dataclass(frozen=True)
class _ReviewTarget:
    """review candidate의 target 하나. FSRS 컬럼은 여기서 **읽기만** 한다."""

    learning_item_id: int
    next_review_at: datetime
    deferred_until: datetime | None
    mastery: float | None

    def eligible(self, now: datetime) -> bool:
        """Review Ordering 1단계. 무신호 review가 같은 세션에서 다시 뽑히지 않게 한다."""
        return self.deferred_until is None or self.deferred_until <= now

    def due(self, now: datetime) -> bool:
        return self.eligible(now) and self.next_review_at <= now

    @property
    def order_key(self) -> ReviewOrderKey:
        """next_review_at ASC -> mastery ASC(NULL이 가장 낮다) -> learning_item_id ASC."""
        mastery = _MASTERY_IS_NULL if self.mastery is None else (1, self.mastery)
        return (self.next_review_at, mastery, self.learning_item_id)


@dataclass(frozen=True)
class _StageSentence:
    """stage 규칙이 고른 문장과, `anchor_sentence_id`에 기록해야 할 값.

    `anchor_to_record`가 None이면 기록할 것이 없다. 기록 자체는 상태 쓰기를 소유한
    `_review_plans`가 한다 --- 문장을 고르는 쪽이 직접 쓰면 쓰기 지점이 둘이 되고,
    최초 지정과 quarantine 재지정이 서로 다른 자리에서 일어난다.
    """

    sentence_id: int
    anchor_to_record: int | None


@dataclass(frozen=True)
class _Plan:
    """materialization이 만들려는 candidate 하나. 아직 DB에 없다."""

    learning_item_id: int
    sentence_id: int
    context_stage: ContextStage
    review_reason: ReviewReason | None


# --------------------------------------------------------------------------
# Category Mix (순수 함수)
# --------------------------------------------------------------------------


def choose_ratios(backlog: int, cfg: LearningConfig) -> Mapping[PresentationRole, float]:
    """backlog가 threshold 이상이면 세 ratio를 `backlog_*` **세트로 통째 교체**한다.

    개별 키를 섞지 않는다. 섞으면 합이 1.0이라는 config 검증이 의미를 잃는다.
    """
    if backlog >= cfg.backlog_threshold:
        return {
            PresentationRole.REVIEW: cfg.backlog_review_ratio,
            PresentationRole.NEW: cfg.backlog_new_ratio,
            PresentationRole.EXPLORATION: cfg.backlog_exploration_ratio,
        }
    return {
        PresentationRole.REVIEW: cfg.review_ratio,
        PresentationRole.NEW: cfg.new_ratio,
        PresentationRole.EXPLORATION: cfg.exploration_ratio,
    }


def rank_categories(
    ratios: Mapping[PresentationRole, float], counters: SessionCounters
) -> list[PresentationRole]:
    """deficit이 큰 category부터의 순서. pool 유무는 여기서 보지 않는다.

    정확한 정수 quota를 세션 시작 시 고정하지 않는다. `total_presented`에 이번에
    제시할 1을 포함하므로 세션 첫 문장에서도 deficit이 모두 0이 되지 않는다.

    pool이 없는 category를 **건너뛰는 일은 호출부**가 한다. 이 함수는 DB를 모르는
    순수 함수여야 하고, "pool이 있다"는 candidate를 실제로 골라봐야 알 수 있다
    (exploration은 target 재확인에서 전부 탈락할 수 있다).
    """
    total_presented = counters.total + 1

    def deficit(role: PresentationRole) -> float:
        target = ratios.get(role, 0.0) * total_presented
        return round(target - counters.by_role[role], _DEFICIT_DECIMALS)

    return sorted(ratios, key=lambda role: (-deficit(role), TIE_ORDER[role]))


def choose_review_reason(
    available: Iterable[ReviewReason], counters: SessionCounters, share: float
) -> ReviewReason | None:
    """06_LEARNING_ENGINE.md의 5단 절차를 그대로 옮긴 것이다.

    `share = 0.0`이면 2단계가 항상 거짓이 되어 최소 지분 규칙이 꺼지고 순수
    우선순위(context_repair -> fsrs_due -> reinforcement)만 남는다.

    최소 지분이 `fsrs_due`보다만 앞서고 `context_repair`를 넘지 않는 이유는,
    context_repair가 직전 실패로만 생겨 수가 제한적이고 미루면 틀린 이해가 굳기
    때문이다.
    """
    usable = set(available)
    if ReviewReason.CONTEXT_REPAIR in usable:
        return ReviewReason.CONTEXT_REPAIR

    # 분모는 reason과 무관한 모든 review presentation이고, 이번에 제시할 1을 포함한다.
    review_total = counters.by_role[PresentationRole.REVIEW] + 1
    reinforcement_deficit = (
        share * review_total - counters.by_review_reason[ReviewReason.REINFORCEMENT]
    )
    if reinforcement_deficit > 0 and ReviewReason.REINFORCEMENT in usable:
        return ReviewReason.REINFORCEMENT
    if ReviewReason.FSRS_DUE in usable:
        return ReviewReason.FSRS_DUE
    if ReviewReason.REINFORCEMENT in usable:
        return ReviewReason.REINFORCEMENT
    return None


# --------------------------------------------------------------------------
# 세션 상태 조회
# --------------------------------------------------------------------------


def load_counters(db: Session, *, study_session_id: int) -> SessionCounters:
    """presentation 집계를 DB에서 읽는다. 세션 resume과 재시작에도 비율이 유지된다."""
    rows = db.execute(
        sa.select(
            StudyPresentation.presentation_role,
            StudyPresentation.review_reason,
            sa.func.count(StudyPresentation.id),
        )
        .where(StudyPresentation.study_session_id == study_session_id)
        .group_by(StudyPresentation.presentation_role, StudyPresentation.review_reason)
    ).all()

    role_counts: dict[PresentationRole, int] = {}
    reason_counts: dict[ReviewReason, int] = {}
    for role, reason, count in rows:
        role_counts[role] = role_counts.get(role, 0) + int(count)
        if reason is not None:
            reason_counts[reason] = reason_counts.get(reason, 0) + int(count)
    return SessionCounters.from_counts(role_counts, reason_counts)


def count_backlog(db: Session, *, user_id: int, now: datetime) -> int:
    """eligible due item 수. deferral 중인 item은 밀린 빚이 아니므로 세지 않는다."""
    count = db.execute(
        sa.select(sa.func.count(ReviewState.id)).where(
            ReviewState.user_id == user_id,
            ReviewState.next_review_at <= now,
            sa.or_(ReviewState.deferred_until.is_(None), ReviewState.deferred_until <= now),
        )
    ).scalar_one()
    return int(count)


def _load_review_targets(
    db: Session, *, user_id: int, item_ids: Iterable[int] | None = None
) -> dict[int, _ReviewTarget]:
    """review ordering에 필요한 값만 모은다. FSRS 컬럼은 읽기만 한다(G5)."""
    statement = (
        sa.select(
            ReviewState.learning_item_id,
            ReviewState.next_review_at,
            ReviewState.deferred_until,
            UserMastery.comprehension_mastery,
        )
        .outerjoin(
            UserMastery,
            sa.and_(
                UserMastery.user_id == ReviewState.user_id,
                UserMastery.learning_item_id == ReviewState.learning_item_id,
            ),
        )
        .where(ReviewState.user_id == user_id)
    )
    if item_ids is not None:
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return {}
        statement = statement.where(ReviewState.learning_item_id.in_(ids))

    return {
        item_id: _ReviewTarget(
            learning_item_id=item_id,
            next_review_at=next_review_at,
            deferred_until=deferred_until,
            mastery=mastery,
        )
        for item_id, next_review_at, deferred_until, mastery in db.execute(statement).all()
    }


def _valid_exposure_count(db: Session, *, user_id: int, learning_item_id: int) -> int:
    """무효화되지 않은 exposure 수. canonical source는 `item_exposures`다(07_SRS_SPEC.md)."""
    count = db.execute(
        sa.select(sa.func.count(ItemExposure.id)).where(
            ItemExposure.user_id == user_id,
            ItemExposure.learning_item_id == learning_item_id,
            ItemExposure.invalidated_at.is_(None),
        )
    ).scalar_one()
    return int(count)


# --------------------------------------------------------------------------
# Candidate Materialization (06_LEARNING_ENGINE.md, ADR-010)
# --------------------------------------------------------------------------


def materialize_candidates(db: Session, *, user: User, now: datetime, cfg: LearningConfig) -> int:
    """요청한 사용자 **한 명분**의 Ready Pool을 채우고 만든 candidate 수를 돌려준다.

    role별로 최대 `candidate_materialization_batch_size`개다. 상한이 없으면 첫
    세션 한 번에 seed 전체가 candidate로 복제된다.

    `status`는 곧바로 `ready`다. 대상이 이미 검증된 콘텐츠뿐이기 때문이다.
    `queued`는 **아직 콘텐츠가 없어 worker가 생성 중인** candidate의 값이며 Wave 3이
    쓴다.
    """
    created = 0
    for role, plans in (
        (PresentationRole.REVIEW, _review_plans(db, user_id=user.id, now=now, cfg=cfg)),
        (PresentationRole.NEW, _new_plans(db, user_id=user.id, now=now)),
        (PresentationRole.EXPLORATION, _exploration_plans(db, user=user, now=now, cfg=cfg)),
    ):
        created += _create_candidates(
            db,
            user_id=user.id,
            role=role,
            plans=plans,
            now=now,
            batch_size=cfg.candidate_materialization_batch_size,
            max_targets=cfg.max_new_items_per_sentence,
        )
    db.flush()
    return created


def _create_candidates(
    db: Session,
    *,
    user_id: int,
    role: PresentationRole,
    plans: Iterator[_Plan],
    now: datetime,
    batch_size: int,
    max_targets: int,
) -> int:
    """plan을 candidate row로 만든다. 같은 문장에 모이는 item은 같은 candidate의 target이 된다.

    `plans`는 generator다. batch 상한에 닿으면 더 끌어오지 않으므로, plan을 만드는
    쪽의 per-item 조회가 상한만큼만 일어난다.
    """
    created: dict[tuple[int, ContextStage], int] = {}
    target_counts: dict[int, int] = {}

    for plan in plans:
        key = (plan.sentence_id, plan.context_stage)
        candidate_id = created.get(key)
        if candidate_id is None:
            if len(created) >= batch_size:
                break
            candidate_id = _insert_candidate(db, user_id=user_id, role=role, plan=plan, now=now)
            if candidate_id is None:
                # 아직 소비되지 않은 같은 candidate가 이미 있다. 재실행은 idempotent다.
                continue
            created[key] = candidate_id
            target_counts[candidate_id] = 0
        if target_counts[candidate_id] >= max_targets:
            # 문장당 target item 수 상한(max_new_items_per_sentence). 넘는 item은
            # 이번 문장에 싣지 않는다.
            continue
        _insert_target(
            db, candidate_id=candidate_id, user_id=user_id, item_id=plan.learning_item_id
        )
        target_counts[candidate_id] += 1

    return len(created)


def _insert_candidate(
    db: Session, *, user_id: int, role: PresentationRole, plan: _Plan, now: datetime
) -> int | None:
    """중복이면 None. 조회 후 삽입이 아니라 partial unique index에 기댄다.

    조회 후 삽입은 같은 사용자의 동시 요청(세션 생성과 /next)에서 경합하고, 그때
    터지는 IntegrityError는 호출부의 트랜잭션 전체를 무효로 만든다.
    """
    statement = (
        pg_insert(UserSentenceCandidate)
        .values(
            user_id=user_id,
            sentence_id=plan.sentence_id,
            presentation_role=role,
            review_reason=plan.review_reason,
            context_stage=plan.context_stage,
            status=CandidateStatus.READY,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=_ACTIVE_CANDIDATE_KEY,
            index_where=_ACTIVE_CANDIDATE_PREDICATE,
        )
        .returning(UserSentenceCandidate.id)
    )
    return db.execute(statement).scalar_one_or_none()


def _insert_target(db: Session, *, candidate_id: int, user_id: int, item_id: int) -> None:
    db.add(
        UserSentenceCandidateTarget(
            candidate_id=candidate_id,
            learning_item_id=item_id,
            # "그 사용자에게 review_states 행이 없으면 is_new_item = true" (06).
            is_new_item=not _has_review_state(db, user_id=user_id, item_id=item_id),
        )
    )


def _has_review_state(db: Session, *, user_id: int, item_id: int) -> bool:
    return (
        db.execute(
            sa.select(ReviewState.id).where(
                ReviewState.user_id == user_id,
                ReviewState.learning_item_id == item_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def _ready_sentences(
    db: Session, *, learning_item_id: int, unseen_by_user_id: int | None
) -> list[tuple[int, int | None]]:
    """Ready invariant를 만족하는 문장 `(id, parent_sentence_id)`, id ASC.

    `sentences.status = validated` 이고, `is_tappable = true`인 모든 `sentence_items`가
    `status = validated`인 explanation을 가져야 한다. 하나라도 없으면 그 문장으로
    candidate를 만들지 않는다 --- 탭했을 때 보여줄 것이 없는 문장을 ready로 두면
    핵심 UI가 빈 화면이 된다.

    `unseen_by_user_id`가 주어지면 그 사용자에게 아직 **제시된 적 없는** 문장만
    남긴다. 판정 소스는 `study_presentations`다. `item_exposures`는 target item에
    대한 기록이라 target이 아닌 item을 품은 문장을 이미 보여준 사실을 놓친다.
    """
    unexplained = (
        sa.select(SentenceItem.sentence_id)
        .outerjoin(
            SentenceItemExplanation,
            sa.and_(
                SentenceItemExplanation.sentence_item_id == SentenceItem.id,
                SentenceItemExplanation.status == ExplanationStatus.VALIDATED,
            ),
        )
        .where(SentenceItem.is_tappable.is_(True), SentenceItemExplanation.id.is_(None))
    )
    statement = (
        sa.select(Sentence.id, Sentence.parent_sentence_id)
        .join(SentenceItem, SentenceItem.sentence_id == Sentence.id)
        .where(
            SentenceItem.learning_item_id == learning_item_id,
            Sentence.status == SentenceStatus.VALIDATED,
            Sentence.id.not_in(unexplained),
        )
        .distinct()
        .order_by(Sentence.id)
    )
    if unseen_by_user_id is not None:
        statement = statement.where(
            Sentence.id.not_in(
                sa.select(StudyPresentation.sentence_id).where(
                    StudyPresentation.user_id == unseen_by_user_id
                )
            )
        )
    return [(sentence_id, parent_id) for sentence_id, parent_id in db.execute(statement).all()]


def _first_unseen_sentence(db: Session, *, user_id: int, item_id: int) -> int | None:
    """exploration과 new의 문장 규칙: 아직 노출되지 않은 validated 문장, id ASC."""
    rows = _ready_sentences(db, learning_item_id=item_id, unseen_by_user_id=user_id)
    return rows[0][0] if rows else None


def _exploration_plans(
    db: Session, *, user: User, now: datetime, cfg: LearningConfig
) -> Iterator[_Plan]:
    """exploration target은 `Exploration Item 선정`의 후보 조건·정렬을 그대로 따른다.

    `new`와 배타적이다(조건 2가 `is_active_learning_target = false`를 요구한다).
    겹치면 같은 item이 두 category에서 동시에 뽑혀 Category Mix가 무의미해진다.
    """
    items = list(db.execute(sa.select(LearningItem)).scalars().all())
    eligible = eligible_exploration_targets(
        db,
        user_id=user.id,
        item_ids=[item.id for item in items],
        now=now,
        recent_days=cfg.exploration_recent_days,
    )
    ordered = sorted(
        (item for item in items if item.id in eligible),
        key=lambda item: exploration_sort_key(item, starting_level=user.starting_level),
    )
    for item in ordered:
        sentence_id = _first_unseen_sentence(db, user_id=user.id, item_id=item.id)
        if sentence_id is not None:
            yield _Plan(item.id, sentence_id, ContextStage.ANCHOR, None)


def _new_plans(db: Session, *, user_id: int, now: datetime) -> Iterator[_Plan]:
    """`new` = 학습 target인데 **아직 한 번도 target으로 제시되지 않은** item (ADR-013).

    "아직 `review_states` 행이 없는 item"이라는 옛 정의는 철회됐다. `몰랐음 -> Again`이
    승격시킨 바로 그 self-report에서 스케줄을 만들므로 그 집합은 항상 공집합이었고,
    Category Mix의 new 축이 영구히 굶었다. 판정 소스는 이 엔진의 다른 모든 노출
    판정과 같은 `item_exposures`의 `invalidated_at IS NULL` 건수다.

    문장은 `stage -> sentence` 표의 `anchor` 행과 같다. 승격 시점에 기록된
    `anchor_sentence_id`가 있으면 **사용자가 실제로 만난 그 문장**을 다시 제시한다
    (`_first_unseen_sentence`를 쓰면 그 문맥이 낯선 문장으로 바뀐다).
    """
    states = (
        db.execute(
            sa.select(UserItemLearningState)
            .where(
                UserItemLearningState.user_id == user_id,
                UserItemLearningState.is_active_learning_target.is_(True),
            )
            .order_by(UserItemLearningState.learning_item_id)
        )
        .scalars()
        .all()
    )
    for state in states:
        item_id = state.learning_item_id
        if _valid_exposure_count(db, user_id=user_id, learning_item_id=item_id) > 0:
            # 이미 제시된 적이 있다. 그 item은 `review`의 몫이다.
            continue
        picked = _stage_sentence(
            db,
            user_id=user_id,
            item_id=item_id,
            stage=ContextStage.ANCHOR,
            anchor_id=state.anchor_sentence_id,
        )
        if picked is None:
            continue
        if picked.anchor_to_record is not None:
            state.anchor_sentence_id = picked.anchor_to_record
            state.updated_at = now
        yield _Plan(item_id, picked.sentence_id, ContextStage.ANCHOR, None)


def _review_plans(
    db: Session, *, user_id: int, now: datetime, cfg: LearningConfig
) -> Iterator[_Plan]:
    """review candidate도 Wave 2가 만든다. 한 item에 reason은 **하나**다.

    유일성 규칙이 `(user_id, sentence_id, presentation_role, context_stage)`이므로,
    같은 item·같은 stage에 두 reason의 candidate를 만들면 대개 같은 문장을 골라
    두 번째가 충돌한다. 어느 reason을 실제로 보여줄지는 `choose_review_reason`이
    정하고, 여기서는 그 선택이 작동할 재료만 만든다.
    """
    targets = _load_review_targets(db, user_id=user_id)
    states = {
        state.learning_item_id: state
        for state in db.execute(
            sa.select(UserItemLearningState).where(UserItemLearningState.user_id == user_id)
        )
        .scalars()
        .all()
    }

    for target in sorted(targets.values(), key=lambda item: item.order_key):
        exposures = _valid_exposure_count(
            db, user_id=user_id, learning_item_id=target.learning_item_id
        )
        if exposures == 0:
            # 아직 한 번도 target으로 제시되지 않았다. 그 item의 첫 제시는 `new`의
            # 몫이고 두 pool은 배타적이다(ADR-013).
            continue
        state = states.get(target.learning_item_id)
        stage = ContextStage.ANCHOR if state is None else state.context_stage
        reason = _review_reason_for(
            db, user_id=user_id, target=target, stage=stage, exposures=exposures, now=now, cfg=cfg
        )
        if reason is None:
            continue
        anchor_id = None if state is None else state.anchor_sentence_id
        picked = _stage_sentence(
            db,
            user_id=user_id,
            item_id=target.learning_item_id,
            stage=stage,
            anchor_id=anchor_id,
        )
        if picked is None:
            # 조건에 맞는 문장이 없다. 그 stage의 candidate를 만들지 않고 Pool
            # Fallback으로 넘긴다. 문맥을 **생성**하는 것은 Wave 3의 일이다.
            continue
        # materialization 쪽의 `anchor_sentence_id` 쓰기 지점이다(`_new_plans`와
        # 같은 규칙). 승격 시점의 기록은 `learning/progression.py`가 하고 둘 다
        # **NULL일 때만** 쓴다. quarantine 재지정은 여기 한 자리가 소유한다.
        if state is not None and picked.anchor_to_record is not None:
            state.anchor_sentence_id = picked.anchor_to_record
            state.updated_at = now
        yield _Plan(target.learning_item_id, picked.sentence_id, stage, reason)


def _review_reason_for(
    db: Session,
    *,
    user_id: int,
    target: _ReviewTarget,
    stage: ContextStage,
    exposures: int,
    now: datetime,
    cfg: LearningConfig,
) -> ReviewReason | None:
    """06_LEARNING_ENGINE.md의 `review candidate: reason 판정`을 위에서부터 평가한다.

    `exposures`는 호출부가 이미 센 유효 노출 건수다. 같은 값을 여기서 다시 세면
    "review pool에 들어가는가"(>= 1건)와 "reinforcement가 필요한가"가 서로 다른
    질의 결과를 볼 수 있다.
    """
    if _needs_context_repair(db, user_id=user_id, item_id=target.learning_item_id, stage=stage):
        return ReviewReason.CONTEXT_REPAIR
    if target.due(now):
        return ReviewReason.FSRS_DUE
    if exposures < cfg.minimum_meaningful_exposures:
        # 불변식 #4: FSRS interval을 cap하지 않는다. 최소 노출은 이 reason으로 채운다.
        return ReviewReason.REINFORCEMENT
    return None


def _needs_context_repair(db: Session, *, user_id: int, item_id: int, stage: ContextStage) -> bool:
    """새 상태 컬럼 없이 세 조건으로 판정한다 (06_LEARNING_ENGINE.md).

    조건 a의 S_fail은 `study_presentations`가 아니라 **그 (presentation, item)의
    유효한 `item_exposures` row**에서 읽는다. 둘은 같지 않다.

    ``` text
    target이 아닌 item의 `몰랐음`   presentation의 stage는 다른 item을 위해 고른 값이다
    flag/quarantine된 노출          invalidated_at이 붙어 실패로 보지 않는다
    ```

    되돌린 문맥의 노출이 실제로 일어나면 조건 c가 자동으로 거짓이 되므로
    "repair를 아직 했는가"를 따로 저장할 필요가 없다. 조건 b가 성립하려면 stage가
    실제로 내려가야 하고, 그 하강은 `learning/progression.py`가 수행한다.
    """
    failure = db.execute(
        sa.select(ItemExposure.context_stage, LearningEvent.created_at)
        .join(
            ItemExposure,
            sa.and_(
                ItemExposure.study_presentation_id == LearningEvent.study_presentation_id,
                ItemExposure.learning_item_id == LearningEvent.learning_item_id,
                ItemExposure.invalidated_at.is_(None),
            ),
        )
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.learning_item_id == item_id,
            LearningEvent.event_type.in_(UNKNOWN_SIGNAL_EVENTS),
        )
        .order_by(LearningEvent.created_at.desc(), LearningEvent.id.desc())
        .limit(1)
    ).first()
    if failure is None:
        return False

    failed_stage, failed_at = failure
    # b. 실패 후 한 단계 내려가 있어야 한다.
    if stage_rank(stage) >= stage_rank(failed_stage):
        return False

    # c. 되돌린 stage의 유효 노출이 그 실패 이후로 아직 없다.
    repaired = db.execute(
        sa.select(sa.func.count(ItemExposure.id)).where(
            ItemExposure.user_id == user_id,
            ItemExposure.learning_item_id == item_id,
            ItemExposure.context_stage == stage,
            ItemExposure.invalidated_at.is_(None),
            ItemExposure.created_at > failed_at,
        )
    ).scalar_one()
    return int(repaired) == 0


def _is_quarantined(db: Session, *, sentence_id: int) -> bool:
    """`_ready_sentences`만으로는 quarantine과 일시적 invariant 미충족을 구분할 수 없다.

    앞엣것은 anchor 재지정 사유이고 뒤엣것은 아니므로 `sentences.status`를 직접 본다.
    """
    status = db.execute(
        sa.select(Sentence.status).where(Sentence.id == sentence_id)
    ).scalar_one_or_none()
    return status == SentenceStatus.QUARANTINED


def _stage_sentence(
    db: Session, *, user_id: int, item_id: int, stage: ContextStage, anchor_id: int | None
) -> _StageSentence | None:
    """`stage -> sentence` 표 (06_LEARNING_ENGINE.md).

    `varied`와 `new_context`의 규칙이 같은 것은 MVP에 문장 단위의 "anchor로부터의
    거리" 지표가 없기 때문이다. 두 stage의 구분은 문장이 아니라
    `user_item_learning_state.context_stage`의 progression이 담당한다.

    `anchor` / `near_original`은 anchor 문장이 실제로 필요하므로 쓸 수 없게 된
    anchor를 여기서 해소한다(`anchor 문장을 더는 쓸 수 없을 때`). `varied` /
    `new_context`에서 anchor는 **제외 조건**일 뿐이라 쓸 수 없어도 stage가 막히지
    않으므로 건드리지 않는다.
    """
    if stage in (ContextStage.ANCHOR, ContextStage.NEAR_ORIGINAL):
        ready = _ready_sentences(db, learning_item_id=item_id, unseen_by_user_id=None)
        resolved = _resolve_anchor(db, ready=ready, anchor_id=anchor_id)
        if resolved is None:
            return None
        anchor_id, anchor_to_record = resolved
        if stage is ContextStage.ANCHOR:
            return _StageSentence(anchor_id, anchor_to_record)
        for sentence_id, parent_id in ready:
            if sentence_id == anchor_id or parent_id == anchor_id:
                return _StageSentence(sentence_id, anchor_to_record)
        return None

    ready = _ready_sentences(db, learning_item_id=item_id, unseen_by_user_id=user_id)
    for sentence_id, _parent_id in ready:
        if sentence_id != anchor_id:
            return _StageSentence(sentence_id, None)
    return None


def _resolve_anchor(
    db: Session, *, ready: list[tuple[int, int | None]], anchor_id: int | None
) -> tuple[int, int | None] | None:
    """쓸 수 있는 anchor와, `anchor_sentence_id`에 기록해야 할 값을 돌려준다.

    ``` text
    sentences.status = quarantined   anchor_sentence_id를 NULL로 되돌리고 재지정
    그 밖의 invariant 미충족          재지정하지 않고 그 stage를 건너뛴다
    ```

    quarantine일 때 재지정하는 것이 "몰래 바꾸는" 것이 아닌 이유는, quarantine
    시점에 그 문장에서 나온 `item_exposures`가 이미 `invalidated_at`으로
    무효화되기 때문이다(10_ERROR_HANDLING.md). 최초 학습 문맥으로서의 기록 자체가
    남아 있지 않다. 반대로 explanation repair 대기처럼 **일시적**인 경우까지
    재지정하면 곧 복구될 문장 때문에 같은 item의 학습 문맥이 흔들린다.

    둘을 같게 다루면 quarantine된 anchor를 가진 item이 candidate를 영영 얻지
    못하고, stage progression은 노출을 요구하므로 자력으로 빠져나올 수 없다.
    """
    if anchor_id is not None:
        if any(sentence_id == anchor_id for sentence_id, _parent_id in ready):
            return (anchor_id, None)
        if not _is_quarantined(db, sentence_id=anchor_id):
            return None
    if not ready:
        return None
    designated = ready[0][0]
    return (designated, designated)


# --------------------------------------------------------------------------
# 선택
# --------------------------------------------------------------------------


def select_next(
    db: Session,
    *,
    user: User,
    study_session_id: int,
    now: datetime,
    cfg: LearningConfig,
) -> Selection | None:
    """다음 presentation으로 쓸 candidate를 고른다. 고를 것이 없으면 None이다.

    **None은 Pool Fallback 3단계(background replenishment job enqueue)를 뜻한다.**
    enqueue 자체를 여기서 하지 않는 이유는 계층이다(ADR-007): `app/jobs/`는 L2이고
    `app/learning/`은 L1이라 job을 import할 수 없다. 호출하는 `services/`가 같은
    트랜잭션 안에서 job row를 INSERT한다. **provider를 부르지 않는다** --- 모든
    pool이 비어도 세션을 LLM 응답 대기로 block하지 않는다(불변식 #1).

    `review_states`에 아무것도 쓰지 않는다. due item을 골라놓고 보여주지 못해도
    lapse도 실패도 아니고 그대로 due로 남는다.
    """
    counters = load_counters(db, study_session_id=study_session_id)
    ratios = choose_ratios(count_backlog(db, user_id=user.id, now=now), cfg)
    ranked = rank_categories(ratios, counters)

    selection = _select_for_role(db, user=user, role=ranked[0], counters=counters, now=now, cfg=cfg)
    if selection is not None:
        return selection

    # 0. Candidate Materialization 1회 (LLM 호출 없음). "Ready candidate가 없다"는
    #    대부분 콘텐츠가 없다가 아니라 아직 이 사용자에게 투영되지 않았다는 뜻이다.
    materialize_candidates(db, user=user, now=now, cfg=cfg)

    # 1. 같은 deficit 순서로 available category를 훑는다(첫 category 재시도 포함).
    for role in ranked:
        selection = _select_for_role(db, user=user, role=role, counters=counters, now=now, cfg=cfg)
        if selection is not None:
            return selection

    # 2. 안전한 기존 anchor reinforcement 재사용.
    return _reuse_anchor_reinforcement(db, user_id=user.id, now=now, cfg=cfg)


def _select_for_role(
    db: Session,
    *,
    user: User,
    role: PresentationRole,
    counters: SessionCounters,
    now: datetime,
    cfg: LearningConfig,
) -> Selection | None:
    if role is PresentationRole.REVIEW:
        return _select_review(db, user_id=user.id, counters=counters, now=now, cfg=cfg)
    if role is PresentationRole.EXPLORATION:
        return _select_exploration(db, user=user, now=now, cfg=cfg)
    return _select_new(db, user_id=user.id)


def _ready_candidates(
    db: Session, *, user_id: int, role: PresentationRole
) -> list[UserSentenceCandidate]:
    return list(
        db.execute(
            sa.select(UserSentenceCandidate)
            .where(
                UserSentenceCandidate.user_id == user_id,
                UserSentenceCandidate.status == CandidateStatus.READY,
                UserSentenceCandidate.presentation_role == role,
            )
            .order_by(UserSentenceCandidate.id)
        )
        .scalars()
        .all()
    )


def _targets_of(db: Session, *, candidate_ids: Sequence[int]) -> dict[int, list[int]]:
    if not candidate_ids:
        return {}
    targets: dict[int, list[int]] = {}
    rows = db.execute(
        sa.select(
            UserSentenceCandidateTarget.candidate_id,
            UserSentenceCandidateTarget.learning_item_id,
        )
        .where(UserSentenceCandidateTarget.candidate_id.in_(candidate_ids))
        .order_by(UserSentenceCandidateTarget.learning_item_id)
    ).all()
    for candidate_id, item_id in rows:
        targets.setdefault(candidate_id, []).append(item_id)
    return targets


def _selection_of(candidate: UserSentenceCandidate, item_ids: Sequence[int]) -> Selection:
    return Selection(
        candidate_id=candidate.id,
        sentence_id=candidate.sentence_id,
        presentation_role=candidate.presentation_role,
        review_reason=candidate.review_reason,
        context_stage=candidate.context_stage,
        target_item_ids=tuple(item_ids),
    )


def _select_review(
    db: Session,
    *,
    user_id: int,
    counters: SessionCounters,
    now: datetime,
    cfg: LearningConfig,
) -> Selection | None:
    """reason의 사용 가능 여부는 Ready Pool에 그 reason의 candidate가 있는지다.

    단 `fsrs_due`는 candidate가 있는 것만으로 부족하고 **target이 실제로 due**여야
    한다. candidate를 만든 뒤에 시간이 흐르지 않았거나 무신호 review로 defer된
    item이면 그 candidate는 지금 due가 아니다.

    `reinforcement`와 `context_repair`는 due를 요구하지 않는다. 그것이 FSRS
    interval을 cap하지 않고도 최소 5회 노출을 채우는 유일한 방법이다(불변식 #4).
    """
    candidates = _ready_candidates(db, user_id=user_id, role=PresentationRole.REVIEW)
    if not candidates:
        return None
    targets = _targets_of(db, candidate_ids=[candidate.id for candidate in candidates])
    states = _load_review_targets(
        db,
        user_id=user_id,
        item_ids=[item_id for items in targets.values() for item_id in items],
    )

    buckets: dict[ReviewReason, list[tuple[ReviewOrderKey, int]]] = {}
    by_id = {candidate.id: candidate for candidate in candidates}
    for candidate in candidates:
        reason = candidate.review_reason
        if reason is None:
            continue
        usable = [
            states[item_id]
            for item_id in targets.get(candidate.id, [])
            if item_id in states and states[item_id].eligible(now)
        ]
        if reason is ReviewReason.FSRS_DUE:
            usable = [target for target in usable if target.due(now)]
        if not usable:
            continue
        # candidate가 target 2개면 candidate의 키는 target 키들의 최소값이다.
        buckets.setdefault(reason, []).append(
            (min(target.order_key for target in usable), candidate.id)
        )

    reason = choose_review_reason(buckets, counters, cfg.reinforcement_min_share_of_review)
    if reason is None:
        return None
    _, candidate_id = min(buckets[reason])
    return _selection_of(by_id[candidate_id], targets.get(candidate_id, []))


def _select_exploration(
    db: Session, *, user: User, now: datetime, cfg: LearningConfig
) -> Selection | None:
    """Ready Pool의 exploration candidate도 target 조건을 **다시** 확인한다.

    candidate를 만든 뒤 사용자가 그 item을 클릭해 학습 target으로 승격시켰거나
    최근에 다른 문장에서 노출됐을 수 있다. 만족하지 않으면 건너뛰고 다음
    candidate로 넘어간다.
    """
    candidates = _ready_candidates(db, user_id=user.id, role=PresentationRole.EXPLORATION)
    if not candidates:
        return None
    targets = _targets_of(db, candidate_ids=[candidate.id for candidate in candidates])
    eligible = eligible_exploration_targets(
        db,
        user_id=user.id,
        item_ids=[item_id for items in targets.values() for item_id in items],
        now=now,
        recent_days=cfg.exploration_recent_days,
    )
    items = {
        item.id: item
        for item in db.execute(sa.select(LearningItem).where(LearningItem.id.in_(eligible)))
        .scalars()
        .all()
    }

    best: tuple[tuple[ExplorationSortKey, int], UserSentenceCandidate] | None = None
    for candidate in candidates:
        usable = [items[item_id] for item_id in targets.get(candidate.id, []) if item_id in items]
        if not usable:
            continue
        key = (
            min(exploration_sort_key(item, starting_level=user.starting_level) for item in usable),
            candidate.id,
        )
        if best is None or key < best[0]:
            best = (key, candidate)

    if best is None:
        return None
    return _selection_of(best[1], targets.get(best[1].id, []))


def _select_new(db: Session, *, user_id: int) -> Selection | None:
    """`new`에는 명세가 정한 정렬이 없다. candidate id ASC로 결정론만 확보한다."""
    candidates = _ready_candidates(db, user_id=user_id, role=PresentationRole.NEW)
    if not candidates:
        return None
    targets = _targets_of(db, candidate_ids=[candidate.id for candidate in candidates])
    for candidate in candidates:
        item_ids = targets.get(candidate.id, [])
        if item_ids:
            return _selection_of(candidate, item_ids)
    return None


def _reuse_anchor_reinforcement(
    db: Session, *, user_id: int, now: datetime, cfg: LearningConfig
) -> Selection | None:
    """Pool Fallback 2: 안전한 기존 anchor 문장을 reinforcement로 다시 쓴다.

    0단계 materialization이 아무것도 만들지 못하는 대표적인 경우는 item의 현재
    stage(`varied` / `new_context`)가 **아직 보지 않은 문장**을 요구하는데 남은
    문장이 없을 때다. 그때 새 문맥을 만드는 것은 Wave 3의 일이고, 지금 할 수 있는
    안전한 일은 이미 본 anchor 문맥을 다시 보여주는 것이다.

    최소 노출에 아직 도달하지 않은 item만 대상으로 한다. 이미 충분히 본 item을
    다시 보여주느니 콘텐츠 생성을 기다리는 편이 낫다(3단계).
    """
    targets = _load_review_targets(db, user_id=user_id)
    anchors = {
        state.learning_item_id: state.anchor_sentence_id
        for state in db.execute(
            sa.select(UserItemLearningState).where(UserItemLearningState.user_id == user_id)
        )
        .scalars()
        .all()
    }

    for target in sorted(targets.values(), key=lambda item: item.order_key):
        if not target.eligible(now):
            continue
        item_id = target.learning_item_id
        if _valid_exposure_count(db, user_id=user_id, learning_item_id=item_id) >= (
            cfg.minimum_meaningful_exposures
        ):
            continue
        picked = _stage_sentence(
            db,
            user_id=user_id,
            item_id=item_id,
            stage=ContextStage.ANCHOR,
            anchor_id=anchors.get(item_id),
        )
        if picked is None:
            continue
        # 재지정 신호는 여기서 쓰지 않는다. `anchor_sentence_id`의 쓰기 소유자는
        # `_review_plans`이고, 그 쪽이 이 fallback보다 **먼저** 같은 요청에서 돈다.
        sentence_id = picked.sentence_id
        plan = _Plan(item_id, sentence_id, ContextStage.ANCHOR, ReviewReason.REINFORCEMENT)
        candidate_id = _insert_candidate(
            db, user_id=user_id, role=PresentationRole.REVIEW, plan=plan, now=now
        )
        if candidate_id is None:
            continue
        _insert_target(db, candidate_id=candidate_id, user_id=user_id, item_id=item_id)
        db.flush()
        return Selection(
            candidate_id=candidate_id,
            sentence_id=sentence_id,
            presentation_role=PresentationRole.REVIEW,
            review_reason=ReviewReason.REINFORCEMENT,
            context_stage=ContextStage.ANCHOR,
            target_item_ids=(item_id,),
        )
    return None
