"""Pool Fallback 3단계의 enqueue (09_BACKGROUND_JOBS.md, 불변식 #1).

이 모듈은 INSERT만 한다. provider 호출도 worker 동작도 여기에 없다 --- 그 검증은
`test_module_boundaries.py`의 G4가 import 수준에서 한다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.jobs.replenishment import enqueue_replenishment, replenishment_idempotency_key
from app.models import GenerationJob
from app.models.enums import GenerationJobStatus, JobType, PresentationRole
from tests import factories
from tests.clock import MutableClock

REVIEW = PresentationRole.REVIEW
NEW = PresentationRole.NEW


# --------------------------------------------------------------------------
# idempotency key (순수)
# --------------------------------------------------------------------------


def test_the_key_is_deterministic() -> None:
    """결정적이지 않으면 ON CONFLICT가 아무것도 막지 못한다."""
    clock = MutableClock()

    first = replenishment_idempotency_key(user_id=1, role=REVIEW, now=clock.now())
    second = replenishment_idempotency_key(user_id=1, role=REVIEW, now=clock.now())

    assert first == second


def test_the_key_separates_user_role_and_day() -> None:
    """셋 중 하나라도 빠지면 억제 창이 남의 job까지 막거나 영원히 재enqueue를 막는다."""
    clock = MutableClock()
    base = replenishment_idempotency_key(user_id=1, role=REVIEW, now=clock.now())

    assert base != replenishment_idempotency_key(user_id=2, role=REVIEW, now=clock.now())
    assert base != replenishment_idempotency_key(user_id=1, role=NEW, now=clock.now())
    assert base != replenishment_idempotency_key(
        user_id=1, role=REVIEW, now=clock.now() + timedelta(days=1)
    )


def test_the_key_ignores_the_time_of_day() -> None:
    """시각이 들어가면 한 세션에서 Pool Fallback을 만날 때마다 job이 하나씩 쌓인다."""
    clock = MutableClock()

    morning = replenishment_idempotency_key(user_id=1, role=REVIEW, now=clock.now())
    evening = replenishment_idempotency_key(
        user_id=1, role=REVIEW, now=clock.now() + timedelta(hours=6)
    )

    assert morning == evening


# --------------------------------------------------------------------------
# enqueue (DB)
# --------------------------------------------------------------------------


def _count_jobs(db: Session) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(GenerationJob)).scalar_one())


@pytest.mark.integration
def test_the_first_call_queues_a_sentence_batch_job(
    db_session: Session, study_clock: MutableClock
) -> None:
    cfg = get_config()
    user = factories.make_user(db_session)

    job = enqueue_replenishment(
        db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )

    assert job is not None
    # replenishment는 job_type이 아니다. GENERATE_SENTENCE_BATCH를 부르는 트리거다.
    assert job.job_type is JobType.GENERATE_SENTENCE_BATCH
    assert job.status is GenerationJobStatus.QUEUED
    assert job.max_attempts == cfg.jobs.max_job_attempts
    assert job.retry_count == 0
    assert job.next_attempt_at == study_clock.now()
    assert job.created_at == study_clock.now()
    assert job.started_at is None
    assert job.payload_json == {"user_id": user.id, "presentation_role": REVIEW.value}


@pytest.mark.integration
def test_calling_again_in_the_same_window_leaves_one_job(
    db_session: Session, study_clock: MutableClock
) -> None:
    """Pool Fallback은 한 세션에서 여러 번 일어난다. 그때마다 job이 쌓이면 비용이 배가 된다."""
    cfg = get_config()
    user = factories.make_user(db_session)

    first = enqueue_replenishment(
        db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )
    study_clock.advance(timedelta(minutes=3))
    second = enqueue_replenishment(
        db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )

    assert first is not None
    assert second is None
    assert _count_jobs(db_session) == 1


@pytest.mark.integration
def test_each_role_gets_its_own_job(db_session: Session, study_clock: MutableClock) -> None:
    """review pool이 비어서 만든 job이 new pool의 job을 막으면 안 된다."""
    cfg = get_config()
    user = factories.make_user(db_session)

    enqueue_replenishment(db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg)
    other = enqueue_replenishment(
        db_session, user_id=user.id, role=NEW, now=study_clock.now(), cfg=cfg
    )

    assert other is not None
    assert _count_jobs(db_session) == 2


@pytest.mark.integration
def test_two_users_do_not_share_one_job(db_session: Session, study_clock: MutableClock) -> None:
    cfg = get_config()
    user_a = factories.make_user(db_session)
    user_b = factories.make_user(db_session)

    enqueue_replenishment(
        db_session, user_id=user_a.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )
    other = enqueue_replenishment(
        db_session, user_id=user_b.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )

    assert other is not None
    assert _count_jobs(db_session) == 2


@pytest.mark.integration
def test_the_next_day_can_queue_again(db_session: Session, study_clock: MutableClock) -> None:
    """억제 창이 영구 차단이면 pool이 계속 비어 있어도 콘텐츠가 영영 생기지 않는다."""
    cfg = get_config()
    user = factories.make_user(db_session)

    enqueue_replenishment(db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg)
    study_clock.advance(timedelta(days=1))
    tomorrow = enqueue_replenishment(
        db_session, user_id=user.id, role=REVIEW, now=study_clock.now(), cfg=cfg
    )

    assert tomorrow is not None
    assert _count_jobs(db_session) == 2
