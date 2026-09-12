"""`GENERATE_SENTENCE_BATCH` handler와 `runner` 파이프라인 (`08_LLM_SPEC.md`).

provider는 `runner.run_job`에 **인자로** 넣는다(`tests.provider_double`). 그래서
claim 이후의 모든 단계 --- 대상 재계산 / 요청 조립 / validation / duplicate / 저장 /
completed / 실패 분류 --- 가 실제 코드로 실행되고 provider 호출만 대체된다.

`committed_db`를 쓴다. `persistence`가 커밋하는 경계를 검사하기 때문이다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import observability, runner
from app.jobs.generate_sentence_batch import (
    avoid_examples,
    load_corpus,
    sentence_policy,
)
from app.jobs.persistence import DUPLICATE_BACKSTOP_MARKER
from app.learning.selection import has_ready_sentence, materialize_candidates
from app.llm.prompts import sentence_gen
from app.llm.provider import ProviderCallError, ProviderRequest, ProviderResult
from app.llm.tasks import requested_refs
from app.models.content import LearningItem, Sentence, SentenceItem
from app.models.enums import (
    CandidateStatus,
    GenerationJobStatus,
    JobType,
    LlmTaskType,
    PresentationRole,
    SentenceStatus,
)
from app.models.jobs import GenerationJob
from app.models.learning import UserSentenceCandidate
from app.models.user import User
from app.normalization import normalized_sentence_hash
from tests import factories
from tests.clock import MutableClock
from tests.conftest import override_config
from tests.llm_fixtures import (
    batch_response,
    explanation_payload,
    item_payload,
    sentence_payload,
)
from tests.provider_double import RecordingProvider

COMPLETED = GenerationJobStatus.COMPLETED
RETRY = GenerationJobStatus.RETRY
DEAD_LETTER = GenerationJobStatus.DEAD_LETTER


@pytest.fixture
def db(committed_db: sessionmaker[Session]) -> Iterator[Session]:
    with committed_db() as session:
        yield session


def _cfg(**llm: object) -> AppConfig:
    return override_config(get_config(), llm=llm)


def _prompt_version(db: Session) -> None:
    factories.make_prompt_version(
        db,
        task_type=LlmTaskType.GENERATE_SENTENCE_BATCH,
        version=sentence_gen.VERSION,
    )


def _job(
    db: Session,
    user: User,
    *,
    role: PresentationRole = PresentationRole.EXPLORATION,
    payload: dict[str, object] | None = None,
    key: str = "replenish:test",
) -> GenerationJob:
    """enqueue 직후의 job. payload는 `{user_id, presentation_role}` 둘뿐이다."""
    job = factories.make_generation_job(
        db, idempotency_key=key, max_attempts=get_config().jobs.max_job_attempts
    )
    job.job_type = JobType.GENERATE_SENTENCE_BATCH
    job.payload_json = (
        {"user_id": user.id, "presentation_role": role.value} if payload is None else payload
    )
    job.status = GenerationJobStatus.RUNNING
    job.retry_count = 1  # claim이 이미 올린 값
    db.commit()
    return job


def _run(
    db: Session,
    job: GenerationJob,
    provider: RecordingProvider,
    clock: MutableClock,
    cfg: AppConfig | None = None,
) -> GenerationJobStatus:
    return runner.run_job(
        db,
        job=job,
        provider=provider,
        cfg=get_config() if cfg is None else cfg,
        now=clock.now(),
    )


def _sentences(db: Session) -> list[Sentence]:
    return list(db.execute(sa.select(Sentence).order_by(Sentence.id)).scalars().all())


def _reload(db: Session, job: GenerationJob) -> GenerationJob:
    fresh = db.get(GenerationJob, job.id, populate_existing=True)
    assert fresh is not None
    return fresh


def _result(job: GenerationJob) -> dict[str, Any]:
    """`result_ref`는 nullable이다. 없으면 그 자체가 실패다."""
    assert job.result_ref is not None
    return job.result_ref


# --------------------------------------------------------------------------
# 대상 선정
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_worker_asks_for_one_sentence_per_item_that_has_no_ready_sentence(
    db: Session, study_clock: MutableClock
) -> None:
    """대상은 실행 시점에 다시 계산한다. payload에는 item 목록이 없다."""
    user = factories.make_user(db)
    covered = factories.make_learning_item(db, lemma="任せる")
    factories.make_ready_sentence(db, [covered])
    bare = factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(
        responses=[
            batch_response(
                sentence_payload(
                    "仕方ないと思う。", [item_payload("it0", "仕方ない", "仕方ないと思う。")]
                )
            )
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    # 이미 Ready 문장이 있는 item은 요청에 실리지 않는다. 비용만 늘기 때문이다.
    context = json.loads(provider.calls[0].context)
    assert [target["lemma"] for target in context["target_items"]] == [bare.lemma]
    assert context["sentences_requested"] == 1
    stored = [row for row in _sentences(db) if row.source_type.value == "generated"]
    assert [row.japanese for row in stored] == ["仕方ないと思う。"]
    assert covered.id is not None


@pytest.mark.integration
def test_no_target_means_no_provider_call_and_a_completed_job(
    db: Session, study_clock: MutableClock
) -> None:
    """빈 결과는 실패가 아니다(`08_LLM_SPEC.md`)."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db)
    factories.make_ready_sentence(db, [item])
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    assert provider.call_count == 0
    assert _reload(db, job).status is COMPLETED


@pytest.mark.integration
def test_the_batch_size_comes_from_config(db: Session, study_clock: MutableClock) -> None:
    """`llm.sentences_per_batch`. 숫자를 코드에 박으면 config를 읽지 않는 구현도 통과한다."""
    user = factories.make_user(db)
    for index in range(4):
        factories.make_learning_item(db, lemma=f"表現{index}")
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=[batch_response()])

    _run(db, job, provider, study_clock, cfg=_cfg(sentences_per_batch=2))

    context = json.loads(provider.calls[0].context)
    assert len(context["target_items"]) == 2


@pytest.mark.integration
def test_the_new_role_targets_items_that_were_never_presented(
    db: Session, study_clock: MutableClock
) -> None:
    """`new` = 활성 학습 target인데 유효 exposure가 0건인 item (ADR-013)."""
    user = factories.make_user(db)
    promoted = factories.make_learning_item(db, lemma="任せる")
    factories.make_learning_state(db, user, promoted, is_active_learning_target=True)
    passive = factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user, role=PresentationRole.NEW)
    provider = RecordingProvider(responses=[batch_response()])

    _run(db, job, provider, study_clock)

    context = json.loads(provider.calls[0].context)
    assert [target["lemma"] for target in context["target_items"]] == [promoted.lemma]
    assert passive.lemma not in json.dumps(context, ensure_ascii=False)


@pytest.mark.integration
def test_the_review_role_targets_items_with_a_review_state_and_an_exposure(
    db: Session, study_clock: MutableClock
) -> None:
    """`review` 대상은 `review_states`가 있고 유효 exposure가 1건 이상인 item이다.

    거기에 "그 item에 쓸 문장이 아예 없다"가 더 붙는다. 문장은 있는데 현재
    `context_stage`에 맞는 것만 없는 경우는 `GENERATE_REVIEW_CONTEXT`의 몫이다.
    """
    user = factories.make_user(db)
    covered = factories.make_learning_item(db, lemma="任せる")
    never_shown = factories.make_learning_item(db, lemma="仕方ない")
    starved = factories.make_learning_item(db, lemma="思い切って")
    for item in (covered, never_shown, starved):
        factories.make_review_state(db, user, item, state=1, params_version="fsrs-6.3.2")
    sentence = factories.make_ready_sentence(db, [covered])
    study_session = factories.make_study_session(
        db, user, target_minutes=get_config().learning.default_session_minutes
    )
    candidate = factories.make_candidate(db, user, sentence, status=CandidateStatus.CONSUMED)
    presentation = factories.make_presentation(db, user, study_session, candidate, sentence)
    # covered: 노출됐지만 Ready 문장이 이미 있다.  starved: 노출됐고 문장이 없다.
    factories.make_exposure(db, user, covered, presentation, sentence)
    factories.make_exposure(db, user, starved, presentation, sentence)
    _prompt_version(db)
    job = _job(db, user, role=PresentationRole.REVIEW)
    provider = RecordingProvider(responses=[batch_response()])

    _run(db, job, provider, study_clock)

    context = json.loads(provider.calls[0].context)
    assert [target["lemma"] for target in context["target_items"]] == [starved.lemma]
    # never_shown은 유효 exposure가 0건이다. 그 item의 첫 제시는 `new`의 몫이다.
    assert never_shown.lemma not in json.dumps(context, ensure_ascii=False)


# --------------------------------------------------------------------------
# validation 정책값의 배선 (`sentence_policy`)
#
# `test_llm_validation.py`는 `validate_sentence`에 `SentencePolicy`를 **주입해** 검사
# 3·5·10을 확인한다. 그것만으로는 handler가 그 정책값을 config에서 실어 보내는지
# 알 수 없다 --- 배선을 리터럴로 바꿔도 그 단위 테스트는 전부 통과한다. 아래가
# 그 사이를 잇는다(13_ACCEPTANCE_CRITERIA.md의 `수치 취급 원칙`).
# --------------------------------------------------------------------------


def test_the_sentence_policy_takes_every_limit_from_config() -> None:
    """검사 3·5·10의 상한이 전부 config에서 온다. DB를 쓰지 않는다.

    주입한 값이 그대로 나오는지 본다. 기본값과 비교하면 config를 아예 읽지 않는
    구현도 통과하므로, 기본값과 **다른** 값을 넣는다.
    """
    length, new_items = 41, 3
    cfg = override_config(
        get_config(),
        content={"max_sentence_length_chars": length},
        learning={"max_new_items_per_sentence": new_items},
    )
    assert cfg.content.max_sentence_length_chars != get_config().content.max_sentence_length_chars
    assert (
        cfg.learning.max_new_items_per_sentence != get_config().learning.max_new_items_per_sentence
    )

    policy = sentence_policy(cfg)

    assert policy.max_sentence_length_chars == length
    assert policy.max_targets_per_sentence == new_items
    assert policy.max_new_items_per_sentence == new_items


def test_check_ten_cannot_fire_while_both_limits_share_one_config_key() -> None:
    """검사 10(`too_many_targets`)은 **이 배선에서는 도달 불가능하다.**

    `sentence_policy`가 검사 5의 상한과 검사 10의 상한을 둘 다
    `learning.max_new_items_per_sentence`에서 가져오고, 신규 target 수는 항상 전체
    target 수 이하다. 그래서 검사 10이 발화할 조건(`new_count > L`)은 검사 5가
    먼저 탈락시키는 조건(`target_count > L`)을 반드시 포함한다 ---
    `app/llm/validation.py`의 `SentencePolicy` docstring이 경고한 "죽은 검사"가 실제
    상태다.

    이 사실을 테스트로 고정하는 이유: 그렇지 않으면 (a) 검사 10을 handler 경로로
    검증하려는 시도가 매번 `target_count_out_of_range`를 받고 원인을 알 수 없고,
    (b) 두 상한을 분리하는 변경이 들어와도 아무 신호가 없다. 분리되는 날 이
    테스트가 빨개지고, 그때 handler 경로의 검사 10 테스트를 추가하면 된다.
    """
    policy = sentence_policy(get_config())
    limit = policy.max_targets_per_sentence
    assert policy.max_new_items_per_sentence == limit

    reachable = [
        (targets, new)
        for targets in range(limit + 5)
        for new in range(targets + 1)  # 신규 target은 전체 target의 부분집합이다
        if new > policy.max_new_items_per_sentence and 1 <= targets <= limit
    ]
    assert reachable == [], (
        "두 상한이 갈라졌다. 검사 10이 도달 가능해졌으므로 handler 경로 테스트를 추가하라"
    )


@pytest.mark.integration
def test_the_configured_sentence_length_is_the_limit_the_handler_enforces(
    db: Session, study_clock: MutableClock
) -> None:
    """검사 3이 **주입한** `content.max_sentence_length_chars`로 판정된다.

    경계 양쪽을 본다. 한쪽만 보면 상한을 리터럴로 박은 구현이 통과한다.

    너무 긴 쪽을 **먼저** 돌린다. 순서를 바꾸면 먼저 저장된 문장이 corpus에 들어가
    두 번째가 `duplicate_similarity`로 탈락하고, 검사 3은 발화하지 않은 채 이
    테스트가 통과한다.
    """
    limit = 12
    surface = "任せる"
    cfg = override_config(get_config(), content={"max_sentence_length_chars": limit})
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma=surface)
    _prompt_version(db)

    too_long = surface + "あ" * (limit + 1 - len(surface))
    assert len(too_long) == limit + 1
    rejected_job = _job(db, user, key="length:over")
    status = _run(
        db,
        rejected_job,
        RecordingProvider(
            responses=[
                batch_response(sentence_payload(too_long, [item_payload("it0", surface, too_long)]))
            ]
        ),
        study_clock,
        cfg=cfg,
    )

    assert status is RETRY
    rejected = _result(_reload(db, rejected_job))["rejected"]
    assert [row["reason"] for row in rejected] == ["sentence_too_long"]
    assert str(limit) in rejected[0]["detail"]
    assert _sentences(db) == []

    exact = surface + "あ" * (limit - len(surface))
    assert len(exact) == limit
    accepted_job = _job(db, user, key="length:exact")
    status = _run(
        db,
        accepted_job,
        RecordingProvider(
            responses=[
                batch_response(sentence_payload(exact, [item_payload("it0", surface, exact)]))
            ]
        ),
        study_clock,
        cfg=cfg,
    )

    assert status is COMPLETED, "상한과 같은 길이는 통과해야 한다"
    assert [row.japanese for row in _sentences(db)] == [exact]


# --------------------------------------------------------------------------
# duplicate 비교 corpus의 범위 (`08_LLM_SPEC.md`의 `duplicate 비교 corpus`)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_duplicate_corpus_keeps_quarantined_and_drops_retired(
    db: Session,
) -> None:
    """corpus는 `status != retired`인 `sentences` 전체다. 두 방향을 함께 고정한다.

    `quarantined` 포함은 불변식 #7이 요구한다(격리한 문장이 새 id로 되살아나지
    않는다). `retired` 제외는 그 반대쪽 규칙이고, **행동으로는 관측되지 않는다**
    --- MVP에는 `retired`로 전이시키는 코드 경로가 없어서 그 상태를 만들 수 있는
    것은 테스트뿐이다. 그래서 corpus 조회를 직접 부른다. 이 테스트가 없으면 필터를
    통째로 지워도 스위트 전체가 초록이다.
    """
    item = factories.make_learning_item(db, lemma="任せる")
    live = factories.make_ready_sentence(db, [item], surfaces=["それは君に任せる。"])
    quarantined = factories.make_ready_sentence(db, [item], surfaces=["今日は全部君に任せる。"])
    quarantined.status = SentenceStatus.QUARANTINED
    retired = factories.make_ready_sentence(db, [item], surfaces=["昔は彼に任せるつもりだった。"])
    retired.status = SentenceStatus.RETIRED
    db.flush()

    corpus = load_corpus(db, exclude_job_id=None)

    assert [row.sentence_id for row in corpus] == [live.id, quarantined.id]
    assert retired.id not in {row.sentence_id for row in corpus}
    # 해시도 실제 본문에서 온 값이어야 한다. 자리 채우기 값이면 11번이 발화할 수 없다.
    assert [row.normalized_hash for row in corpus] == [
        normalized_sentence_hash(live.japanese),
        normalized_sentence_hash(quarantined.japanese),
    ]


@pytest.mark.integration
def test_avoid_examples_skip_retired_sentences(db: Session) -> None:
    """프롬프트의 회피 예시도 `retired`를 싣지 않는다. `load_corpus`와 같은 규칙이다.

    같은 규칙이 두 조회에 각각 적혀 있어(`generate_sentence_batch.py`) 한쪽만 고쳐도
    아무 신호가 없다. 그래서 두 자리를 따로 고정한다.
    """
    item = factories.make_learning_item(db, lemma="任せる")
    live = factories.make_ready_sentence(db, [item], surfaces=["それは君に任せる。"])
    retired = factories.make_ready_sentence(db, [item], surfaces=["昔は彼に任せるつもりだった。"])
    retired.status = SentenceStatus.RETIRED
    db.flush()

    examples = avoid_examples(
        db, learning_item_id=item.id, limit=get_config().llm.avoid_examples_per_item
    )

    assert examples == [live.japanese]


# --------------------------------------------------------------------------
# 응답 처리
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_a_generated_sentence_becomes_a_candidate_on_the_next_materialization(
    db: Session, study_clock: MutableClock
) -> None:
    """worker는 candidate를 만들지 않는다. 다음 materialization이 만든다."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "それは仕方ないと思う。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", "仕方ない", japanese)]))
        ]
    )

    _run(db, job, provider, study_clock)

    assert has_ready_sentence(db, learning_item_id=item.id)
    created = materialize_candidates(
        db, user=user, now=study_clock.now(), cfg=get_config().learning
    )
    db.commit()
    assert created == 1
    candidate = db.execute(sa.select(UserSentenceCandidate)).scalar_one()
    stored = db.execute(sa.select(Sentence).where(Sentence.japanese == japanese)).scalar_one()
    assert candidate.sentence_id == stored.id
    assert stored.status is SentenceStatus.VALIDATED


@pytest.mark.integration
def test_one_rejected_sentence_does_not_discard_the_rest(
    db: Session, study_clock: MutableClock
) -> None:
    """부분 수용. 3개 중 1개가 탈락해도 2개를 저장한다."""
    user = factories.make_user(db)
    items = [factories.make_learning_item(db, lemma=f"表現{index}") for index in range(3)]
    _prompt_version(db)
    job = _job(db, user)
    good = [
        sentence_payload(
            f"これは{item.lemma}です。",
            [item_payload(f"it{index}", item.lemma, f"これは{item.lemma}です。")],
        )
        for index, item in enumerate(items[:2])
    ]
    # 세 번째 문장은 요청하지 않은 item_ref를 쓴다 -> unknown_item_ref.
    bad = sentence_payload("これは表現9です。", [item_payload("it9", "表現9", "これは表現9です。")])
    provider = RecordingProvider(responses=[batch_response(*good, bad)])

    status = _run(db, job, provider, study_clock, cfg=_cfg(sentences_per_batch=3))

    assert status is COMPLETED
    stored = _reload(db, job)
    assert len(_result(stored)["sentence_ids"]) == 2
    assert [row["reason"] for row in _result(stored)["rejected"]] == ["unknown_item_ref"]
    assert len(_sentences(db)) == 2


@pytest.mark.integration
def test_the_second_copy_of_the_same_sentence_in_one_batch_is_rejected(
    db: Session, study_clock: MutableClock
) -> None:
    """`find_duplicate`는 문장 하나만 본다. 통과한 문장을 corpus에 이어 붙여야 잡힌다."""
    user = factories.make_user(db)
    # 두 target을 요청하지만 모델은 같은 문장을 두 번 돌려준다.
    factories.make_learning_item(db, lemma="任せる")
    factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "それは君に任せる。"
    provider = RecordingProvider(
        responses=[
            batch_response(
                sentence_payload(japanese, [item_payload("it0", "任せる", japanese)]),
                sentence_payload(japanese, [item_payload("it0", "任せる", japanese)]),
            )
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is COMPLETED
    stored = _reload(db, job)
    assert len(_result(stored)["sentence_ids"]) == 1
    assert [row["reason"] for row in _result(stored)["rejected"]] == ["duplicate_hash"]
    assert len(_sentences(db)) == 1


@pytest.mark.integration
def test_a_sentence_that_repeats_existing_content_is_rejected(
    db: Session, study_clock: MutableClock
) -> None:
    """비교 corpus는 `status != retired`인 `sentences` 전체다. quarantined도 포함한다.

    탈락이 **corpus 비교(11번)에서** 났다는 것까지 단정한다. `persistence`의 backstop도
    같은 `duplicate_hash`를 내므로 사유 코드만 보면 corpus에서 `quarantined`를 빼도 이
    테스트가 통과한다 --- 그러면 불변식 #7의 hash 경로 방어가 관측되지 않는다. backstop이
    낸 것은 `detail`에 `DUPLICATE_BACKSTOP_MARKER`를 달고 온다.
    """
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma="任せる")
    japanese = "それは君に任せる。"
    quarantined = factories.make_ready_sentence(db, [item], surfaces=[japanese])
    quarantined.status = SentenceStatus.QUARANTINED
    db.commit()
    assert quarantined.normalized_hash == normalized_sentence_hash(japanese)
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", "任せる", japanese)]))
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    stored = _reload(db, job)
    rejected = _result(stored)["rejected"]
    assert [row["reason"] for row in rejected] == ["duplicate_hash"]
    assert rejected[0]["detail"] == f"normalized_hash matches sentence {quarantined.id}"
    assert DUPLICATE_BACKSTOP_MARKER not in rejected[0]["detail"]
    assert len(_sentences(db)) == 1


@pytest.mark.integration
def test_running_the_same_job_twice_stores_the_sentence_once(
    db: Session, study_clock: MutableClock
) -> None:
    """at-least-once. 재실행이 자기 콘텐츠를 duplicate로 보지도, 두 번 만들지도 않는다."""
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "それは仕方ない。"
    response = batch_response(
        sentence_payload(japanese, [item_payload("it0", "仕方ない", japanese)])
    )
    provider = RecordingProvider(responses=[response, response])

    first = _run(db, job, provider, study_clock)
    job.status = GenerationJobStatus.RUNNING
    db.commit()
    second = _run(db, job, provider, study_clock)

    assert (first, second) == (COMPLETED, COMPLETED)
    # 첫 실행이 문장을 만들었으므로 그 item은 더 이상 대상이 아니다. 재실행은
    # provider를 부르지도 않는다. 그래도 부르는 경로(대상이 남아 있는 경우)의 방어는
    # `persistence`의 hash 대조이며 test_jobs_persistence.py가 검사한다.
    assert provider.call_count == 1
    assert len(_sentences(db)) == 1
    assert int(db.execute(sa.select(sa.func.count()).select_from(SentenceItem)).scalar_one()) == 1


# --------------------------------------------------------------------------
# 실패 분류
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_every_sentence_rejected_is_a_retry(db: Session, study_clock: MutableClock) -> None:
    """전량 탈락은 재시도 대상이다. 저장한 것이 없으므로 completed가 아니다."""
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="任せる")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "これは表現9です。"
    provider = RecordingProvider(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it7", "表現9", japanese)]))
        ]
    )

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    stored = _reload(db, job)
    assert stored.last_error is not None
    assert "unknown_item_ref" in stored.last_error
    assert [row["reason"] for row in _result(stored)["rejected"]] == ["unknown_item_ref"]
    assert stored.next_attempt_at > study_clock.now()
    assert _sentences(db) == []


@pytest.mark.integration
def test_a_provider_failure_is_a_retry(db: Session, study_clock: MutableClock) -> None:
    user = factories.make_user(db)
    factories.make_learning_item(db)
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(error=ProviderCallError("timeout"))

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    stored = _reload(db, job)
    assert stored.last_error is not None
    assert "provider call failed" in stored.last_error
    # 호출이 없었으므로 usage도 없다.
    assert (stored.result_ref or {}).get("usage") is None


@pytest.mark.integration
def test_an_unparseable_response_is_a_retry(db: Session, study_clock: MutableClock) -> None:
    user = factories.make_user(db)
    factories.make_learning_item(db)
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=["{not json"])

    status = _run(db, job, provider, study_clock)

    assert status is RETRY
    stored = _reload(db, job)
    # 응답을 받은 직후 기록한 usage는 실패해도 남는다. 실패한 호출도 비용이다.
    assert _result(stored)["usage"]["provider_calls"] == 1
    assert _result(stored)["usage"]["last_call_at"].startswith("2026-01-01")


@pytest.mark.integration
def test_a_missing_active_prompt_version_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    """재시도해도 결과가 같다. attempt를 소진하지 않는다."""
    user = factories.make_user(db)
    factories.make_learning_item(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert provider.call_count == 0
    assert _reload(db, job).last_error == "no_active_prompt_version"


@pytest.mark.integration
def test_a_payload_without_the_required_keys_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    user = factories.make_user(db)
    _prompt_version(db)
    job = _job(db, user, payload={"user_id": user.id})
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert _reload(db, job).last_error == "invalid_payload"


@pytest.mark.integration
def test_a_payload_that_points_at_no_user_is_a_dead_letter(
    db: Session, study_clock: MutableClock
) -> None:
    user = factories.make_user(db)
    _prompt_version(db)
    job = _job(
        db,
        user,
        payload={"user_id": user.id + 10_000, "presentation_role": "exploration"},
    )
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert _reload(db, job).last_error == "missing_reference"


@pytest.mark.integration
def test_an_unsupported_job_type_is_a_dead_letter(
    db: Session, study_clock: MutableClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """handler가 없는 job_type. enum이 닫혀 있으므로 registry를 비워 재현한다."""
    user = factories.make_user(db)
    job = _job(db, user)
    monkeypatch.setattr(runner, "HANDLERS", {})
    provider = RecordingProvider(responses=[])

    status = _run(db, job, provider, study_clock)

    assert status is DEAD_LETTER
    assert _reload(db, job).last_error == "unsupported_job_type"


# --------------------------------------------------------------------------
# 트랜잭션 경계 (ADR-015)
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_no_database_transaction_is_open_while_the_provider_runs(
    db: Session, study_clock: MutableClock
) -> None:
    """수 초짜리 HTTP가 커넥션과 행 잠금을 붙들면 request 경로가 같은 pool에서 굶는다."""
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="仕方ない")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "それは仕方ない。"
    observed: list[bool] = []

    class TransactionProbe(RecordingProvider):
        """호출 **순간**의 세션 상태를 기록한다. 호출이 끝난 뒤에 보면 이미 늦다."""

        def generate_structured(self, request: ProviderRequest) -> ProviderResult:
            observed.append(db.in_transaction())
            return super().generate_structured(request)

    provider = TransactionProbe(
        responses=[
            batch_response(sentence_payload(japanese, [item_payload("it0", "仕方ない", japanese)]))
        ]
    )

    _run(db, job, provider, study_clock)

    assert observed == [False]


@pytest.mark.integration
def test_the_request_carries_no_database_identifiers(
    db: Session, study_clock: MutableClock
) -> None:
    """모델이 유효해 보이는 id를 지어낼 수 없도록 DB id를 프롬프트에 싣지 않는다."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma="仕方ない")
    other = factories.make_ready_sentence(db, [factories.make_learning_item(db, lemma="任せる")])
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=[batch_response()])

    _run(db, job, provider, study_clock)

    context = json.loads(provider.calls[0].context)
    assert context["target_items"] == [
        {
            "item_ref": "it0",
            "type": item.type.value,
            "lemma": item.lemma,
            "reading": item.reading,
            "default_meaning": item.default_meaning,
        }
    ]
    assert user.login_id not in provider.calls[0].context
    # 응답을 되돌리는 열쇠는 요청 로컬 라벨뿐이다.
    assert set(context["target_items"][0]) == {
        "item_ref",
        "type",
        "lemma",
        "reading",
        "default_meaning",
    }
    assert requested_refs(()) == frozenset()
    assert other.id is not None


@pytest.mark.integration
def test_avoid_examples_are_capped_by_config(db: Session, study_clock: MutableClock) -> None:
    """`llm.avoid_examples_per_item`. 힌트일 뿐 실제 판정은 duplicate 검사가 한다."""
    user = factories.make_user(db)
    item = factories.make_learning_item(db, lemma="任せる")
    for prefix in ("A", "B", "C"):
        sentence = factories.make_sentence(db, japanese=f"{prefix}それは君に任せる。")
        factories.make_sentence_item(db, sentence, item, surface_form="任せる")
    _prompt_version(db)
    job = _job(db, user)
    provider = RecordingProvider(responses=[batch_response()])

    _run(db, job, provider, study_clock, cfg=_cfg(avoid_examples_per_item=2))

    context = json.loads(provider.calls[0].context)
    assert len(context["avoid_japanese"]) == 2
    assert all(row.endswith("それは君に任せる。") for row in context["avoid_japanese"])
    assert db.get(LearningItem, item.id) is not None


# --------------------------------------------------------------------------
# 관측: provider.call 로그 / usage / 남기지 않는 것 (11_OBSERVABILITY.md)
# --------------------------------------------------------------------------


class MeteredProvider(RecordingProvider):
    """usage를 **주는** provider. `RecordingProvider`는 주지 않는 쪽이다.

    두 double이 필요한 이유가 그것이다 --- token 수가 있는 경로와 없는 경로는 기록
    결과가 달라야 한다(`None`은 0이 아니다).
    """

    input_tokens = 1234
    output_tokens = 567

    def generate_structured(self, request: ProviderRequest) -> ProviderResult:
        result = super().generate_structured(request)
        return replace(result, input_tokens=self.input_tokens, output_tokens=self.output_tokens)


def _fields(caplog: pytest.LogCaptureFixture, message: str) -> dict[str, Any]:
    records = [record for record in caplog.records if record.getMessage() == message]
    assert len(records) == 1, [record.getMessage() for record in caplog.records]
    return records[0].__dict__


@pytest.mark.integration
def test_the_provider_call_is_logged_with_its_provenance_and_token_counts(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """`11_OBSERVABILITY.md`의 필수 수집 항목. prompt_version/model은 응답이 아니라
    active `prompt_versions` 행에서 온다.
    """
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="任せる")
    _prompt_version(db)
    job = _job(db, user)
    provider = MeteredProvider(responses=[batch_response()])

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        _run(db, job, provider, study_clock)

    fields = _fields(caplog, observability.PROVIDER_CALL)
    assert fields["task"] == JobType.GENERATE_SENTENCE_BATCH.value
    assert fields["prompt_version"] == sentence_gen.VERSION
    assert fields["model"] == provider.calls[0].model
    assert fields["input_tokens"] == 1234
    assert fields["output_tokens"] == 567
    # "estimated cost **if available**". 단가표가 없으므로 필드 자체가 없다.
    assert "estimated_cost_usd" not in fields


@pytest.mark.integration
def test_the_recorded_usage_comes_from_the_response(db: Session, study_clock: MutableClock) -> None:
    """`daily_token_limit`이 읽는 값이다. 0을 적으면 그 한도가 영원히 발화하지 않는다."""
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="任せる")
    _prompt_version(db)
    job = _job(db, user)

    _run(db, job, MeteredProvider(responses=[batch_response()]), study_clock)

    usage = _result(_reload(db, job))["usage"]
    assert usage["provider_calls"] == 1
    assert usage["input_tokens"] == 1234
    assert usage["output_tokens"] == 567


@pytest.mark.integration
def test_a_provider_that_reports_no_usage_records_null_tokens(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """usage가 없는 호출은 `null`이다. 0은 "호출했는데 토큰을 안 썼다"는 거짓이다."""
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="任せる")
    _prompt_version(db)
    job = _job(db, user)

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        _run(db, job, RecordingProvider(responses=[batch_response()]), study_clock)

    usage = _result(_reload(db, job))["usage"]
    assert usage["provider_calls"] == 1
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None
    assert _fields(caplog, observability.PROVIDER_CALL)["input_tokens"] is None


@pytest.mark.integration
def test_a_failed_call_logs_no_provider_call(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """token 수가 없는 호출을 0으로 적으면 로그 합계와 `result_ref.usage`가 갈린다.

    실패는 `job.failed`와 `last_error`가 남긴다.
    """
    user = factories.make_user(db)
    factories.make_learning_item(db)
    _prompt_version(db)
    job = _job(db, user)

    with caplog.at_level(logging.INFO, logger="app.jobs"):
        _run(db, job, RecordingProvider(error=ProviderCallError("timeout")), study_clock)

    assert [
        record for record in caplog.records if record.getMessage() == observability.PROVIDER_CALL
    ] == []


@pytest.mark.integration
def test_the_rejection_log_keeps_the_reason_code_and_drops_the_response_text(
    db: Session, study_clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    """`detail`에는 생성 문장의 slice가 들어간다. 그것은 DB에만 남는다.

    `11_OBSERVABILITY.md`와 `04_SECURITY_AND_DATA.md`: provider 응답 원문을 로그에
    남기지 않는다. 집계 단위인 사유 코드는 로그에도 있다(`08_LLM_SPEC.md`).
    """
    user = factories.make_user(db)
    factories.make_learning_item(db, lemma="任せる")
    _prompt_version(db)
    job = _job(db, user)
    japanese = "これは秘密の合図です。"
    surface = "存在しない表現"
    mismatched: dict[str, Any] = {
        "item_ref": "it0",
        "surface_form": surface,
        "is_tappable": True,
        # 범위는 유효하지만 다른 글자를 덮는다. surface_form이 문장에 없으므로 자동
        # 보정도 적용되지 않고, 사유 문자열이 덮은 **문장 조각**을 그대로 담는다.
        "spans": [{"start_codepoint": 0, "end_codepoint": 3, "span_order": 0}],
        "explanation": explanation_payload(),
    }
    provider = RecordingProvider(
        responses=[batch_response(sentence_payload(japanese, [mismatched]))]
    )

    with caplog.at_level(logging.INFO):
        status = _run(db, job, provider, study_clock)

    assert status is RETRY
    rejected = _result(_reload(db, job))["rejected"]
    assert [row["reason"] for row in rejected] == ["surface_not_found"]
    assert japanese[:3] in rejected[0]["detail"]  # 진단은 DB에 남는다
    assert "surface_not_found" in caplog.text
    assert japanese[:3] not in caplog.text
    assert surface not in caplog.text


@pytest.mark.integration
def test_the_last_error_is_one_capped_line(db: Session, study_clock: MutableClock) -> None:
    """`last_error`가 응답 본문을 무제한으로 싣는 경로가 되지 않게 한다.

    parsing 실패의 예외 메시지에는 응답 조각이 들어 있다. 분류 리터럴은 유지하고
    (worker의 `_error_category`가 그것만 로그에 싣는다) 상세는 접어서 자른다.
    """
    user = factories.make_user(db)
    factories.make_learning_item(db)
    _prompt_version(db)
    job = _job(db, user)
    bloated = json.dumps({"sentences": [{"japanese": "あ" * 5_000}]})

    status = _run(db, job, RecordingProvider(responses=[bloated]), study_clock)

    assert status is RETRY
    last_error = _reload(db, job).last_error
    assert last_error is not None
    assert last_error.startswith("invalid response: ")
    assert "\n" not in last_error
    assert len(last_error) <= len("invalid response: ") + observability.MAX_ERROR_LENGTH
