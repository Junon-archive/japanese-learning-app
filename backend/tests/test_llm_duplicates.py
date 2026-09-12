"""Duplicate 검사 11·12의 순수 부분 (08_LLM_SPEC.md의 `duplicate 비교 corpus`).

DB를 쓰지 않는다. corpus는 인자다. `make test-unit`에 들어간다.
"""

from __future__ import annotations

import pytest

from app.llm.duplicates import CorpusSentence, find_duplicate, skips_similarity_check
from app.llm.validation import Rejection, RejectionReason
from app.models.enums import ContextStage, LlmTaskType
from app.normalization import normalized_sentence_hash, similarity_ratio

ANCHOR = "昨日は駅で友達に会いました。"
THRESHOLD = 0.90


def corpus(*sentences: str) -> tuple[CorpusSentence, ...]:
    return tuple(
        CorpusSentence(
            sentence_id=index,
            japanese=japanese,
            normalized_hash=normalized_sentence_hash(japanese),
        )
        for index, japanese in enumerate(sentences, start=1)
    )


def duplicate(
    japanese: str,
    *,
    existing: tuple[CorpusSentence, ...],
    skip_similarity: bool = False,
) -> Rejection | None:
    return find_duplicate(
        japanese,
        existing,
        similarity_threshold=THRESHOLD,
        skip_similarity=skip_similarity,
    )


# --------------------------------------------------------------------------
# 11  duplicate_hash
# --------------------------------------------------------------------------


def test_11_exact_duplicate() -> None:
    rejection = duplicate(ANCHOR, existing=corpus(ANCHOR))
    assert rejection is not None
    assert rejection.reason is RejectionReason.DUPLICATE_HASH


def test_11_whitespace_and_width_fold_into_the_same_hash() -> None:
    """정규화 규칙은 seed 적재와 같은 함수 하나에서 온다."""
    rejection = duplicate("昨日は 駅で友達に会いました。", existing=corpus(ANCHOR))
    assert rejection is not None
    assert rejection.reason is RejectionReason.DUPLICATE_HASH


def test_11_an_empty_corpus_rejects_nothing() -> None:
    assert duplicate(ANCHOR, existing=()) is None


# --------------------------------------------------------------------------
# 12  duplicate_similarity
# --------------------------------------------------------------------------


def test_12_similarity_threshold_boundary() -> None:
    """threshold를 **초과**할 때만 탈락한다. 경계값 자체는 통과한다."""
    near = "昨日は駅で友達に会いました"
    ratio = similarity_ratio(near, ANCHOR)
    assert 0.0 < ratio < 1.0

    below = find_duplicate(near, corpus(ANCHOR), similarity_threshold=ratio, skip_similarity=False)
    assert below is None

    above = find_duplicate(
        near, corpus(ANCHOR), similarity_threshold=ratio - 0.01, skip_similarity=False
    )
    assert above is not None
    assert above.reason is RejectionReason.DUPLICATE_SIMILARITY


def test_12_an_unrelated_sentence_passes() -> None:
    assert duplicate("猫が好きです。", existing=corpus(ANCHOR)) is None


# --------------------------------------------------------------------------
# near_original 면제
# --------------------------------------------------------------------------


def test_near_original_is_exempt_from_similarity_only() -> None:
    """의도된 near-duplicate를 일반 중복으로 지우면 핵심 학습 전략이 깨진다."""
    near = "今日は駅で友達に会いました。"
    assert similarity_ratio(near, ANCHOR) > THRESHOLD

    assert duplicate(near, existing=corpus(ANCHOR), skip_similarity=True) is None

    # 그래도 완전히 같은 문장은 만들지 않는다. 11번은 그대로 적용된다.
    exact = duplicate(ANCHOR, existing=corpus(ANCHOR), skip_similarity=True)
    assert exact is not None
    assert exact.reason is RejectionReason.DUPLICATE_HASH


def test_the_same_text_is_rejected_in_an_ordinary_batch() -> None:
    """면제는 `near_original`에만 붙는다. 같은 텍스트라도 일반 batch에서는 탈락한다."""
    near = "今日は駅で友達に会いました。"
    rejection = duplicate(near, existing=corpus(ANCHOR), skip_similarity=False)
    assert rejection is not None
    assert rejection.reason is RejectionReason.DUPLICATE_SIMILARITY


@pytest.mark.parametrize(
    ("task_type", "context_stage", "expected"),
    [
        (LlmTaskType.GENERATE_REVIEW_CONTEXT, ContextStage.NEAR_ORIGINAL, True),
        (LlmTaskType.GENERATE_REVIEW_CONTEXT, ContextStage.VARIED, False),
        (LlmTaskType.GENERATE_REVIEW_CONTEXT, ContextStage.NEW_CONTEXT, False),
        (LlmTaskType.GENERATE_REVIEW_CONTEXT, ContextStage.ANCHOR, False),
        (LlmTaskType.GENERATE_SENTENCE_BATCH, ContextStage.NEAR_ORIGINAL, False),
        (LlmTaskType.GENERATE_SENTENCE_BATCH, None, False),
        (LlmTaskType.EXPLAIN_ITEM, None, False),
    ],
)
def test_exemption_is_computed_from_the_request(
    task_type: LlmTaskType, context_stage: ContextStage | None, expected: bool
) -> None:
    """면제 판단의 입력은 task와 요청 stage뿐이다.

    provider 응답에서 읽으면 모델이 "이건 near_original이야"라고 신고해 스스로
    검사를 면제받는다. 응답 스키마에 그 field가 없다는 것은
    `test_llm_schemas.py`가 함께 고정한다.
    """
    assert skips_similarity_check(task_type=task_type, context_stage=context_stage) is expected


def test_exemption_needs_both_the_task_and_the_stage() -> None:
    """`GENERATE_SENTENCE_BATCH`는 stage를 갖지 않으므로 어떤 값으로도 면제되지 않는다."""
    exempt = [
        (task_type, stage)
        for task_type in LlmTaskType
        for stage in (*ContextStage, None)
        if skips_similarity_check(task_type=task_type, context_stage=stage)
    ]
    assert exempt == [(LlmTaskType.GENERATE_REVIEW_CONTEXT, ContextStage.NEAR_ORIGINAL)]
