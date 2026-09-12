"""Job queue의 claim / 상태 전이 / backoff / lease 회수 (09_BACKGROUND_JOBS.md).

여기 있는 DB 테스트는 전부 `committed_db`를 쓴다. `db_session`은 커넥션 하나 안에서
끝나므로 `FOR UPDATE SKIP LOCKED`도, "커밋된 뒤에 남는 값"도 볼 수 없다 --- job
queue는 그 둘이 검사 대상이다.

시각은 전부 `study_clock`이 준다. 이 모듈은 `datetime.now()`를 부르지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import queue
from app.models.enums import GenerationJobStatus, JobType
from app.models.jobs import GenerationJob
from tests.clock import MutableClock
from tests.conftest import override_config

QUEUED = GenerationJobStatus.QUEUED
RUNNING = GenerationJobStatus.RUNNING
VALIDATED = GenerationJobStatus.VALIDATED
COMPLETED = GenerationJobStatus.COMPLETED
RETRY = GenerationJobStatus.RETRY
FAILED = GenerationJobStatus.FAILED
DEAD_LETTER = GenerationJobStatus.DEAD_LETTER

_KEY_SEQUENCE = iter(range(1, 10_000))


def _job(
    db: Session,
    *,
    now: datetime,
    status: GenerationJobStatus = QUEUED,
    next_attempt_at: datetime | None = None,
    started_at: datetime | None = None,
    retry_count: int = 0,
    max_attempts: int = 3,
    result_ref: dict[str, object] | None = None,
) -> GenerationJob:
    """queue 테스트가 필요로 하는 상태를 그대로 만드는 job.

    `factories.make_generation_job`을 쓰지 않는다. 그쪽은 enqueue 직후의 모양
    하나만 만들고 `status` / `started_at` / `retry_count`를 받지 않는데, 이 파일이
    검사하는 것이 정확히 그 세 값의 전이다.
    """
    job = GenerationJob(
        job_type=JobType.GENERATE_SENTENCE_BATCH,
        status=status,
        payload_json={},
        result_ref=result_ref,
        idempotency_key=f"queue-test:{next(_KEY_SEQUENCE)}",
        retry_count=retry_count,
        max_attempts=max_attempts,
        next_attempt_at=next_attempt_at if next_attempt_at is not None else now,
        started_at=started_at,
        created_at=now,
    )
    db.add(job)
    db.commit()
    return job


def _reload(db: Session, job: GenerationJob) -> GenerationJob:
    """다른 커넥션이 **커밋한** 값을 읽는다. 캐시된 인스턴스를 믿지 않는다."""
    fresh = db.get(GenerationJob, job.id, populate_existing=True)
    assert fresh is not None
    return fresh


@pytest.fixture
def db(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    """이 테스트의 "worker" 커넥션 하나."""
    with committed_db() as session:
        yield session


def _cfg(**jobs: object) -> AppConfig:
    return override_config(get_config(), jobs=jobs)


# --------------------------------------------------------------------------
# backoff (순수)
# --------------------------------------------------------------------------


def test_the_backoff_doubles_from_the_configured_base() -> None:
    """`base * 2 ** (retry_count - 1)`. 첫 재시도가 base다."""
    cfg = _cfg(retry_backoff_base_seconds=60)

    delays = [queue.retry_delay(retry_count=n, cfg=cfg) for n in (1, 2, 3, 4)]

    assert delays == [
        timedelta(seconds=60),
        timedelta(seconds=120),
        timedelta(seconds=240),
        timedelta(seconds=480),
    ]


def test_the_backoff_reads_the_configured_base() -> None:
    """숫자를 코드에 박으면 config를 아예 읽지 않는 구현도 통과한다."""
    assert queue.retry_delay(retry_count=1, cfg=_cfg(retry_backoff_base_seconds=7)) == timedelta(
        seconds=7
    )


# --------------------------------------------------------------------------
# claim
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_claiming_moves_a_queued_job_to_running(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    job = _job(db, now=now)

    claimed = queue.claim_next_job(db, now=now)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status is RUNNING
    assert claimed.started_at == now


@pytest.mark.integration
def test_the_claim_commit_already_contains_the_attempt(
    committed_db: sessionmaker[Session], db: Session, study_clock: MutableClock
) -> None:
    """`retry_count` 증가가 claim 커밋에 있는지 **다른 커넥션에서** 확인한다.

    실패 경로로 옮기면 crash한 job은 증가 없이 lease로 회수되기만 하고, 예산을
    영원히 쓰지 않는다(ADR-015). 같은 세션에서 읽으면 커밋 여부를 구분하지 못하므로
    두 번째 커넥션으로 본다.
    """
    now = study_clock.now()
    job = _job(db, now=now)

    queue.claim_next_job(db, now=now)

    with committed_db() as observer:
        seen = _reload(observer, job)
        assert seen.status is RUNNING
        assert seen.retry_count == 1


@pytest.mark.integration
def test_claiming_returns_nothing_when_the_queue_is_empty(
    db: Session, study_clock: MutableClock
) -> None:
    assert queue.claim_next_job(db, now=study_clock.now()) is None


@pytest.mark.integration
def test_a_job_scheduled_for_later_is_not_claimed(db: Session, study_clock: MutableClock) -> None:
    """backoff는 이 조건 하나로 성립한다. 여기가 무너지면 재시도가 즉시 반복된다."""
    now = study_clock.now()
    _job(db, now=now, status=RETRY, next_attempt_at=now + timedelta(seconds=1))

    assert queue.claim_next_job(db, now=now) is None

    study_clock.advance(timedelta(seconds=1))
    assert queue.claim_next_job(db, now=study_clock.now()) is not None


@pytest.mark.integration
def test_the_oldest_due_job_goes_first(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    later = _job(db, now=now, next_attempt_at=now)
    earlier = _job(db, now=now, next_attempt_at=now - timedelta(minutes=5))

    claimed = queue.claim_next_job(db, now=now)

    assert claimed is not None
    assert claimed.id == earlier.id
    assert claimed.id != later.id


@pytest.mark.integration
@pytest.mark.parametrize("status", [RUNNING, VALIDATED, COMPLETED, FAILED, DEAD_LETTER])
def test_only_queued_and_retry_are_claimable(
    db: Session, study_clock: MutableClock, status: GenerationJobStatus
) -> None:
    """끝난 job이 다시 집히면 provider 비용이 그대로 다시 나간다."""
    now = study_clock.now()
    _job(db, now=now, status=status, started_at=now)

    assert queue.claim_next_job(db, now=now) is None


# --------------------------------------------------------------------------
# 두 커넥션 (FOR UPDATE SKIP LOCKED)
#
# 스레드를 쓰지 않는다. 세션 두 개면 커넥션도 두 개이고, A가 트랜잭션을 연 채로
# 두면 B가 보는 것은 실제 운영에서 두 worker가 겹치는 순간과 같다. 대신 B에
# `lock_timeout`을 걸어 둔다 --- `SKIP LOCKED`가 사라지면 B는 A를 **기다리므로**,
# 이것이 없으면 회귀가 실패가 아니라 hang으로 나타난다.
# --------------------------------------------------------------------------


def _hold_claim(session: Session, *, now: datetime) -> int:
    """claim을 실행하고 **커밋하지 않는다.** 반환할 때까지 그 행의 잠금을 쥐고 있다."""
    job_id = session.execute(queue.claim_statement(now=now)).scalar_one_or_none()
    assert job_id is not None
    return int(job_id)


def _fail_fast_on_lock(session: Session) -> None:
    session.execute(sa.text("SET lock_timeout = '2s'"))


@pytest.mark.integration
def test_two_connections_never_claim_the_same_job(
    committed_db: sessionmaker[Session], study_clock: MutableClock
) -> None:
    now = study_clock.now()
    with committed_db() as setup:
        first = _job(setup, now=now, next_attempt_at=now - timedelta(minutes=1))
        second = _job(setup, now=now, next_attempt_at=now)

    with committed_db() as worker_a, committed_db() as worker_b:
        _fail_fast_on_lock(worker_b)
        held = _hold_claim(worker_a, now=now)

        other = queue.claim_next_job(worker_b, now=now)

        assert held == first.id
        assert other is not None
        assert other.id == second.id
        worker_a.rollback()


@pytest.mark.integration
def test_a_second_worker_gets_nothing_rather_than_the_locked_job(
    committed_db: sessionmaker[Session], study_clock: MutableClock
) -> None:
    """집을 것이 그 하나뿐이면 두 번째 worker는 **빈손**이다. 기다리지도, 뺏지도 않는다."""
    now = study_clock.now()
    with committed_db() as setup:
        only = _job(setup, now=now)

    with committed_db() as worker_a, committed_db() as worker_b:
        _fail_fast_on_lock(worker_b)
        held = _hold_claim(worker_a, now=now)

        assert held == only.id
        assert queue.claim_next_job(worker_b, now=now) is None
        worker_a.rollback()


# --------------------------------------------------------------------------
# 성공 경로: running -> validated -> completed
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_validation_is_recorded_before_the_content_is_saved(
    committed_db: sessionmaker[Session], db: Session, study_clock: MutableClock
) -> None:
    """`validated`는 진단 지점이다. 커밋되지 않으면 상태로서 존재하지 않는다."""
    now = study_clock.now()
    job = _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None

    queue.mark_validated(db, job=claimed)

    with committed_db() as observer:
        assert _reload(observer, job).status is VALIDATED


@pytest.mark.integration
def test_completion_is_written_in_the_callers_transaction(
    committed_db: sessionmaker[Session], db: Session, study_clock: MutableClock
) -> None:
    """`apply_completion`은 커밋하지 않는다. 저장하는 쪽이 같은 커밋에 얹는다.

    나누면 콘텐츠는 저장됐는데 completed가 아닌 job이 남고, 재실행이 콘텐츠를 두 번
    만든다(ADR-015).
    """
    now = study_clock.now()
    job = _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None

    queue.apply_completion(db, job=claimed, now=now, result={"sentence_ids": [1, 2]})

    with committed_db() as observer:
        assert _reload(observer, job).status is not COMPLETED

    db.commit()
    with committed_db() as observer:
        saved = _reload(observer, job)
        assert saved.status is COMPLETED
        assert saved.finished_at == now
        assert saved.result_ref == {"sentence_ids": [1, 2]}


@pytest.mark.integration
def test_a_rolled_back_save_leaves_the_job_unfinished(
    db: Session, study_clock: MutableClock
) -> None:
    """저장 실패를 성공처럼 적지 않는다. 롤백하면 job도 completed가 아니다."""
    now = study_clock.now()
    job = _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None

    queue.apply_completion(db, job=claimed, now=now, result={"sentence_ids": [1]})
    db.rollback()

    assert _reload(db, job).status is RUNNING


@pytest.mark.integration
def test_completed_jobs_are_not_claimed_again(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None
    queue.apply_completion(db, job=claimed, now=now, result={})
    db.commit()

    assert queue.claim_next_job(db, now=now) is None


# --------------------------------------------------------------------------
# 실패 경로: retry -> failed / dead_letter
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_retryable_failure_reschedules_with_backoff(
    db: Session, study_clock: MutableClock
) -> None:
    cfg = _cfg(retry_backoff_base_seconds=30)
    now = study_clock.now()
    _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None

    status = queue.record_retryable_failure(db, job=claimed, error="provider 5xx", now=now, cfg=cfg)

    assert status is RETRY
    assert claimed.next_attempt_at == now + timedelta(seconds=30)
    assert claimed.retry_count == 1
    assert claimed.last_error == "provider 5xx"
    assert claimed.finished_at is None


@pytest.mark.integration
def test_the_delay_grows_with_each_attempt(db: Session, study_clock: MutableClock) -> None:
    """claim -> 실패를 반복하며 실제 `next_attempt_at` 간격이 두 배가 되는지 본다."""
    cfg = _cfg(retry_backoff_base_seconds=10, max_job_attempts=4)
    now = study_clock.now()
    _job(db, now=now, max_attempts=4)

    delays = []
    for _ in range(3):
        claimed = queue.claim_next_job(db, now=study_clock.now())
        assert claimed is not None
        queue.record_retryable_failure(
            db, job=claimed, error="timeout", now=study_clock.now(), cfg=cfg
        )
        assert claimed.status is RETRY
        delays.append(claimed.next_attempt_at - study_clock.now())
        study_clock.set(claimed.next_attempt_at)

    assert delays == [timedelta(seconds=10), timedelta(seconds=20), timedelta(seconds=40)]


@pytest.mark.integration
def test_the_last_attempt_ends_in_failed_and_is_never_claimed_again(
    db: Session, study_clock: MutableClock
) -> None:
    """무한 retry 금지. 예산을 소진하면 끝이고, 그 뒤로는 claim 대상이 아니다."""
    cfg = _cfg(retry_backoff_base_seconds=1, max_job_attempts=3)
    now = study_clock.now()
    _job(db, now=now, max_attempts=3)

    attempts = 0
    while (claimed := queue.claim_next_job(db, now=study_clock.now())) is not None:
        attempts += 1
        assert attempts <= 3, "예산을 넘겨 계속 claim된다"
        queue.record_retryable_failure(
            db, job=claimed, error="timeout", now=study_clock.now(), cfg=cfg
        )
        study_clock.advance(timedelta(minutes=1))

    assert attempts == 3
    assert claimed is None
    only = db.execute(sa.select(GenerationJob)).scalar_one()
    assert only.status is FAILED
    assert only.retry_count == 3
    assert only.finished_at is not None


@pytest.mark.integration
@pytest.mark.parametrize("reason", list(queue.PermanentReason))
def test_a_permanent_error_dead_letters_without_spending_the_budget(
    db: Session, study_clock: MutableClock, reason: queue.PermanentReason
) -> None:
    """4종 영구 오류는 attempt를 소진하지 않고 즉시 끝난다."""
    now = study_clock.now()
    _job(db, now=now, max_attempts=3)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None

    queue.record_permanent_failure(db, job=claimed, reason=reason, now=now)

    assert claimed.status is DEAD_LETTER
    assert claimed.retry_count == 1
    assert claimed.last_error == reason.value
    assert claimed.finished_at == now
    assert queue.claim_next_job(db, now=now) is None


def test_dead_letter_is_limited_to_the_four_permanent_errors() -> None:
    """목록이 늘면 재시도했어야 할 오류가 조용히 영구 실패가 된다(특히 인증 실패)."""
    assert {reason.value for reason in queue.PermanentReason} == {
        "invalid_payload",
        "missing_reference",
        "unsupported_job_type",
        "no_active_prompt_version",
    }


# --------------------------------------------------------------------------
# stale running 회수
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_job_whose_lease_expired_goes_back_to_retry(
    db: Session, study_clock: MutableClock
) -> None:
    """crash한 worker가 남긴 `running`은 아무 조건에도 걸리지 않는다. lease가 그것을 푼다."""
    cfg = _cfg(claim_lease_seconds=300)
    now = study_clock.now()
    job = _job(db, now=now)
    claimed = queue.claim_next_job(db, now=now)
    assert claimed is not None
    study_clock.advance(timedelta(seconds=301))

    reclaimed = queue.reclaim_stale_jobs(db, now=study_clock.now(), cfg=cfg)

    assert reclaimed == 1
    recovered = _reload(db, job)
    assert recovered.status is RETRY
    # 증가시키지 않으면 실행할 때마다 죽는 job이 영원히 회수-재실행을 반복한다.
    assert recovered.retry_count == 2
    assert recovered.next_attempt_at == study_clock.now()
    assert recovered.last_error == queue.LEASE_EXPIRED


@pytest.mark.integration
def test_a_running_job_inside_its_lease_is_left_alone(
    db: Session, study_clock: MutableClock
) -> None:
    """실행 중인 job을 뺏으면 provider를 두 번 부른다."""
    cfg = _cfg(claim_lease_seconds=300)
    now = study_clock.now()
    job = _job(db, now=now)
    assert queue.claim_next_job(db, now=now) is not None
    study_clock.advance(timedelta(seconds=299))

    assert queue.reclaim_stale_jobs(db, now=study_clock.now(), cfg=cfg) == 0
    assert _reload(db, job).status is RUNNING


@pytest.mark.integration
def test_a_reclaimed_job_becomes_claimable_again(db: Session, study_clock: MutableClock) -> None:
    cfg = _cfg(claim_lease_seconds=60)
    now = study_clock.now()
    job = _job(db, now=now, max_attempts=5)
    queue.claim_next_job(db, now=now)
    study_clock.advance(timedelta(seconds=61))
    queue.reclaim_stale_jobs(db, now=study_clock.now(), cfg=cfg)

    again = queue.claim_next_job(db, now=study_clock.now())

    assert again is not None
    assert again.id == job.id
    assert again.retry_count == 3


@pytest.mark.integration
def test_a_worker_that_always_crashes_runs_out_of_attempts(
    db: Session, study_clock: MutableClock
) -> None:
    """crash 루프도 유한하다. 회수가 예산을 소비하지 않으면 이 루프는 끝나지 않는다."""
    cfg = _cfg(claim_lease_seconds=60)
    now = study_clock.now()
    _job(db, now=now, max_attempts=3)

    cycles = 0
    while queue.claim_next_job(db, now=study_clock.now()) is not None:
        cycles += 1
        assert cycles <= 3, "crash한 job이 영원히 재시도된다"
        study_clock.advance(timedelta(seconds=61))
        queue.reclaim_stale_jobs(db, now=study_clock.now(), cfg=cfg)

    only = db.execute(sa.select(GenerationJob)).scalar_one()
    assert only.status is FAILED
    assert only.last_error == queue.LEASE_EXPIRED


# --------------------------------------------------------------------------
# usage
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_usage_is_recorded_immediately_after_the_call(
    committed_db: sessionmaker[Session], db: Session, study_clock: MutableClock
) -> None:
    now = study_clock.now()
    job = _job(db, now=now)

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=100, output_tokens=20, now=now)

    with committed_db() as observer:
        usage = _reload(observer, job).result_ref
        assert usage == {
            "usage": {
                "provider_calls": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "estimated_cost_usd": None,
                "last_call_at": now.isoformat(),
            }
        }


@pytest.mark.integration
def test_usage_accumulates_across_attempts(db: Session, study_clock: MutableClock) -> None:
    """실패한 호출도 비용이다. attempt마다 덮어쓰면 하루 사용량이 과소 계상된다."""
    cfg = _cfg(retry_backoff_base_seconds=1)
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=10, output_tokens=5, now=now)
    queue.record_retryable_failure(db, job=job, error="parse error", now=now, cfg=cfg)
    later = study_clock.advance(timedelta(minutes=1))

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=30, output_tokens=7, now=later)

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"] == {
        "provider_calls": 2,
        "input_tokens": 40,
        "output_tokens": 12,
        "estimated_cost_usd": None,
        "last_call_at": later.isoformat(),
    }


@pytest.mark.integration
def test_completion_does_not_erase_the_usage(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=10, output_tokens=5, now=now)

    queue.apply_completion(db, job=job, now=now, result={"sentence_ids": [9]})
    db.commit()

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["sentence_ids"] == [9]
    assert stored["usage"]["provider_calls"] == 1


@pytest.mark.integration
def test_the_daily_total_covers_the_utc_day_only(db: Session, study_clock: MutableClock) -> None:
    """일 경계는 UTC다. 사용자 timezone을 쓰지 않는다."""
    study_clock.set(datetime(2026, 3, 2, 0, 30, tzinfo=UTC))
    today = study_clock.now()
    yesterday = today - timedelta(hours=1)  # 2026-03-01 23:30 UTC
    old = _job(db, now=yesterday)
    fresh = _job(db, now=today)
    queue.record_usage(
        db, job=old, provider_calls=3, input_tokens=999, output_tokens=999, now=yesterday
    )
    queue.record_usage(db, job=fresh, provider_calls=2, input_tokens=11, output_tokens=4, now=today)

    usage = queue.daily_usage(db, now=today)

    assert usage == queue.DailyUsage(provider_calls=2, input_tokens=11, output_tokens=4)
    assert usage.total_tokens == 15


@pytest.mark.integration
def test_jobs_without_usage_do_not_break_the_total(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    _job(db, now=now)

    assert queue.daily_usage(db, now=now) == queue.DailyUsage(0, 0, 0)


@pytest.mark.integration
def test_a_null_limit_is_off(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(
        db, job=job, provider_calls=99, input_tokens=99_999, output_tokens=1, now=now
    )
    cfg = override_config(
        get_config(), llm={"daily_request_limit": None, "daily_token_limit": None}
    )

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False


@pytest.mark.integration
def test_the_request_ceiling_stops_new_claims(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(get_config(), llm={"daily_request_limit": 2, "daily_token_limit": None})
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=1, output_tokens=1, now=now)

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=1, output_tokens=1, now=now)
    assert queue.ceiling_reached(db, now=now, cfg=cfg) is True


@pytest.mark.integration
def test_the_token_ceiling_counts_input_and_output(db: Session, study_clock: MutableClock) -> None:
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(get_config(), llm={"daily_request_limit": None, "daily_token_limit": 100})
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=60, output_tokens=39, now=now)

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=0, output_tokens=1, now=now)
    assert queue.ceiling_reached(db, now=now, cfg=cfg) is True


# --------------------------------------------------------------------------
# usage를 주지 않는 provider (11_OBSERVABILITY.md의 "if available")
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_unknown_token_counts_are_stored_as_null_not_zero(
    db: Session, study_clock: MutableClock
) -> None:
    """0은 "호출했는데 토큰을 안 썼다"는 거짓 정보다. 모르는 것은 `null`로 적는다."""
    now = study_clock.now()
    job = _job(db, now=now)

    queue.record_usage(
        db, job=job, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["provider_calls"] == 1
    assert stored["usage"]["input_tokens"] is None
    assert stored["usage"]["output_tokens"] is None


@pytest.mark.integration
def test_a_job_that_once_lost_its_token_count_stays_unknown(
    db: Session, study_clock: MutableClock
) -> None:
    """누적값은 그 job의 **총량**이다. 한 attempt를 모르면 총량은 계속 모른다.

    아는 부분만 더해 숫자로 적으면 그 숫자가 총량처럼 보이고, 하루 합계는 조용히
    과소 계상된다.
    """
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(
        db, job=job, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=10, output_tokens=5, now=now)

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["provider_calls"] == 2
    assert stored["usage"]["input_tokens"] is None
    assert stored["usage"]["output_tokens"] is None


@pytest.mark.integration
def test_the_daily_total_marks_itself_incomplete_when_tokens_are_unknown(
    db: Session, study_clock: MutableClock
) -> None:
    now = study_clock.now()
    known = _job(db, now=now)
    unknown = _job(db, now=now)
    queue.record_usage(db, job=known, provider_calls=1, input_tokens=10, output_tokens=5, now=now)
    queue.record_usage(
        db, job=unknown, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    usage = queue.daily_usage(db, now=now)

    assert usage.provider_calls == 2
    assert usage.total_tokens == 15  # 아는 부분만. 총량이 아니라 하한이다.
    assert usage.jobs_with_unknown_tokens == 1
    assert usage.tokens_are_complete is False


@pytest.mark.integration
def test_the_token_ceiling_holds_when_the_total_is_unknown(
    db: Session, study_clock: MutableClock
) -> None:
    """하한을 한도와 비교하는 것은 한도를 지키는 척하는 것이다.

    `daily_token_limit`을 켜 둔 채 token을 셀 수 없게 되면 생성을 멈춘다. 학습 세션은
    Ready Pool로 계속 돈다(불변식 #1). 한도를 끄려면 `null`로 둔다.
    """
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(
        get_config(), llm={"daily_request_limit": None, "daily_token_limit": 1_000_000}
    )
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=1, output_tokens=1, now=now)
    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False

    queue.record_usage(
        db, job=job, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is True


@pytest.mark.integration
def test_an_unknown_token_count_does_not_touch_the_request_ceiling(
    db: Session, study_clock: MutableClock
) -> None:
    """호출 횟수는 언제나 셀 수 있다. token을 몰라도 request 한도는 그대로 판정한다."""
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(get_config(), llm={"daily_request_limit": 5, "daily_token_limit": None})

    queue.record_usage(
        db, job=job, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False


@pytest.mark.integration
def test_a_null_token_limit_is_still_off_when_tokens_are_unknown(
    db: Session, study_clock: MutableClock
) -> None:
    """`null = limit disabled`의 의미는 바뀌지 않는다 (14_CONFIGURATION.md)."""
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(
        get_config(), llm={"daily_request_limit": None, "daily_token_limit": None}
    )
    queue.record_usage(
        db, job=job, provider_calls=1, input_tokens=None, output_tokens=None, now=now
    )

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False


# --------------------------------------------------------------------------
# estimated_cost_usd (token과 같은 sticky-null 누적. ceiling 항목은 아니다)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_cost_accumulates_across_attempts(db: Session, study_clock: MutableClock) -> None:
    """마지막 attempt 값으로 덮어쓰면 retry한 job의 비용이 실제의 1/attempt로 보인다."""
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=10,
        output_tokens=5,
        now=now,
        estimated_cost_usd=0.002,
    )
    later = study_clock.advance(timedelta(minutes=1))

    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=30,
        output_tokens=7,
        now=later,
        estimated_cost_usd=0.004,
    )

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["estimated_cost_usd"] == pytest.approx(0.006)


@pytest.mark.integration
def test_an_unknown_cost_in_one_attempt_makes_the_job_total_unknown(
    db: Session, study_clock: MutableClock
) -> None:
    """sticky-null. 부분 합을 총계로 적으면 그 숫자가 총계처럼 보인다 (token과 같다)."""
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=10,
        output_tokens=5,
        now=now,
        estimated_cost_usd=0.002,
    )

    # provider가 이번 호출의 비용을 알려주지 않았다.
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=30, output_tokens=7, now=now)

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["estimated_cost_usd"] is None


@pytest.mark.integration
def test_a_cost_after_an_unknown_cost_stays_unknown(db: Session, study_clock: MutableClock) -> None:
    """순서가 반대여도 같다. 한 번 모르면 그 job의 총계는 계속 모른다."""
    now = study_clock.now()
    job = _job(db, now=now)
    queue.record_usage(db, job=job, provider_calls=1, input_tokens=10, output_tokens=5, now=now)

    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=30,
        output_tokens=7,
        now=now,
        estimated_cost_usd=0.004,
    )

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["estimated_cost_usd"] is None


@pytest.mark.integration
def test_an_unknown_cost_is_stored_as_null_not_zero(db: Session, study_clock: MutableClock) -> None:
    """0은 "호출했는데 비용이 없었다"는 거짓 정보다."""
    now = study_clock.now()
    job = _job(db, now=now)

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=10, output_tokens=5, now=now)

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["estimated_cost_usd"] is None


@pytest.mark.integration
def test_an_unknown_cost_does_not_touch_either_ceiling(
    db: Session, study_clock: MutableClock
) -> None:
    """cost는 관측 항목이다. 한도를 만드는 것은 request / token 뿐이다.

    비용을 모른다는 사실이 생성을 멈추면 안 된다 --- token의 fail-closed 규칙은
    `daily_token_limit`의 것이고 cost로 번지지 않는다.
    """
    now = study_clock.now()
    job = _job(db, now=now)
    cfg = override_config(get_config(), llm={"daily_request_limit": 5, "daily_token_limit": 100})

    queue.record_usage(db, job=job, provider_calls=1, input_tokens=60, output_tokens=39, now=now)

    stored = _reload(db, job).result_ref
    assert stored is not None
    assert stored["usage"]["estimated_cost_usd"] is None
    assert queue.ceiling_reached(db, now=now, cfg=cfg) is False

    # 비용을 아는 호출이 끼어도 판정은 token / request로만 갈린다.
    queue.record_usage(
        db,
        job=job,
        provider_calls=1,
        input_tokens=0,
        output_tokens=1,
        now=now,
        estimated_cost_usd=0.002,
    )

    assert queue.ceiling_reached(db, now=now, cfg=cfg) is True
