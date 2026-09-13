"""worker loop / cost guard / heartbeat / 로그 (09_BACKGROUND_JOBS.md, 11_OBSERVABILITY.md).

DB를 쓰는 테스트는 전부 `committed_db`다. worker는 회전마다 **여러 세션**을 열고 각자
커밋한다(heartbeat / claim / 결과). `db_session`은 커넥션 하나 안에서 끝나므로 그
분리를 재현할 수 없다.

provider는 인자로 주입한다. 이 파일에 `LLM_PROVIDER` / `LLM_API_KEY`를 세팅하는 코드가
없어야 한다 --- `stub`은 env 값이 아니라 provenance 값이다(ADR-016의 `개정`).
"""

from __future__ import annotations

import importlib.util
import logging
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Never

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import observability, worker
from app.llm.prompts import PROMPT_TEMPLATES
from app.llm.provider import LlmProvider, ProviderConfigError
from app.models import LearningItem
from app.models.enums import (
    CandidateStatus,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
    PresentationRole,
)
from app.models.jobs import GenerationJob, WorkerHeartbeat
from app.services.heartbeat import DEFAULT_WORKER_NAME
from tests import factories
from tests.clock import MutableClock
from tests.conftest import StudyApi, override_config
from tests.provider_double import RecordingProvider

_KEY_SEQUENCE = iter(range(1, 10_000))

ROLLED_BACK_LEMMA = "롤백되어야-한다"

# 로그 검사는 **우리 로거만** 본다. caplog가 root 레벨을 낮추면 SQLAlchemy가 SQL과
# bind parameter를 함께 뱉고(그 안에는 방금 저장한 last_error가 있다), 검사 대상이
# "애플리케이션이 무엇을 남기는가"에서 "서드파티 echo가 켜졌는가"로 바뀐다.
OUR_LOGGER = "app.jobs"


# --------------------------------------------------------------------------
# double
# --------------------------------------------------------------------------


@dataclass
class FakeRunner:
    """`app/jobs/runner.py`의 자리. worker가 무엇을 하는지만 보기 위한 double이다.

    실제 runner의 계약(`worker.JobRunner`)을 그대로 만족한다: 결과를 DB에 적고 최종
    상태를 돌려주며, 예외를 던지면 worker가 그것을 재시도 가능한 실패로 처리한다.
    """

    status: GenerationJobStatus = GenerationJobStatus.COMPLETED
    error: Exception | None = None
    result_ref: dict[str, Any] | None = None
    before_raise: Callable[[Session], None] | None = None
    after_call: Callable[[], None] | None = None
    calls: list[int] = field(default_factory=list)

    def __call__(
        self,
        db: Session,
        *,
        job: GenerationJob,
        provider: LlmProvider,
        now: datetime,
        cfg: AppConfig,
    ) -> GenerationJobStatus:
        self.calls.append(job.id)
        if self.error is not None:
            if self.before_raise is not None:
                self.before_raise(db)
            raise self.error
        job.status = self.status
        job.finished_at = now
        if self.result_ref is not None:
            job.result_ref = dict(self.result_ref)
        db.commit()
        if self.after_call is not None:
            self.after_call()
        return self.status


# --------------------------------------------------------------------------
# 공통
# --------------------------------------------------------------------------


def _cfg(**sections: dict[str, Any]) -> AppConfig:
    return override_config(get_config(), **sections)


def _activate_prompt_versions(db: Session) -> None:
    for template in PROMPT_TEMPLATES.values():
        factories.make_prompt_version(db, task_type=template.task_type, version=template.version)


def _queued_job(
    db: Session, *, now: datetime, payload: dict[str, Any] | None = None
) -> GenerationJob:
    job = GenerationJob(
        job_type=JobType.GENERATE_SENTENCE_BATCH,
        status=GenerationJobStatus.QUEUED,
        payload_json=payload or {},
        idempotency_key=f"worker-test:{next(_KEY_SEQUENCE)}",
        retry_count=0,
        max_attempts=3,
        next_attempt_at=now,
        created_at=now,
    )
    db.add(job)
    db.flush()
    return job


def _spent_job(
    db: Session, *, now: datetime, provider_calls: int, tokens: int | None
) -> GenerationJob:
    """오늘 이미 쓴 usage를 들고 있는 job (`result_ref.usage`).

    `tokens=None`은 provider가 usage를 주지 않은 호출이다. 0이 아니다.
    """
    job = _queued_job(db, now=now)
    job.status = GenerationJobStatus.COMPLETED
    job.result_ref = {
        "usage": {
            "provider_calls": provider_calls,
            "input_tokens": tokens,
            "output_tokens": 0,
            "estimated_cost_usd": None,
            "last_call_at": now.astimezone(UTC).isoformat(),
        }
    }
    db.flush()
    return job


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def provider() -> RecordingProvider:
    return RecordingProvider()


def _run_once(
    factory: sessionmaker[Session],
    *,
    provider: RecordingProvider,
    runner: FakeRunner,
    cfg: AppConfig,
    now: datetime,
    state: worker.LoopState | None = None,
) -> bool:
    return worker.run_once(
        session_factory=factory,
        provider=provider,
        run_job=runner,
        cfg=cfg,
        now=now,
        state=state,
    )


def _statuses(factory: sessionmaker[Session]) -> list[tuple[GenerationJobStatus, int, str | None]]:
    with factory() as db:
        return [
            (job.status, job.retry_count, job.last_error)
            for job in db.scalars(sa.select(GenerationJob).order_by(GenerationJob.id)).all()
        ]


def _heartbeat(factory: sessionmaker[Session]) -> datetime | None:
    with factory() as db:
        latest: datetime | None = db.scalar(
            sa.select(sa.func.max(WorkerHeartbeat.last_heartbeat_at))
        )
        return latest


def _records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.message == event]


def _one(caplog: pytest.LogCaptureFixture, event: str) -> dict[str, Any]:
    """그 event 하나의 구조화 field. `extra=`로 붙인 값은 LogRecord 속성으로 들어온다."""
    matching = _records(caplog, event)
    assert len(matching) == 1, [record.message for record in caplog.records]
    return dict(matching[0].__dict__)


def _never_sleep(seconds: float) -> None:
    raise AssertionError(f"idle sleep은 일어나지 않아야 한다 (요청값 {seconds})")


@contextmanager
def _restored_signal_handlers() -> Iterator[None]:
    """테스트가 설치한 SIGTERM/SIGINT 핸들러를 원래대로 돌려놓는다."""
    numbers = (signal.SIGTERM, signal.SIGINT)
    previous = {number: signal.getsignal(number) for number in numbers}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


# --------------------------------------------------------------------------
# cost guard 기동 경고 (DB 없음)
# --------------------------------------------------------------------------


def test_a_configured_key_with_a_disabled_ceiling_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """과금되는 키가 꽂혔는데 한도가 꺼져 있으면 운영자가 그 사실을 알아야 한다."""
    cfg = _cfg(llm={"daily_request_limit": None, "daily_token_limit": None})
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        worker.warn_if_cost_guard_disabled(cfg, api_key_configured=True)

    assert len(_records(caplog, observability.COST_GUARD_DISABLED)) == 1
    warning = _one(caplog, observability.COST_GUARD_DISABLED)
    assert warning["disabled_limits"] == ["daily_request_limit", "daily_token_limit"]


def test_no_warning_when_both_limits_are_configured(caplog: pytest.LogCaptureFixture) -> None:
    cfg = _cfg(llm={"daily_request_limit": 10, "daily_token_limit": 1000})
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        worker.warn_if_cost_guard_disabled(cfg, api_key_configured=True)
    assert caplog.records == []


def test_no_warning_without_an_api_key(caplog: pytest.LogCaptureFixture) -> None:
    """test double 주입 경로에는 청구서가 없다. 여기서 경고하면 모든 테스트가 시끄러워진다."""
    cfg = _cfg(llm={"daily_request_limit": None, "daily_token_limit": None})
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        worker.warn_if_cost_guard_disabled(cfg, api_key_configured=False)
    assert caplog.records == []


# --------------------------------------------------------------------------
# describe_error
# --------------------------------------------------------------------------


def test_last_error_is_capped_and_single_line() -> None:
    described = observability.describe_error(ValueError("x" * 5000 + "\nsecond line"))
    assert described.startswith("ValueError: ")
    assert len(described) <= observability.MAX_ERROR_LENGTH
    assert "\n" not in described


def test_describe_error_keeps_the_type_when_there_is_no_message() -> None:
    assert observability.describe_error(RuntimeError()) == "RuntimeError"


# `describe_error`의 결과는 `generation_jobs.last_error`로 들어가고 그 행은 정기
# `pg_dump`를 타고 다른 물리 디스크의 백업 매체까지 복제된다
# (04_SECURITY_AND_DATA.md의 `Backup`). 그래서 이 자리는 길이만 막아서는 안 된다 ---
# SDK나 중간 proxy(사내 gateway, LiteLLM류 base_url)가 예외 메시지에 무엇을 넣든
# 그대로 DB에 적히는 seam이다.
FAKE_KEY = "sk-proj-ZZZLEAKCANARYZZZ0123456789"


def test_describe_error_redacts_key_shaped_tokens() -> None:
    described = observability.describe_error(
        RuntimeError(f"401 Unauthorized for key {FAKE_KEY} body={{'input': '秘密です'}}")
    )

    assert FAKE_KEY not in described
    assert "ZZZLEAKCANARY" not in described
    assert "sk-" not in described
    assert "[redacted]" in described
    # 지우는 것은 키뿐이다. 무엇이 실패했는지는 남아야 운영자가 읽을 수 있다.
    assert described.startswith("RuntimeError: 401 Unauthorized for key [redacted]")


def test_describe_error_redacts_before_it_truncates() -> None:
    """상한 컷이 키 **안에서** 떨어지게 만든다.

    자른 뒤에 지우면 남는 앞 조각(`sk-p`)은 키 패턴의 최소 길이에 못 미쳐 마스킹을
    빠져나가고 그대로 `last_error`에 적힌다. 그래서 순서가 정책이다.
    """
    cut = observability.MAX_ERROR_LENGTH - 1
    head = "h" * (cut - len("ValueError: ") - 4)  # 키가 컷 4글자 전에 시작한다
    described = observability.describe_error(ValueError(f"{head}{FAKE_KEY} trailing detail"))

    assert len(described) <= observability.MAX_ERROR_LENGTH
    assert "sk-" not in described
    assert "ZZZLEAKCANARY" not in described


def test_redaction_preserves_the_classification_prefix() -> None:
    """마스킹이 앞의 분류 리터럴을 건드리면 로그의 `error_type`이 조용히 `unknown`이 된다.

    worker는 `last_error.split(":", 1)[0]`로 분류한다(`_error_category`). runner가
    만드는 문자열 모양 그대로 확인한다.
    """
    last_error = f"provider call failed: {observability.describe_error(RuntimeError(FAKE_KEY))}"

    assert worker._error_category(last_error) == "provider call failed"
    assert FAKE_KEY not in last_error


# --------------------------------------------------------------------------
# loop
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_run_once_runs_one_claimed_job(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    with committed_db() as setup:
        job = _queued_job(setup, now=clock.now())
        setup.commit()
        job_id = job.id

    runner = FakeRunner(result_ref={"sentence_ids": [1, 2]})
    handled = _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    assert handled is True
    assert runner.calls == [job_id]
    assert _statuses(committed_db) == [(GenerationJobStatus.COMPLETED, 1, None)]


@pytest.mark.integration
def test_an_empty_queue_is_not_work(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    runner = FakeRunner()
    handled = _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())
    assert handled is False
    assert runner.calls == []


@pytest.mark.integration
def test_the_completed_log_carries_the_result_counts(
    committed_db: sessionmaker[Session],
    clock: MutableClock,
    provider: RecordingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """11_OBSERVABILITY.md의 job count / validation failure는 `result_ref`에서 온다."""
    with committed_db() as setup:
        _queued_job(setup, now=clock.now())
        setup.commit()

    runner = FakeRunner(result_ref={"sentence_ids": [1, 2, 3], "rejected": [{"reason": "dup"}]})
    with caplog.at_level(logging.INFO, logger=OUR_LOGGER):
        _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    claimed = _one(caplog, observability.JOB_CLAIMED)
    completed = _one(caplog, observability.JOB_COMPLETED)
    assert claimed["job_type"] == JobType.GENERATE_SENTENCE_BATCH.value
    assert claimed["retry_count"] == 1
    assert completed["sentences_persisted"] == 3
    assert completed["validation_failures"] == 1
    assert completed["duration_ms"] >= 0


@pytest.mark.integration
def test_the_ready_pool_size_is_logged_after_a_batch_job(
    committed_db: sessionmaker[Session],
    clock: MutableClock,
    provider: RecordingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with committed_db() as setup:
        user = factories.make_user(setup)
        item = factories.make_learning_item(setup)
        sentence = factories.make_ready_sentence(setup, [item])
        factories.make_candidate(
            setup,
            user,
            sentence,
            status=CandidateStatus.READY,
            presentation_role=PresentationRole.NEW,
        )
        _queued_job(
            setup,
            now=clock.now(),
            payload={"user_id": user.id, "presentation_role": PresentationRole.NEW.value},
        )
        setup.commit()
        user_id = user.id

    with caplog.at_level(logging.INFO, logger=OUR_LOGGER):
        _run_once(committed_db, provider=provider, runner=FakeRunner(), cfg=_cfg(), now=clock.now())

    pool = _one(caplog, observability.POOL_READY_SIZE)
    assert (pool["user_id"], pool["role"], pool["size"]) == (
        user_id,
        PresentationRole.NEW.value,
        1,
    )


# --------------------------------------------------------------------------
# cost guard: claim 직전 판정
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_ceiling_stops_the_claim_without_burning_an_attempt(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """한도에 걸린 job은 `queued`로 남는다. `failed`로 만들면 다음 날 살아 있어야 할 job이 죽는다."""
    with committed_db() as setup:
        _spent_job(setup, now=clock.now(), provider_calls=5, tokens=10)
        _queued_job(setup, now=clock.now())
        setup.commit()

    runner = FakeRunner()
    cfg = _cfg(llm={"daily_request_limit": 5, "daily_token_limit": None})
    handled = _run_once(committed_db, provider=provider, runner=runner, cfg=cfg, now=clock.now())

    assert handled is False
    assert runner.calls == []
    assert provider.calls == []
    assert _statuses(committed_db)[1] == (GenerationJobStatus.QUEUED, 0, None)


@pytest.mark.integration
def test_the_token_ceiling_uses_the_sum_of_input_and_output(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    with committed_db() as setup:
        _spent_job(setup, now=clock.now(), provider_calls=1, tokens=100)
        _queued_job(setup, now=clock.now())
        setup.commit()

    runner = FakeRunner()
    cfg = _cfg(llm={"daily_request_limit": None, "daily_token_limit": 100})
    handled = _run_once(committed_db, provider=provider, runner=runner, cfg=cfg, now=clock.now())

    assert handled is False
    assert runner.calls == []


@pytest.mark.integration
def test_an_unmeasurable_token_total_stops_the_claim_and_says_why(
    committed_db: sessionmaker[Session],
    clock: MutableClock,
    provider: RecordingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """token을 셀 수 없으면 `daily_token_limit`을 지킬 수 없다. 하한과 비교하지 않는다.

    한도에 한참 못 미치는 값으로도 멈추므로 그 이유가 로그에 있어야 한다. 멈춘 job은
    `queued`로 남고(attempt를 쓰지 않는다) 학습 세션은 Ready Pool로 계속 돈다.
    """
    with committed_db() as setup:
        _spent_job(setup, now=clock.now(), provider_calls=1, tokens=None)
        _queued_job(setup, now=clock.now())
        setup.commit()

    cfg = _cfg(llm={"daily_request_limit": None, "daily_token_limit": 1_000_000})
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        handled = _run_once(
            committed_db, provider=provider, runner=FakeRunner(), cfg=cfg, now=clock.now()
        )

    assert handled is False
    assert provider.calls == []
    ceiling = _one(caplog, observability.COST_CEILING_REACHED)
    assert ceiling["jobs_with_unknown_tokens"] == 1
    assert ceiling["input_tokens"] == 0  # 아는 부분만. 총량이 아니다.
    assert _statuses(committed_db)[1] == (GenerationJobStatus.QUEUED, 0, None)


@pytest.mark.integration
def test_null_limits_mean_disabled_not_zero(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """`null = limit disabled`다 (14_CONFIGURATION.md). 사용량이 아무리 많아도 막지 않는다."""
    with committed_db() as setup:
        _spent_job(setup, now=clock.now(), provider_calls=10_000, tokens=10_000_000)
        _queued_job(setup, now=clock.now())
        setup.commit()

    cfg = _cfg(llm={"daily_request_limit": None, "daily_token_limit": None})
    handled = _run_once(
        committed_db, provider=provider, runner=FakeRunner(), cfg=cfg, now=clock.now()
    )
    assert handled is True


@pytest.mark.integration
def test_yesterdays_usage_does_not_block_today(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """일 경계는 UTC다 (09_BACKGROUND_JOBS.md)."""
    with committed_db() as setup:
        _spent_job(setup, now=clock.now() - timedelta(days=1), provider_calls=99, tokens=0)
        _queued_job(setup, now=clock.now())
        setup.commit()

    cfg = _cfg(llm={"daily_request_limit": 5, "daily_token_limit": None})
    handled = _run_once(
        committed_db, provider=provider, runner=FakeRunner(), cfg=cfg, now=clock.now()
    )
    assert handled is True


@pytest.mark.integration
def test_the_ceiling_warning_is_logged_once_per_episode(
    committed_db: sessionmaker[Session],
    clock: MutableClock,
    provider: RecordingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """한도는 UTC 자정까지 이어진다. 매 poll마다 같은 경고를 쓰면 디스크만 찬다."""
    with committed_db() as setup:
        _spent_job(setup, now=clock.now(), provider_calls=5, tokens=0)
        setup.commit()

    cfg = _cfg(llm={"daily_request_limit": 1, "daily_token_limit": None})
    state = worker.LoopState()
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        for _ in range(3):
            _run_once(
                committed_db,
                provider=provider,
                runner=FakeRunner(),
                cfg=cfg,
                now=clock.now(),
                state=state,
            )

    assert len(_records(caplog, observability.COST_CEILING_REACHED)) == 1
    assert _one(caplog, observability.COST_CEILING_REACHED)["provider_calls"] == 5


@pytest.mark.integration
def test_a_study_session_keeps_running_while_the_ceiling_is_reached(
    committed_api: StudyApi, committed_db: sessionmaker[Session], provider: RecordingProvider
) -> None:
    """생성이 멈춰도 학습은 멈추지 않는다. request 경로는 애초에 provider를 부르지 않는다.

    **강한 검증은 `test_worker_pool_integration.py`의
    `test_the_session_keeps_serving_while_the_ceiling_blocks_the_claim`에 있다.** 그쪽은
    실물 `runner.run_job`을 넣고 candidate를 materialization이 만들게 하며, 막힌 job이
    `queued`로 남고 `retry_count`가 늘지 않는 것까지 단정한다. 여기는 worker loop 단위의
    빠른 판이고(`FakeRunner` + 손으로 넣은 candidate) 둘은 같은 규칙을 본다 --- 규칙이
    바뀌면 **두 곳을 함께** 고친다. 한쪽만 고치면 다른 쪽이 옛 규칙을 계속 통과시킨다.
    """
    now = committed_api.clock.now()
    with committed_db() as setup:
        item = factories.make_learning_item(setup)
        sentence = factories.make_ready_sentence(setup, [item])
        candidate = factories.make_candidate(
            setup,
            committed_api.user,
            sentence,
            status=CandidateStatus.READY,
            presentation_role=PresentationRole.NEW,
        )
        factories.make_candidate_target(setup, candidate, item)
        _spent_job(setup, now=now, provider_calls=9, tokens=0)
        _queued_job(setup, now=now)
        setup.commit()

    cfg = _cfg(llm={"daily_request_limit": 1, "daily_token_limit": None})
    handled = _run_once(committed_db, provider=provider, runner=FakeRunner(), cfg=cfg, now=now)
    assert handled is False

    started = committed_api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]
    presented = committed_api.client.post(f"/api/study/session/{session_id}/next")

    assert presented.status_code == 200, presented.text
    assert presented.json()["presentation"] is not None
    assert provider.calls == []


# --------------------------------------------------------------------------
# heartbeat
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_heartbeat_is_written_even_when_there_is_no_job(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """이 신호의 뜻은 일이 있었다가 아니라 worker가 살아 있다이다 (ADR-017)."""
    _run_once(committed_db, provider=provider, runner=FakeRunner(), cfg=_cfg(), now=clock.now())

    assert _heartbeat(committed_db) == clock.now()
    with committed_db() as db:
        names = list(db.scalars(sa.select(WorkerHeartbeat.worker_name)).all())
    assert names == [DEFAULT_WORKER_NAME]


@pytest.mark.integration
def test_the_heartbeat_is_upserted_not_appended(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    for _ in range(3):
        _run_once(committed_db, provider=provider, runner=FakeRunner(), cfg=_cfg(), now=clock.now())
        clock.advance(timedelta(seconds=30))

    with committed_db() as db:
        rows = list(db.scalars(sa.select(WorkerHeartbeat)).all())
    assert len(rows) == 1
    assert rows[0].last_heartbeat_at == clock.now() - timedelta(seconds=30)


@pytest.mark.integration
def test_the_heartbeat_survives_a_rolled_back_job(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """job 트랜잭션에 얹으면 rollback이 생존 신호까지 지운다."""
    with committed_db() as setup:
        _queued_job(setup, now=clock.now())
        setup.commit()

    def _dirty(db: Session) -> None:
        factories.make_learning_item(db, lemma=ROLLED_BACK_LEMMA)

    runner = FakeRunner(error=RuntimeError("boom"), before_raise=_dirty)
    handled = _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    assert handled is True
    assert _heartbeat(committed_db) == clock.now()
    with committed_db() as db:
        leaked = list(
            db.scalars(sa.select(LearningItem).where(LearningItem.lemma == ROLLED_BACK_LEMMA)).all()
        )
    assert leaked == []


@pytest.mark.integration
def test_an_escaping_runner_exception_becomes_a_retryable_failure(
    committed_db: sessionmaker[Session],
    clock: MutableClock,
    provider: RecordingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with committed_db() as setup:
        _queued_job(setup, now=clock.now())
        setup.commit()

    runner = FakeRunner(error=RuntimeError("x" * 5000))
    with caplog.at_level(logging.WARNING, logger=OUR_LOGGER):
        _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    status, retry_count, last_error = _statuses(committed_db)[0]
    assert status is GenerationJobStatus.RETRY
    assert retry_count == 1
    assert last_error is not None
    assert last_error.startswith("RuntimeError: ")
    assert len(last_error) <= observability.MAX_ERROR_LENGTH

    failed = _one(caplog, observability.JOB_FAILED)
    assert failed["error_type"] == "RuntimeError"
    assert failed["next_status"] == GenerationJobStatus.RETRY.value


@pytest.mark.integration
def test_a_runner_reported_outcome_is_not_overwritten(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    """runner가 `dead_letter`로 끝낸 job을 worker가 `retry`로 되살리지 않는다."""
    with committed_db() as setup:
        _queued_job(setup, now=clock.now())
        setup.commit()

    runner = FakeRunner(status=GenerationJobStatus.DEAD_LETTER)
    _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    assert _statuses(committed_db)[0][0] is GenerationJobStatus.DEAD_LETTER


# --------------------------------------------------------------------------
# 기동과 종료
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_worker_refuses_to_start_without_active_prompt_versions(
    committed_db: sessionmaker[Session], provider: RecordingProvider
) -> None:
    """조용히 도는 worker보다 즉시 실패가 낫다 --- 그 상태로는 모든 job이 dead_letter다."""
    with pytest.raises(worker.WorkerStartupError) as raised:
        worker.run_worker(
            session_factory=committed_db,
            provider=provider,
            run_job=FakeRunner(),
            cfg=_cfg(),
            sleep=_never_sleep,
        )
    for task in LlmTaskType:
        assert task.value in str(raised.value)


@pytest.mark.integration
def test_the_loop_stops_after_sigterm_and_finishes_the_current_job(
    committed_db: sessionmaker[Session], clock: MutableClock, provider: RecordingProvider
) -> None:
    with committed_db() as setup:
        _activate_prompt_versions(setup)
        _queued_job(setup, now=clock.now())
        _queued_job(setup, now=clock.now())
        setup.commit()

    shutdown = worker.ShutdownSignal()
    runner = FakeRunner(after_call=lambda: signal.raise_signal(signal.SIGTERM))

    with _restored_signal_handlers():
        worker.install_signal_handlers(shutdown)
        worker.run_worker(
            session_factory=committed_db,
            provider=provider,
            run_job=runner,
            cfg=_cfg(),
            shutdown=shutdown,
            sleep=_never_sleep,
        )

    assert shutdown.requested is True
    # 첫 job은 끝났고 두 번째 job은 건드리지 않았다.
    assert len(runner.calls) == 1
    statuses = _statuses(committed_db)
    assert statuses[0][0] is GenerationJobStatus.COMPLETED
    assert statuses[1][0] is GenerationJobStatus.QUEUED


@pytest.mark.integration
def test_an_idle_loop_sleeps_the_smaller_of_poll_and_heartbeat_interval(
    committed_db: sessionmaker[Session], provider: RecordingProvider
) -> None:
    """poll 간격을 heartbeat 간격보다 크게 잡아도 생존 신호가 stale 임계를 넘지 않아야 한다."""
    with committed_db() as setup:
        _activate_prompt_versions(setup)
        setup.commit()

    cfg = _cfg(
        jobs={
            "poll_interval_seconds": 600,
            "heartbeat_interval_seconds": 30,
            "heartbeat_stale_seconds": 120,
        }
    )
    shutdown = worker.ShutdownSignal()
    slept: list[float] = []

    def _sleep(seconds: float) -> None:
        slept.append(seconds)
        shutdown.request()

    worker.run_worker(
        session_factory=committed_db,
        provider=provider,
        run_job=FakeRunner(),
        cfg=cfg,
        shutdown=shutdown,
        sleep=_sleep,
    )

    assert slept == [30]
    assert _heartbeat(committed_db) is not None


# --------------------------------------------------------------------------
# 로그 위생 (11_OBSERVABILITY.md: secret / auth token log 금지)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_logs_carry_no_key_no_prompt_and_no_provider_payload(
    committed_db: sessionmaker[Session], clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    api_key = "sk-test-DO-NOT-LOG"
    prompt = "너는 일본어 문장을 만든다"
    response = '{"sentences": [{"japanese": "秘密の応答本文"}]}'

    with committed_db() as setup:
        _queued_job(setup, now=clock.now())
        setup.commit()

    provider = RecordingProvider(responses=[response])
    runner = FakeRunner(
        error=RuntimeError(f"provider rejected key {api_key} for prompt {prompt}: {response}")
    )
    with caplog.at_level(logging.INFO, logger=OUR_LOGGER):
        _run_once(committed_db, provider=provider, runner=runner, cfg=_cfg(), now=clock.now())

    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert logged
    for secret in (api_key, prompt, "秘密の応答本文"):
        assert secret not in logged, secret


# --------------------------------------------------------------------------
# 진입점 (scripts/run_worker.py)
#
# 환경변수를 읽는 유일한 지점이다. 스크립트는 backend/ 밖에 있어 평소 import 경로에
# 없으므로 파일 경로로 직접 적재한다(test_auth_cli.py와 같은 방식).
# --------------------------------------------------------------------------

RUN_WORKER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_worker.py"


def _load_run_worker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_worker", RUN_WORKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "environment",
    [
        pytest.param({}, id="unset"),
        pytest.param({"LLM_PROVIDER": ""}, id="empty"),
        pytest.param({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k"}, id="unknown-provider"),
        pytest.param({"LLM_PROVIDER": "stub", "LLM_API_KEY": "k"}, id="stub-is-not-an-env-value"),
        pytest.param({"LLM_PROVIDER": "openai"}, id="openai-without-a-key"),
    ],
)
def test_the_entrypoint_fails_closed(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    """어느 쪽도 조용히 다른 값으로 승격시키지 않는다 (04_SECURITY_AND_DATA.md)."""
    for name in ("LLM_PROVIDER", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    module = _load_run_worker()
    with pytest.raises(ProviderConfigError):
        module.main()


def test_the_entrypoint_fails_closed_when_the_analyzer_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """분석기 부재는 배포 결함이다. 문장별 NULL로 흡수하지 않고 worker가 뜨지 않는다(ADR-021)."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    module = _load_run_worker()

    def missing() -> Never:
        raise ModuleNotFoundError("No module named 'sudachidict_core'")

    def must_not_start(**kwargs: object) -> Never:
        raise AssertionError("분석기 없이 worker loop가 시작됐다")

    monkeypatch.setattr(module, "load_analyzer", missing)
    monkeypatch.setattr(module, "run_worker", must_not_start)

    with pytest.raises(ModuleNotFoundError, match="sudachidict_core"):
        module.main()


def test_the_entrypoint_loads_the_analyzer_before_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    module = _load_run_worker()
    calls: list[str] = []

    monkeypatch.setattr(module, "load_analyzer", lambda: calls.append("load_analyzer"))
    monkeypatch.setattr(module, "run_worker", lambda **kwargs: calls.append("run_worker"))
    # 테스트 프로세스의 signal handler를 바꾸지 않는다.
    monkeypatch.setattr(module, "install_signal_handlers", lambda shutdown: None)

    assert module.main() == 0
    assert calls == ["load_analyzer", "run_worker"]


def test_the_entrypoint_renders_structured_fields() -> None:
    """`extra=`로 붙인 값이 실제로 출력되어야 한다. 기본 formatter는 그것을 버린다."""
    module = _load_run_worker()
    record = logging.LogRecord(OUR_LOGGER, logging.INFO, __file__, 1, "job.claimed", None, None)
    record.job_id = 7

    rendered = module.KeyValueFormatter("%(message)s").format(record)

    assert rendered == "job.claimed job_id=7"
