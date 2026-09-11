"""Study session create / resume / finish / extend와 active time (05_API_SPEC.md).

정책값은 전부 config에서 읽는다. 테스트에 12나 30을 적어 두면 config를 무시하는
구현이 통과한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.mastery import MASTERY_ALGORITHM_VERSION
from app.models import (
    LearningEvent,
    SentenceItem,
    SentenceItemExplanation,
    StudyPresentation,
    StudySession,
    User,
    UserItemLearningState,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    EventType,
    ExplanationStatus,
)
from app.services.events import server_client_event_id
from app.services.study_session import (
    StudySessionClosedError,
    StudySessionNotFoundError,
    build_policy_snapshot,
    extend,
    finish,
    get_open_session,
    start_or_resume,
    touch,
)
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION
from tests import factories
from tests.clock import DEFAULT_START, MutableClock

# --------------------------------------------------------------------------
# active_seconds / policy snapshot (순수)
# --------------------------------------------------------------------------


def _detached_session(*, active_seconds: int = 0) -> StudySession:
    """DB에 넣지 않은 session 인스턴스. active time 계산은 DB를 보지 않는다."""
    return StudySession(
        user_id=1,
        started_at=DEFAULT_START,
        last_activity_at=DEFAULT_START,
        active_seconds=active_seconds,
        target_minutes=get_config().learning.default_session_minutes,
        extended_minutes=0,
    )


def test_a_short_gap_is_added_to_active_seconds() -> None:
    cfg = get_config().session
    session = _detached_session()

    touch(session, now=DEFAULT_START + timedelta(seconds=30), cfg=cfg)

    assert session.active_seconds == 30
    assert session.last_activity_at == DEFAULT_START + timedelta(seconds=30)


def test_a_gap_exactly_at_the_limit_still_counts() -> None:
    """경계는 포함이다. 경계 직전/직후가 둘 다 고정돼야 `<`와 `<=`의 차이가 드러난다."""
    cfg = get_config().session
    session = _detached_session()

    touch(session, now=DEFAULT_START + timedelta(seconds=cfg.active_time_idle_gap_seconds), cfg=cfg)

    assert session.active_seconds == cfg.active_time_idle_gap_seconds


def test_a_long_gap_adds_zero_and_is_not_clamped_to_the_limit() -> None:
    """상한값을 대신 더하면 자리를 비운 시간이 매번 그만큼 학습 시간으로 샌다."""
    cfg = get_config().session
    session = _detached_session()
    idle = timedelta(seconds=cfg.active_time_idle_gap_seconds + 1)

    touch(session, now=DEFAULT_START + idle, cfg=cfg)

    assert session.active_seconds == 0
    assert session.last_activity_at == DEFAULT_START + idle


def test_two_short_gaps_accumulate() -> None:
    cfg = get_config().session
    session = _detached_session()

    touch(session, now=DEFAULT_START + timedelta(seconds=10), cfg=cfg)
    touch(session, now=DEFAULT_START + timedelta(seconds=25), cfg=cfg)

    assert session.active_seconds == 25


def test_a_clock_that_goes_backwards_adds_nothing() -> None:
    cfg = get_config().session
    session = _detached_session(active_seconds=5)

    touch(session, now=DEFAULT_START - timedelta(seconds=10), cfg=cfg)

    assert session.active_seconds == 5


def test_the_policy_snapshot_carries_every_learning_key() -> None:
    """키를 골라 담으면 새 config 키가 추가될 때 snapshot이 조용히 뒤처진다."""
    cfg = get_config()

    snapshot = build_policy_snapshot(cfg)

    assert snapshot["learning"] == cfg.learning.model_dump()
    assert snapshot["session"] == cfg.session.model_dump()
    assert snapshot["srs"] == cfg.srs.model_dump()


def test_the_policy_snapshot_identifies_the_code_that_produced_the_values() -> None:
    """alpha만으로는 replay가 되지 않는다. 그 alpha를 어떤 식에 넣었는지가 있어야 한다."""
    snapshot = build_policy_snapshot(get_config())

    assert snapshot["mastery_algorithm_version"] == MASTERY_ALGORITHM_VERSION
    assert snapshot["fsrs_params_version"] == FSRS_PARAMS_VERSION


def _walk(value: object, path: str = "") -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    else:
        yield path, value


def test_the_policy_snapshot_has_no_secret_or_infrastructure_value() -> None:
    """세션 행은 운영자가 열어보는 학습 기록이다. DSN이나 secret이 실릴 자리가 아니다."""
    markers = ("password", "secret", "token", "dsn", "url", "cookie", "hash", "credential")

    for path, value in _walk(build_policy_snapshot(get_config())):
        assert not any(marker in path.lower() for marker in markers), path
        if isinstance(value, str):
            assert "://" not in value, path


# --------------------------------------------------------------------------
# create / resume (DB)
# --------------------------------------------------------------------------


def _events(db: Session, *, user_id: int, event_type: EventType) -> list[LearningEvent]:
    return list(
        db.execute(
            sa.select(LearningEvent)
            .where(LearningEvent.user_id == user_id, LearningEvent.event_type == event_type)
            .order_by(LearningEvent.id)
        )
        .scalars()
        .all()
    )


@pytest.mark.integration
def test_a_new_session_takes_its_target_minutes_from_config(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)

    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    assert started.resumed is False
    assert started.timed_out_session_id is None
    assert started.session.target_minutes == cfg.learning.default_session_minutes
    assert started.session.started_at == study_clock.now()
    assert started.session.active_seconds == 0
    assert started.session.policy_snapshot_json == build_policy_snapshot(cfg)


@pytest.mark.integration
def test_starting_a_session_records_session_started_with_the_server_key(
    db_session: Session, study_clock: MutableClock
) -> None:
    user = factories.make_user(db_session)

    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=get_config())

    events = _events(db_session, user_id=user.id, event_type=EventType.SESSION_STARTED)
    assert len(events) == 1
    assert events[0].client_event_id == server_client_event_id(
        EventType.SESSION_STARTED, study_session_id=started.session.id
    )
    assert events[0].created_at == study_clock.now()


@pytest.mark.integration
def test_a_session_start_materializes_the_ready_pool_for_that_user(
    db_session: Session, study_clock: MutableClock
) -> None:
    """seed만 적재된 신규 사용자가 첫 세션을 시작할 수 있어야 한다(05_API_SPEC.md).

    provider를 부르지 않고 이미 validated인 콘텐츠를 투영할 뿐이다.
    """
    user = factories.make_user(db_session)
    _seed_new_item_content(db_session, user)

    start_or_resume(db_session, user=user, now=study_clock.now(), cfg=get_config())

    ready = db_session.execute(
        sa.select(sa.func.count())
        .select_from(UserSentenceCandidate)
        .where(
            UserSentenceCandidate.user_id == user.id,
            UserSentenceCandidate.status == CandidateStatus.READY,
        )
    ).scalar_one()
    assert ready >= 1


@pytest.mark.integration
def test_returning_exactly_at_the_idle_limit_resumes_the_same_session(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    first = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    study_clock.advance(timedelta(minutes=cfg.session.study_session_idle_timeout_minutes))
    second = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    assert second.resumed is True
    assert second.session.id == first.session.id
    assert second.session.ended_at is None
    assert len(_events(db_session, user_id=user.id, event_type=EventType.SESSION_STARTED)) == 1


@pytest.mark.integration
def test_one_second_past_the_idle_limit_starts_a_new_session(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    first = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    last_activity_at = first.session.last_activity_at

    study_clock.advance(
        timedelta(minutes=cfg.session.study_session_idle_timeout_minutes, seconds=1)
    )
    second = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    assert second.resumed is False
    assert second.session.id != first.session.id
    assert second.timed_out_session_id == first.session.id
    # 가정: 밀려난 세션은 마지막 활동 시각에 끝난 것으로 본다. now로 채우면 자리를
    # 비운 시간이 세션 길이에 들어간다.
    assert first.session.ended_at == last_activity_at
    assert len(_events(db_session, user_id=user.id, event_type=EventType.SESSION_FINISHED)) == 1
    assert get_open_session(db_session, user_id=user.id) is not None
    assert get_open_session(db_session, user_id=user.id).id == second.session.id  # type: ignore[union-attr]


@pytest.mark.integration
def test_a_timed_out_session_leaves_its_unfinished_presentation_alone(
    db_session: Session, study_clock: MutableClock
) -> None:
    """가정: timeout은 부재의 추론이므로 `sentence_completed`를 만들어내지 않는다.

    `/finish`는 사용자의 명시적 종료라서 반대로 동작한다(아래 finish 테스트).
    """
    cfg = get_config()
    user = factories.make_user(db_session)
    first = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    presentation = _presentation_for(db_session, user, first.session)

    study_clock.advance(
        timedelta(minutes=cfg.session.study_session_idle_timeout_minutes, seconds=1)
    )
    start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    assert presentation.completed_at is None
    assert _events(db_session, user_id=user.id, event_type=EventType.SENTENCE_COMPLETED) == []


@pytest.mark.integration
def test_one_users_open_session_is_not_resumed_by_another(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user_a = factories.make_user(db_session)
    user_b = factories.make_user(db_session)
    started_a = start_or_resume(db_session, user=user_a, now=study_clock.now(), cfg=cfg)

    started_b = start_or_resume(db_session, user=user_b, now=study_clock.now(), cfg=cfg)

    assert started_b.session.id != started_a.session.id
    assert started_b.resumed is False


# --------------------------------------------------------------------------
# finish (DB)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_finishing_closes_the_session_and_the_open_presentation(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    presentation = _presentation_for(db_session, user, started.session)

    study_clock.advance(timedelta(seconds=30))
    finished = finish(
        db_session,
        user_id=user.id,
        session_id=started.session.id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert finished.ended_at == study_clock.now()
    assert finished.active_seconds == 30
    assert presentation.completed_at == study_clock.now()
    completed = _events(db_session, user_id=user.id, event_type=EventType.SENTENCE_COMPLETED)
    assert len(completed) == 1
    assert completed[0].client_event_id == server_client_event_id(
        EventType.SENTENCE_COMPLETED, study_presentation_id=presentation.id
    )
    assert len(_events(db_session, user_id=user.id, event_type=EventType.SESSION_FINISHED)) == 1


@pytest.mark.integration
def test_finishing_twice_changes_nothing(db_session: Session, study_clock: MutableClock) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    first = finish(
        db_session, user_id=user.id, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )
    ended_at = first.ended_at

    study_clock.advance(timedelta(seconds=30))
    second = finish(
        db_session, user_id=user.id, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )

    assert second.ended_at == ended_at
    assert len(_events(db_session, user_id=user.id, event_type=EventType.SESSION_FINISHED)) == 1


@pytest.mark.integration
def test_finishing_someone_elses_session_is_not_found(
    db_session: Session, study_clock: MutableClock
) -> None:
    """ "남의 세션"과 "없는 세션"을 구분하지 않는다. 구분하면 id 훑기로 존재를 알아낼 수
    있다."""
    cfg = get_config()
    owner = factories.make_user(db_session)
    other = factories.make_user(db_session)
    started = start_or_resume(db_session, user=owner, now=study_clock.now(), cfg=cfg)

    with pytest.raises(StudySessionNotFoundError):
        finish(
            db_session,
            user_id=other.id,
            session_id=started.session.id,
            now=study_clock.now(),
            cfg=cfg,
        )


# --------------------------------------------------------------------------
# extend (DB)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_extending_adds_the_configured_minutes(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    session = extend(
        db_session,
        user_id=user.id,
        session_id=started.session.id,
        client_event_id=uuid.uuid4(),
        now=study_clock.now(),
        cfg=cfg,
    )

    assert session.extended_minutes == cfg.learning.extra_session_minutes


@pytest.mark.integration
def test_resending_the_same_extend_does_not_extend_twice(
    db_session: Session, study_clock: MutableClock
) -> None:
    """client 발급 key의 존재 이유다. 재전송이 `+5분`을 한 번 더 주면 그 UUID는 장식이다."""
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    client_event_id = uuid.uuid4()

    extend(
        db_session,
        user_id=user.id,
        session_id=started.session.id,
        client_event_id=client_event_id,
        now=study_clock.now(),
        cfg=cfg,
    )
    study_clock.advance(timedelta(seconds=3))
    session = extend(
        db_session,
        user_id=user.id,
        session_id=started.session.id,
        client_event_id=client_event_id,
        now=study_clock.now(),
        cfg=cfg,
    )

    assert session.extended_minutes == cfg.learning.extra_session_minutes
    assert len(_events(db_session, user_id=user.id, event_type=EventType.SESSION_EXTENDED)) == 1


@pytest.mark.integration
def test_a_second_deliberate_extension_uses_a_second_key(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)

    for _ in range(2):
        session = extend(
            db_session,
            user_id=user.id,
            session_id=started.session.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )

    assert session.extended_minutes == 2 * cfg.learning.extra_session_minutes


@pytest.mark.integration
def test_a_finished_session_cannot_be_extended(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)
    started = start_or_resume(db_session, user=user, now=study_clock.now(), cfg=cfg)
    finish(
        db_session, user_id=user.id, session_id=started.session.id, now=study_clock.now(), cfg=cfg
    )

    with pytest.raises(StudySessionClosedError):
        extend(
            db_session,
            user_id=user.id,
            session_id=started.session.id,
            client_event_id=uuid.uuid4(),
            now=study_clock.now(),
            cfg=cfg,
        )


# --------------------------------------------------------------------------
# 보조
# --------------------------------------------------------------------------


def _presentation_for(db: Session, user: User, study_session: StudySession) -> StudyPresentation:
    sentence = factories.make_sentence(db)
    candidate = factories.make_candidate(db, user, sentence, status=CandidateStatus.SHOWN)
    return factories.make_presentation(db, user, study_session, candidate, sentence)


def _seed_new_item_content(db: Session, user: User) -> None:
    """`new` role materialization이 볼 수 있는 최소 콘텐츠.

    Ready invariant를 만족해야 한다 --- tappable item에 validated explanation이 없으면
    candidate가 만들어지지 않는다(08_LLM_SPEC.md).
    """
    item = factories.make_learning_item(db)
    sentence = factories.make_sentence(db)
    sentence_item = SentenceItem(
        sentence_id=sentence.id,
        learning_item_id=item.id,
        surface_form=item.lemma,
        is_tappable=True,
        created_at=factories.NOW,
    )
    db.add(sentence_item)
    db.flush()
    db.add(
        SentenceItemExplanation(
            sentence_item_id=sentence_item.id,
            reading="r",
            core_meaning="c",
            meaning_in_context="m",
            nuance="n",
            example_sentence="e",
            generated_at=factories.NOW,
            status=ExplanationStatus.VALIDATED,
        )
    )
    db.add(
        UserItemLearningState(
            user_id=user.id,
            learning_item_id=item.id,
            context_stage=ContextStage.ANCHOR,
            is_active_learning_target=True,
            updated_at=factories.NOW,
        )
    )
    db.flush()
