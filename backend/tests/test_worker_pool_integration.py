"""job -> worker -> pool 한 줄 (Wave 3 완료 기준, `12_TEST_PLAN.md`의 `job↔worker↔pool`).

여기서 보는 것은 handler 하나의 동작이 아니라 **경로가 이어져 있는가**다.

``` text
request 경로   enqueue만 한다 (provider 호출 0)        불변식 #1
worker         claim -> provider(test double) -> 저장
다음 요청      materialization이 그 콘텐츠로 candidate를 만들고 /next가 제시한다
```

마지막 줄이 끊어져 있으면 handler는 있어도 학습자에게는 아무 일도 일어나지 않는다.
handler 단위 검사는 `test_jobs_generate_sentence_batch.py` / `test_jobs_review_context.py`
/ `test_jobs_explain_item.py`가 하고, 이 파일은 **HTTP 요청과 worker를 번갈아** 밟는다.

## fixture 규약

-   `committed_db` / `committed_api`를 쓴다. worker는 회전마다 여러 세션을 열고 각자
    커밋하므로 커넥션 하나로 끝나는 `db_session`으로는 그 분리를 재현할 수 없다.
    `committed_db`는 **실제 커밋을 남기고 teardown의 TRUNCATE로만 치운다** --- 그래서
    이 파일은 세션 스코프 데이터를 만들지 않고 필요한 것을 테스트마다 만든다.
-   provider는 `worker.run_once(provider=...)`에 **인자로** 주입한다.
    `LLM_PROVIDER`를 세팅하지 않는다 --- `stub`은 env 값이 아니라 provenance 값이고
    (ADR-016의 `개정`), `prompt_versions` 행의 `provider="stub"`가 그 자리다.
-   정책값은 `override_config`로 주입하고 API app에도 같은 값을 꽂는다. 숫자를
    테스트에 적지 않는다(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import runner, worker
from app.llm.prompts import PROMPT_TEMPLATES
from app.llm.prompts import explain_item as explain_item_prompt
from app.models import (
    GenerationJob,
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
    UserSentenceCandidate,
)
from app.models.enums import (
    CandidateStatus,
    ContextStage,
    ExplanationStatus,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
    PresentationRole,
    ReviewReason,
    SentenceStatus,
)
from app.models.user import User
from app.normalization import normalized_sentence_hash, similarity_ratio
from tests import factories
from tests.conftest import StudyApi, override_config
from tests.llm_fixtures import batch_response, explanation_payload, item_payload, sentence_payload
from tests.provider_double import RecordingProvider

pytestmark = pytest.mark.integration

# worker 회전 상한. 정책값이 아니라 무한 루프 대신 실패로 끝나게 하는 안전장치다.
MAX_TURNS = 8

# `factories.make_review_state`가 요구하는 FSRS 채움값. 이 파일은 FSRS 산술을 보지
# 않는다(그쪽은 test_srs_review.py / test_scenarios.py).
FSRS_STATE_FILLER = 1
FSRS_PARAMS_VERSION_FILLER = "test"


# --------------------------------------------------------------------------
# 공통
# --------------------------------------------------------------------------


@pytest.fixture
def observer(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    """worker/API와 **다른 커넥션**에서 커밋된 결과만 읽는 세션."""
    with committed_db() as session:
        yield session


def _cfg(**sections: dict[str, Any]) -> AppConfig:
    return override_config(get_config(), **sections)


def _activate_prompt_versions(db: Session, *task_types: LlmTaskType) -> None:
    """`prompt_versions`의 active 행. version은 코드에 본문이 있는 값이어야 한다.

    `provider="stub"`은 factory 기본값이며 **test double이 만든 콘텐츠**라는
    provenance다(ADR-016의 `개정`).
    """
    for template in PROMPT_TEMPLATES.values():
        if task_types and template.task_type not in task_types:
            continue
        factories.make_prompt_version(db, task_type=template.task_type, version=template.version)


def _jobs(db: Session, *, job_type: JobType | None = None) -> list[GenerationJob]:
    statement = sa.select(GenerationJob).order_by(GenerationJob.id)
    if job_type is not None:
        statement = statement.where(GenerationJob.job_type == job_type)
    db.expire_all()
    return list(db.execute(statement).scalars().all())


def _sentences(db: Session, *, source: str | None = None) -> list[Sentence]:
    db.expire_all()
    rows = list(db.execute(sa.select(Sentence).order_by(Sentence.id)).scalars().all())
    if source is None:
        return rows
    return [row for row in rows if row.source_type.value == source]


def _count(db: Session, model: type[Any]) -> int:
    db.expire_all()
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())


def _drain(
    factory: sessionmaker[Session],
    *,
    provider: RecordingProvider,
    cfg: AppConfig,
    now: datetime,
) -> int:
    """더 집을 job이 없을 때까지 worker를 돌리고 처리한 job 수를 돌려준다.

    **실제 `runner.run_job`을 넣는다.** FakeRunner를 쓰면 claim과 loop만 검사하게
    되고, 이 파일의 주제인 "job이 콘텐츠가 되어 pool로 돌아온다"가 빠진다.
    """
    for handled in range(MAX_TURNS):
        if not worker.run_once(
            session_factory=factory,
            provider=provider,
            run_job=runner.run_job,
            cfg=cfg,
            now=now,
        ):
            return handled
    raise AssertionError(f"worker가 {MAX_TURNS}회전 안에 대기열을 비우지 않았다")


def _start(api: StudyApi) -> int:
    response = api.client.post("/api/study/session")
    assert response.status_code == 200, response.text
    session_id = response.json()["session"]["session_id"]
    assert isinstance(session_id, int)
    return session_id


def _next(api: StudyApi, session_id: int) -> dict[str, Any] | None:
    response = api.client.post(f"/api/study/session/{session_id}/next")
    assert response.status_code == 200, response.text
    shown = response.json()["presentation"]
    if shown is None:
        return None
    assert isinstance(shown, dict)
    return shown


def _complete(api: StudyApi, presentation_id: int) -> None:
    response = api.client.post(f"/api/study/presentations/{presentation_id}/complete")
    assert response.status_code == 200, response.text


def _flag(api: StudyApi, presentation_id: int, *, reason: str = "unnatural") -> None:
    response = api.client.post(
        f"/api/study/presentations/{presentation_id}/flag",
        json={"client_event_id": str(uuid.uuid4()), "reason": reason},
    )
    assert response.status_code == 204, response.text


def _batch_of(japanese: str, *, surface: str) -> str:
    return batch_response(sentence_payload(japanese, [item_payload("it0", surface, japanese)]))


def _spent_call(
    db: Session, *, now: datetime, provider_calls: int, cfg: AppConfig
) -> GenerationJob:
    """오늘 이미 쓴 provider 호출을 들고 있는 completed job (`result_ref.usage`).

    ceiling 판정의 입력은 이 컬럼이다(`09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`).
    """
    job = factories.make_generation_job(
        db,
        idempotency_key=f"spent:{uuid.uuid4()}",
        max_attempts=cfg.jobs.max_job_attempts,
    )
    job.status = GenerationJobStatus.COMPLETED
    job.result_ref = {
        "usage": {
            "provider_calls": provider_calls,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": None,
            "last_call_at": now.isoformat(),
        }
    }
    db.flush()
    return job


def _queued_batch_job(db: Session, *, user: User, role: PresentationRole, cfg: AppConfig) -> None:
    """worker가 집어갈 `GENERATE_SENTENCE_BATCH` 하나.

    request 경로로 만들지 않는 이유는 ceiling 테스트가 "job이 있는데도 claim하지
    않는다"를 봐야 하기 때문이다 --- 빈 pool을 만들면 그 사용자에게 보여줄 문장이
    없어지고, 그러면 "세션이 계속 돈다"를 확인할 수 없다.
    """
    job = factories.make_generation_job(
        db, idempotency_key=f"ceiling:{uuid.uuid4()}", max_attempts=cfg.jobs.max_job_attempts
    )
    job.payload_json = {"user_id": user.id, "presentation_role": role.value}
    db.flush()


# --------------------------------------------------------------------------
# GENERATE_SENTENCE_BATCH: 빈 pool -> job -> worker -> 제시
# --------------------------------------------------------------------------


def test_the_enqueued_batch_job_becomes_the_next_presented_sentence(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """Wave 3 완료 기준의 절반. enqueue -> worker -> **다음 `/next`가 그 문장을 제시한다.**

    `12_TEST_PLAN.md`: "test double provider를 worker loop에 주입해
    `GENERATE_SENTENCE_BATCH` job을 끝까지 실행하면 `sentences` / `sentence_items` /
    `sentence_item_spans` / `sentence_item_explanations`가 만들어지고, 이어진
    materialization이 그 문장으로 `status = ready` candidate를 만든다."

    candidate를 손으로 INSERT하지 않는다. 이 테스트에서 `user_sentence_candidates`에
    행을 만드는 유일한 주체는 materialization이다.
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    with committed_db() as setup:
        item = factories.make_learning_item(setup, lemma="仕方ない")
        _activate_prompt_versions(setup, LlmTaskType.GENERATE_SENTENCE_BATCH)
        setup.commit()
        item_id = item.id

    session_id = _start(committed_api)
    assert _next(committed_api, session_id) is None, "문장이 없는데 무언가를 제시했다"

    queued = _jobs(observer)
    assert [job.job_type for job in queued] == [JobType.GENERATE_SENTENCE_BATCH] * len(
        PresentationRole
    )
    assert all(job.status is GenerationJobStatus.QUEUED for job in queued)
    assert _count(observer, UserSentenceCandidate) == 0

    japanese = "それは仕方ないと思う。"
    provider = RecordingProvider(responses=[_batch_of(japanese, surface="仕方ない")])
    handled = _drain(committed_db, provider=provider, cfg=cfg, now=now)

    # role마다 job이 있지만 대상 item이 있는 role은 하나다(나머지는 대상 0건이므로
    # provider를 부르지 않고 completed다). 그래서 호출은 정확히 1회다.
    assert handled == len(PresentationRole)
    assert provider.call_count == 1
    generated = _sentences(observer, source="generated")
    assert [row.japanese for row in generated] == [japanese]
    assert generated[0].status is SentenceStatus.VALIDATED
    assert _count(observer, SentenceItem) == 1
    assert _count(observer, SentenceItemSpan) == 1
    assert _count(observer, SentenceItemExplanation) == 1

    shown = _next(committed_api, session_id)

    assert shown is not None, "worker가 만든 문장이 pool로 돌아오지 않았다"
    assert shown["sentence_id"] == generated[0].id
    assert shown["japanese"] == japanese
    candidate = observer.execute(sa.select(UserSentenceCandidate)).scalar_one()
    assert candidate.sentence_id == generated[0].id
    assert candidate.user_id == committed_api.user.id
    # 제시된 candidate는 `shown`이다. 그 전 상태가 `ready`였다는 것은 selection이
    # ready만 집는다는 규칙과 함께 이 한 줄로 고정된다.
    assert candidate.status is CandidateStatus.SHOWN
    assert observer.get(LearningItem, item_id) is not None


def test_the_same_job_run_twice_does_not_double_the_pool(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """at-least-once. 같은 job을 두 번 실행해도 문장도 candidate도 두 벌이 되지 않는다.

    두 번째 실행은 job을 `queued`로 되돌려 만든다 --- worker가 결과를 적고 죽어서 ack가
    유실된 상태다. 재실행이 그 item의 Ready 문장을 다시 사지 않는 것까지 함께 본다
    (`provider.call_count`가 그대로다).
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    with committed_db() as setup:
        factories.make_learning_item(setup, lemma="仕方ない")
        _activate_prompt_versions(setup, LlmTaskType.GENERATE_SENTENCE_BATCH)
        setup.commit()

    session_id = _start(committed_api)
    assert _next(committed_api, session_id) is None

    japanese = "それは仕方ないと思う。"
    response = _batch_of(japanese, surface="仕方ない")
    provider = RecordingProvider(responses=[response, response])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    shown = _next(committed_api, session_id)
    assert shown is not None
    sentences_before = len(_sentences(observer, source="generated"))
    candidates_before = _count(observer, UserSentenceCandidate)

    with committed_db() as reset:
        for job in reset.execute(sa.select(GenerationJob)).scalars().all():
            job.status = GenerationJobStatus.QUEUED
            job.next_attempt_at = now
            job.finished_at = None
        reset.commit()
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1, "재실행이 같은 콘텐츠를 다시 샀다"
    assert len(_sentences(observer, source="generated")) == sentences_before
    # materialization을 한 번 더 돌린다. 중복 candidate는 partial unique index가
    # 막지만, 그 자리에서 IntegrityError로 요청이 깨지지 않는 것까지 본다.
    _complete(committed_api, shown["presentation_id"])
    _next(committed_api, session_id)
    assert _count(observer, UserSentenceCandidate) == candidates_before


# --------------------------------------------------------------------------
# 불변식 #7: quarantined content는 새 id로 되살아나지 않는다
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Flagged:
    """사용자가 `unnatural`로 신고해 격리된 문장과, 그 세션."""

    session_id: int
    sentence_id: int
    japanese: str


def _quarantine_by_flagging(
    api: StudyApi, factory: sessionmaker[Session], observer: Session, *, cfg: AppConfig
) -> _Flagged:
    """제시 -> 완료 -> `/flag`로 문장을 실제 경로로 격리시킨다.

    `sentences.status`를 손으로 바꾸지 않는다. flag가 quarantine·candidate 격리·exposure
    무효화를 한 트랜잭션에서 하므로(`services/content_flag.py`), 상태를 직접 세우면 그
    묶음이 갈라진 구현에서도 아래 단정이 통과한다.

    `normalized_hash`는 손으로 넣지 않는다. `factories.make_sentence`가 본문에서
    `normalized_sentence_hash`로 계산하므로(그 factory의 docstring) 실제 경로(seed
    loader / persistence)와 같은 값이고, 그래서 아래 단정이 검사하는 hash 비교가
    실제로 일어난다. 자리 채우기 해시를 쓰면 같은 문장을 넣어도 hash가 달라 11번이
    발화할 수 없으므로, factory가 그 값을 계산하는 것 자체가 이 테스트의 전제다.
    """
    japanese = "それは君に任せる。"
    with factory() as setup:
        item = factories.make_learning_item(setup, lemma="任せる")
        sentence = factories.make_ready_sentence(setup, [item], surfaces=[japanese])
        assert sentence.normalized_hash == normalized_sentence_hash(japanese)
        _activate_prompt_versions(setup, LlmTaskType.GENERATE_SENTENCE_BATCH)
        setup.commit()
        flagged_id = sentence.id

    session_id = _start(api)
    shown = _next(api, session_id)
    assert shown is not None
    assert shown["sentence_id"] == flagged_id
    _complete(api, shown["presentation_id"])
    _flag(api, shown["presentation_id"])

    quarantined = observer.get(Sentence, flagged_id, populate_existing=True)
    assert quarantined is not None
    assert quarantined.status is SentenceStatus.QUARANTINED
    assert _next(api, session_id) is None, "격리된 문장이 다시 선택됐다"
    del cfg  # 호출부가 이미 app에 꽂았다. 여기서는 서명의 대칭을 위해 받는다.
    return _Flagged(session_id=session_id, sentence_id=flagged_id, japanese=japanese)


def _rejection_reasons(observer: Session) -> list[str]:
    return [
        str(row["reason"])
        for job in _jobs(observer, job_type=JobType.GENERATE_SENTENCE_BATCH)
        for row in ((job.result_ref or {}).get("rejected") or [])
    ]


def test_quarantined_sentence_is_not_regenerated_into_ready(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """flag된 문장과 **같은 문장**을 생성하려 하면 `duplicate_hash`로 탈락한다.

    **주의: 이 단정만으로는 duplicate corpus에서 `quarantined`를 빼는 회귀를 잡지
    못한다.** 같은 해시에 대한 방어가 두 겹이기 때문이다 --- corpus 비교(검사 11)와
    `jobs/persistence._store_one`의 hash 대조. 뒤쪽은 `sentences.status`를 보지 않으므로
    corpus에서 quarantined를 빼도 같은 `duplicate_hash`가 나오고 문장은 저장되지 않는다.
    그 회귀를 잡는 것은 아래
    `test_a_near_copy_of_a_quarantined_sentence_is_rejected_by_the_corpus`다.

    그래도 이 테스트를 두는 이유는 여기서 고정하는 것이 "어느 계층이 막는가"가 아니라
    **사용자에게 보이는 결과**이기 때문이다: 신고한 문장은 새 id로도 다시 나오지 않는다.
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    flagged = _quarantine_by_flagging(committed_api, committed_db, observer, cfg=cfg)

    # 모델이 같은 문장을 다시 만들어 온다. 실제로 있었던 실패 양상이다 ---
    # avoid_japanese는 힌트일 뿐이고 판정은 deterministic duplicate 검사다.
    provider = RecordingProvider(responses=[_batch_of(flagged.japanese, surface="任せる")])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1, "생성 자체가 일어나지 않았다면 이 테스트는 무의미하다"
    assert _sentences(observer, source="generated") == []
    assert [row.id for row in _sentences(observer)] == [flagged.sentence_id]
    assert _rejection_reasons(observer) == ["duplicate_hash"]
    assert _next(committed_api, flagged.session_id) is None, "격리된 문장이 새 id로 되살아났다"


def test_a_near_copy_of_a_quarantined_sentence_is_rejected_by_the_corpus(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """격리된 문장의 **거의 같은 판**은 similarity(검사 12)로 탈락한다.

    이것이 "duplicate corpus에 `quarantined`가 포함된다"(`08_LLM_SPEC.md`)를 실제로 고정
    하는 단정이다. hash가 다르므로 `persistence`의 대조는 이것을 잡지 못하고, corpus에서
    quarantined를 빼면 그 문장이 새 id로 `validated`가 되어 다음 materialization이 다시
    Ready로 만든다 --- 사용자 입장에서는 신고가 무시된 것이다.

    threshold는 **주입한 값**이고 두 전제를 테스트가 직접 확인한다: (a) 두 문장의 해시가
    다르다, (b) 유사도가 주입한 threshold를 넘는다. 전제를 단정하지 않으면 문장을 한 글자
    고치는 순간 이 테스트가 아무것도 검사하지 않게 된다.
    """
    threshold = 0.5
    cfg = _cfg(content={"duplicate_similarity_threshold": threshold})
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    flagged = _quarantine_by_flagging(committed_api, committed_db, observer, cfg=cfg)

    near_copy = "それは君に任せるよ。"
    assert normalized_sentence_hash(near_copy) != normalized_sentence_hash(flagged.japanese)
    assert similarity_ratio(near_copy, flagged.japanese) > threshold

    provider = RecordingProvider(responses=[_batch_of(near_copy, surface="任せる")])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1, "생성 자체가 일어나지 않았다면 이 테스트는 무의미하다"
    assert _rejection_reasons(observer) == ["duplicate_similarity"]
    assert _sentences(observer, source="generated") == []
    assert _next(committed_api, flagged.session_id) is None, "격리된 문장의 사본이 Ready가 됐다"


# --------------------------------------------------------------------------
# EXPLAIN_ITEM: 설명이 붙으면 그 문장이 ready가 된다
# --------------------------------------------------------------------------


def test_the_explain_item_job_makes_the_skipped_sentence_presentable(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """Ready invariant(불변식 #6) 때문에 건너뛴 문장이 job -> worker를 거쳐 제시된다.

    `/next`가 그 문장을 실제로 돌려주는 것까지 본다. explanation row가 생기는 것만
    보면 selection이 그 문장을 여전히 배제하는 구현도 통과한다.
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    with committed_db() as setup:
        item = factories.make_learning_item(setup, lemma="任せる")
        sentence = factories.make_sentence(setup, japanese="それは君に任せる。")
        sentence_item = factories.make_sentence_item(setup, sentence, item, surface_form="任せる")
        factories.make_span(setup, sentence_item, start=5, end=8)
        # explanation을 두지 않는다. 그 하나 때문에 문장 전체가 ready가 아니다.
        _activate_prompt_versions(setup, LlmTaskType.EXPLAIN_ITEM)
        setup.commit()
        sentence_id = sentence.id
        sentence_item_id = sentence_item.id

    session_id = _start(committed_api)
    assert _next(committed_api, session_id) is None

    (job,) = _jobs(observer, job_type=JobType.EXPLAIN_ITEM)
    assert job.payload_json == {"sentence_item_id": sentence_item_id}

    provider = RecordingProvider(responses=[json.dumps(explanation_payload(), ensure_ascii=False)])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1
    stored = observer.execute(
        sa.select(SentenceItemExplanation).where(
            SentenceItemExplanation.sentence_item_id == sentence_item_id
        )
    ).scalar_one()
    assert stored.status is ExplanationStatus.VALIDATED
    # provenance는 active `prompt_versions` 행에서 온다. `stub`은 test double이 만든
    # 콘텐츠라는 뜻이며 `LLM_PROVIDER`가 가질 수 있는 값이 아니다(ADR-016의 `개정`).
    assert stored.provider == "stub"
    assert stored.prompt_version == explain_item_prompt.VERSION

    shown = _next(committed_api, session_id)

    assert shown is not None, "설명이 붙었는데도 그 문장이 pool로 오지 않았다"
    assert shown["sentence_id"] == sentence_id


# --------------------------------------------------------------------------
# GENERATE_REVIEW_CONTEXT: 그 stage의 candidate가 생긴다
# --------------------------------------------------------------------------


def _review_item_without_a_sentence_for(
    db: Session, user: User, *, stage: ContextStage, now: datetime, cfg: AppConfig
) -> tuple[LearningItem, Sentence]:
    """그 stage 조건에 맞는 미노출 문장이 없는 review item 하나.

    `varied`는 "anchor가 아니고 아직 제시되지 않은 문장"을 요구한다. anchor 하나뿐이고
    그것이 이미 제시됐으면 조건을 만족하는 문장이 없다 --- `GENERATE_REVIEW_CONTEXT`의
    트리거 지점이다. stage와 노출을 factory로 세우는 이유는 전제가 "이미 ladder 뒤쪽에
    도달한 item"이어서다(`factories.make_learning_state`의 주의).
    """
    item = factories.make_learning_item(db, lemma="任せる")
    # `normalized_hash`는 factory가 본문에서 계산한다. 손으로 덮어쓰지 않는다.
    anchor = factories.make_ready_sentence(db, [item], surfaces=["それは君に任せる。"])
    factories.make_learning_state(
        db,
        user,
        item,
        context_stage=stage,
        is_active_learning_target=True,
        anchor_sentence_id=anchor.id,
    )
    review_state = factories.make_review_state(
        db, user, item, state=FSRS_STATE_FILLER, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.next_review_at = now - timedelta(days=1)

    # 유효 exposure 1건이 있어야 그 item이 `new`가 아니라 `review` pool의 몫이다(ADR-013).
    study = factories.make_study_session(
        db, user, target_minutes=cfg.learning.default_session_minutes
    )
    candidate = factories.make_candidate(
        db,
        user,
        anchor,
        status=CandidateStatus.CONSUMED,
        presentation_role=PresentationRole.REVIEW,
    )
    presentation = factories.make_presentation(
        db,
        user,
        study,
        candidate,
        anchor,
        presentation_role=PresentationRole.REVIEW,
        review_reason=ReviewReason.FSRS_DUE,
        completed_at=now,
    )
    factories.make_exposure(db, user, item, presentation, anchor)
    db.flush()
    return item, anchor


def test_the_review_context_job_creates_the_candidate_for_that_stage(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """stage에 맞는 문장이 없어 생긴 job이 worker를 거쳐 **그 stage의 candidate**가 된다.

    `varied`를 쓴다. `near_original`은 similarity(12번)를 면제받으므로 생성물이 anchor와
    거의 같아도 통과해서, "새 문맥이 실제로 pool에 들어왔는가"를 약하게 만든다.
    """
    cfg = _cfg()
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    stage = ContextStage.VARIED
    with committed_db() as setup:
        item, anchor = _review_item_without_a_sentence_for(
            setup, committed_api.user, stage=stage, now=now, cfg=cfg
        )
        _activate_prompt_versions(setup, LlmTaskType.GENERATE_REVIEW_CONTEXT)
        setup.commit()
        item_id = item.id
        anchor_id = anchor.id

    session_id = _start(committed_api)

    (job,) = _jobs(observer, job_type=JobType.GENERATE_REVIEW_CONTEXT)
    assert job.payload_json == {
        "user_id": committed_api.user.id,
        "learning_item_id": item_id,
        "context_stage": stage.value,
        "anchor_sentence_id": anchor_id,
    }

    japanese = "今日の仕事は全部あなたに任せるつもりだ。"
    provider = RecordingProvider(responses=[_batch_of(japanese, surface="任せる")])
    _drain(committed_db, provider=provider, cfg=cfg, now=now)

    assert provider.call_count == 1
    generated = _sentences(observer, source="generated")
    assert [row.japanese for row in generated] == [japanese]
    # `varied`는 anchor의 자식이 아니다. lineage는 stage에서 나온다.
    assert generated[0].parent_sentence_id is None

    shown = _next(committed_api, session_id)

    assert shown is not None, "생성된 문맥이 review pool로 돌아오지 않았다"
    assert shown["sentence_id"] == generated[0].id
    assert shown["context_stage"] == stage.value
    assert shown["presentation_role"] == PresentationRole.REVIEW.value
    candidate = observer.execute(
        sa.select(UserSentenceCandidate).where(UserSentenceCandidate.sentence_id == generated[0].id)
    ).scalar_one()
    assert candidate.context_stage is stage
    assert candidate.presentation_role is PresentationRole.REVIEW


# --------------------------------------------------------------------------
# cost ceiling: 생성이 멈춰도 학습은 계속된다
# --------------------------------------------------------------------------


def test_the_session_keeps_serving_while_the_ceiling_blocks_the_claim(
    committed_api: StudyApi, committed_db: sessionmaker[Session], observer: Session
) -> None:
    """`daily_request_limit`에 도달한 상태에서도 `/next`가 계속 응답한다.

    한도는 **주입한 값**이고 오늘 쓴 호출 수는 그 값에 맞춰 만든다. 기본값(`null` =
    disabled)에 기대면 이 테스트는 한도를 읽지 않는 구현에서도 통과한다.

    함께 보는 것: ceiling에 걸린 job은 `queued`로 남고 `retry_count`가 늘지 않는다.
    claim한 뒤 한도로 실패시키면 다음 날 살아 있어야 할 job이 `failed`가 된다.
    """
    limit = 1
    cfg = _cfg(llm={"daily_request_limit": limit, "daily_token_limit": None})
    committed_api.use_config(cfg)
    now = committed_api.clock.now()
    with committed_db() as setup:
        item = factories.make_learning_item(setup, lemma="任せる")
        factories.make_ready_sentence(setup, [item])
        # 생성이 필요한 item을 하나 더 둔다. 그것이 job의 대상이다.
        factories.make_learning_item(setup, lemma="仕方ない")
        _activate_prompt_versions(setup, LlmTaskType.GENERATE_SENTENCE_BATCH)
        _spent_call(setup, now=now, provider_calls=limit, cfg=cfg)
        _queued_batch_job(
            setup, user=committed_api.user, role=PresentationRole.EXPLORATION, cfg=cfg
        )
        setup.commit()

    provider = RecordingProvider(responses=[_batch_of("それは仕方ない。", surface="仕方ない")])
    assert _drain(committed_db, provider=provider, cfg=cfg, now=now) == 0

    assert provider.calls == []
    blocked = _jobs(observer, job_type=JobType.GENERATE_SENTENCE_BATCH)
    assert [job.status for job in blocked] == [
        GenerationJobStatus.COMPLETED,  # usage를 들고 있는 과거 job
        GenerationJobStatus.QUEUED,
    ]
    assert blocked[1].retry_count == 0

    session_id = _start(committed_api)
    shown = _next(committed_api, session_id)

    assert shown is not None, "생성이 멈추자 학습 세션도 멈췄다"
    assert provider.calls == []


# --------------------------------------------------------------------------
# heartbeat: worker가 돌면 health가 ok를 답한다
# --------------------------------------------------------------------------


def test_a_worker_turn_makes_the_health_endpoint_report_ok(
    committed_api: StudyApi, committed_db: sessionmaker[Session]
) -> None:
    """worker loop 1회전 -> `worker_heartbeats` upsert -> `/api/health`가 `ok`.

    두 주체가 다른 프로세스·다른 세션이므로 커밋된 값으로만 만난다. 임계값은
    주입하고 시계를 그 안쪽으로 옮긴다 --- 기본값에 기대면 "임계값을 읽는가"를 보지
    못한다.
    """
    stale_seconds = 300
    cfg = _cfg(jobs={"heartbeat_stale_seconds": stale_seconds})
    committed_api.use_config(cfg)
    now = committed_api.clock.now()

    before = committed_api.client.get("/api/health").json()
    assert before["components"]["worker"]["status"] == "unknown"
    assert before["status"] == "ok"

    provider = RecordingProvider()
    assert _drain(committed_db, provider=provider, cfg=cfg, now=now) == 0

    committed_api.clock.advance(timedelta(seconds=stale_seconds - 1))
    body = committed_api.client.get("/api/health").json()

    assert body["components"]["worker"]["status"] == "ok", body
    assert body["status"] == "ok"
    assert provider.calls == []
