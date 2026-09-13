"""후리가나 계산 지점과 실패 (ADR-021 결정 4, 12_TEST_PLAN.md `계산 지점과 실패`).

job -> worker(test double provider) -> 저장 -> materialization -> `/next`를 한 줄로 밟는다.
handler 단위 검사는 `test_jobs_persistence.py`에 있고, 여기서 보는 것은 경로다.

-   생성 job을 끝까지 돌리면 저장된 문장의 `ruby_json`이 채워지고 `/next`가 그 ruby를 싣는다.
-   `compute_ruby`가 던져도 문장은 `validated`, `ruby_json = NULL`이고 이어진 materialization이
    `ready` candidate를 만든다. `ruby.failed`가 남는다.
-   `EXPLAIN_ITEM`은 `ruby_json`을 바꾸지 않는다.
-   계산 전후로 원문과 span 행이 그대로다.
-   seed 적재·worker·backfill이 같은 입력에 같은 `spans`를 낸다(`test_backfill_ruby.py`와 함께).

fixture 규약은 `test_worker_pool_integration.py`와 같다(`committed_db`, 실제 `runner.run_job`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.furigana import RubyComputation, RubyItem
from app.jobs import observability, persistence, runner, worker
from app.llm.prompts import PROMPT_TEMPLATES
from app.models import (
    GenerationJob,
    Sentence,
    SentenceItem,
    SentenceItemSpan,
    UserSentenceCandidate,
)
from app.models.enums import CandidateStatus, JobType, LlmTaskType, SentenceStatus
from tests import factories
from tests.conftest import StudyApi, override_config
from tests.llm_fixtures import (
    batch_response,
    explanation_payload,
    item_payload,
    sentence_payload,
)
from tests.provider_double import RecordingProvider

pytestmark = pytest.mark.integration

# worker 회전 상한. 정책값이 아니라 무한 루프 대신 실패로 끝나게 하는 안전장치다.
MAX_TURNS = 8

# 明0 日1 は2 君3 に4 任5 せ6 る7 。8. tappable `任せる` = [5, 8), 설명 읽기 まかせる.
JAPANESE = "明日は君に任せる。"
SURFACE = "任せる"
EXPECTED_SPANS = [[0, 2, "あした"], [3, 4, "きみ"], [5, 6, "まか"]]


@pytest.fixture
def observer(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _cfg() -> AppConfig:
    return override_config(get_config())


def _activate(db: Session, task_type: LlmTaskType) -> None:
    for template in PROMPT_TEMPLATES.values():
        if template.task_type is task_type:
            factories.make_prompt_version(
                db, task_type=template.task_type, version=template.version
            )


def _drain(
    factory: sessionmaker[Session], *, provider: RecordingProvider, cfg: AppConfig, now: datetime
) -> None:
    for _ in range(MAX_TURNS):
        if not worker.run_once(
            session_factory=factory, provider=provider, run_job=runner.run_job, cfg=cfg, now=now
        ):
            return
    raise AssertionError(f"worker가 {MAX_TURNS}회전 안에 대기열을 비우지 않았다")


def _start(api: StudyApi) -> int:
    response = api.client.post("/api/study/session")
    assert response.status_code == 200, response.text
    return int(response.json()["session"]["session_id"])


def _next(api: StudyApi, session_id: int) -> dict[str, Any] | None:
    response = api.client.post(f"/api/study/session/{session_id}/next")
    assert response.status_code == 200, response.text
    shown = response.json()["presentation"]
    assert shown is None or isinstance(shown, dict)
    return shown


def _generated(db: Session) -> Sentence:
    db.expire_all()
    (sentence,) = db.execute(sa.select(Sentence)).scalars().all()
    return sentence


def _span_rows(db: Session, sentence_id: int) -> list[tuple[int, int, int]]:
    rows = db.execute(
        sa.select(
            SentenceItemSpan.start_codepoint,
            SentenceItemSpan.end_codepoint,
            SentenceItemSpan.span_order,
        )
        .join(SentenceItem, SentenceItem.id == SentenceItemSpan.sentence_item_id)
        .where(SentenceItem.sentence_id == sentence_id)
        .order_by(SentenceItemSpan.start_codepoint)
    ).all()
    return [(int(start), int(end), int(order)) for start, end, order in rows]


def _run_batch_job(api: StudyApi, factory: sessionmaker[Session], cfg: AppConfig) -> int:
    """빈 pool의 `/next`가 enqueue한 job을 worker가 test double 응답으로 끝까지 돌린다."""
    now = api.clock.now()
    with factory() as setup:
        factories.make_learning_item(setup, lemma=SURFACE)
        _activate(setup, LlmTaskType.GENERATE_SENTENCE_BATCH)
        setup.commit()

    session_id = _start(api)
    assert _next(api, session_id) is None
    response = batch_response(sentence_payload(JAPANESE, [item_payload("it0", SURFACE, JAPANESE)]))
    provider = RecordingProvider(responses=[response])
    _drain(factory, provider=provider, cfg=cfg, now=now)
    assert provider.call_count == 1
    return session_id


def test_a_generated_sentence_gets_ruby_that_next_presents(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    observer: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = _cfg()
    committed_api.use_config(cfg)

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        session_id = _run_batch_job(committed_api, committed_db, cfg)

    sentence = _generated(observer)
    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is not None
    assert sentence.ruby_json["spans"] == EXPECTED_SPANS
    # 원문과 span 행은 payload 그대로다. ruby는 옆 컬럼이다.
    assert sentence.japanese == JAPANESE
    assert _span_rows(observer, sentence.id) == [(5, 8, 0)]
    computed = [r for r in caplog.records if r.getMessage() == observability.RUBY_COMPUTED]
    assert [record.__dict__["sentence_id"] for record in computed] == [sentence.id]

    shown = _next(committed_api, session_id)

    assert shown is not None
    assert shown["sentence_id"] == sentence.id
    assert shown["render_segments"] == [
        {
            "text": "明日は君に",
            "sentence_item_id": None,
            "ruby": [
                {"text": "明日", "reading": "あした"},
                {"text": "は", "reading": None},
                {"text": "君", "reading": "きみ"},
                {"text": "に", "reading": None},
            ],
        },
        {
            "text": SURFACE,
            "sentence_item_id": shown["tappable_items"][0]["sentence_item_id"],
            "ruby": [{"text": "任", "reading": "まか"}, {"text": "せる", "reading": None}],
        },
        {"text": "。", "sentence_item_id": None, "ruby": []},
    ]


def test_a_failed_ruby_computation_does_not_block_ready(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    observer: Session,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg()
    committed_api.use_config(cfg)

    def broken(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> RubyComputation:
        raise RuntimeError("simulated ruby failure")

    monkeypatch.setattr(persistence, "compute_ruby", broken)

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        session_id = _run_batch_job(committed_api, committed_db, cfg)

    sentence = _generated(observer)
    assert sentence.status is SentenceStatus.VALIDATED
    assert sentence.ruby_json is None
    failed = [r for r in caplog.records if r.getMessage() == observability.RUBY_FAILED]
    assert [record.__dict__["sentence_id"] for record in failed] == [sentence.id]

    shown = _next(committed_api, session_id)

    assert shown is not None, "ruby 계산 실패가 ready를 막았다"
    assert shown["sentence_id"] == sentence.id
    assert all(segment["ruby"] == [] for segment in shown["render_segments"])
    candidate = observer.execute(sa.select(UserSentenceCandidate)).scalar_one()
    assert candidate.sentence_id == sentence.id
    # 제시되었으므로 shown이다. selection은 ready만 집는다.
    assert candidate.status is CandidateStatus.SHOWN


def test_explain_item_does_not_change_ruby(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    stored_ruby = {"spans": [[3, 4, "きみ"]], "marker": "unchanged"}
    with committed_db() as setup:
        item = factories.make_learning_item(setup, lemma=SURFACE)
        sentence = factories.make_sentence(setup, japanese="それは君に任せる。")
        sentence.ruby_json = stored_ruby
        sentence_item = factories.make_sentence_item(setup, sentence, item, surface_form=SURFACE)
        factories.make_span(setup, sentence_item, start=5, end=8)
        _activate(setup, LlmTaskType.EXPLAIN_ITEM)
        setup.commit()
        sentence_id = sentence.id

    session_id = _start(committed_api)
    assert _next(committed_api, session_id) is None
    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1
    observer.expire_all()
    (job,) = observer.execute(
        sa.select(GenerationJob).where(GenerationJob.job_type == JobType.EXPLAIN_ITEM)
    ).scalars()
    assert job.result_ref is not None
    reloaded = observer.get(Sentence, sentence_id)
    assert reloaded is not None
    assert reloaded.ruby_json == stored_ruby
    assert reloaded.japanese == "それは君に任せる。"
    assert _span_rows(observer, sentence_id) == [(5, 8, 0)]
