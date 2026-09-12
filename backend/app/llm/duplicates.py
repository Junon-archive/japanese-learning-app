"""Duplicate 검사 11·12의 **순수 부분** (`08_LLM_SPEC.md`).

corpus 조회는 DB를 아는 쪽(`app/jobs/`)이 하고 여기는 비교만 한다(ADR-015).
비교 대상은 `sentences` 전체 중 `status != 'retired'`이며 사용자별로 자르지
않는다 --- `sentences`는 global content다. `quarantined`를 반드시 포함한다.
빼면 사용자가 flag해서 격리한 문장을 다음 generation이 그대로 다시 만들고, 새
id를 받은 그 문장이 `validated`가 되어 다시 Ready로 선택된다.

## `near_original` 면제

`near_original` 목적의 review context는 **의도된 near-duplicate**이므로 12번
(similarity)을 적용하지 않는다. 이걸 일반 duplicate로 지우면 핵심 학습 전략인
의도된 재노출이 통째로 사라진다. 11번(exact hash)은 그대로 적용한다.

면제 여부는 **task와 요청 stage에서 계산한다.** provider 응답에서 읽지 않는다
--- 모델이 "이건 near_original이야"라고 신고하면 스스로 duplicate 검사를 면제받게
된다. 응답 스키마에는 그것을 실을 field 자체가 없다(`app.llm.schemas`).

embedding semantic similarity는 MVP 의무가 아니다.

DB를 모른다(G11(a)). threshold는 인자다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.validation import Rejection, RejectionReason
from app.models.enums import ContextStage, LlmTaskType
from app.normalization import normalized_sentence_hash, similarity_ratio


@dataclass(frozen=True)
class CorpusSentence:
    """비교 대상 한 건. `app/jobs/`가 `sentences` 행에서 만든다."""

    sentence_id: int
    japanese: str
    normalized_hash: str


def skips_similarity_check(*, task_type: LlmTaskType, context_stage: ContextStage | None) -> bool:
    """12번을 건너뛰는가. 요청에서만 계산한다.

    `context_stage`는 `GENERATE_REVIEW_CONTEXT` job의 payload 값이고
    (`08_LLM_SPEC.md`의 `GENERATE_REVIEW_CONTEXT 입력`), 다른 task에서는 None이다.
    """
    return (
        task_type is LlmTaskType.GENERATE_REVIEW_CONTEXT
        and context_stage is ContextStage.NEAR_ORIGINAL
    )


def find_duplicate(
    japanese: str,
    corpus: Sequence[CorpusSentence],
    *,
    similarity_threshold: float,
    skip_similarity: bool,
) -> Rejection | None:
    """검사 11과 12. 통과하면 None이다.

    11번은 `normalized_hash` 동등 비교, 12번은 같은 정규화 문자열끼리의 문자 기반
    유사도이며 threshold를 **초과**할 때만 탈락한다(경계값은 통과).

    corpus 전체를 훑는 O(N) 비교다. 개인 사용 규모에서는 충분하고, 커져서 문제가
    되면 그때 후보를 좁힌다. 지금 좁히는 규칙을 만들면 근거 없는 숫자가 하나 더
    생긴다.

    한 batch 안의 문장끼리도 중복일 수 있다. 그 처리는 호출자가 통과시킨 문장을
    `corpus`에 이어 붙이며 다음 문장을 검사하는 것으로 한다 --- 여기서 batch를
    통째로 받으면 "이미 저장된 것"과 "방금 통과한 것"의 경계가 흐려진다.
    """
    digest = normalized_sentence_hash(japanese)
    for existing in corpus:
        if existing.normalized_hash == digest:
            return Rejection(
                RejectionReason.DUPLICATE_HASH,
                f"normalized_hash matches sentence {existing.sentence_id}",
            )

    if skip_similarity:
        return None

    for existing in corpus:
        ratio = similarity_ratio(japanese, existing.japanese)
        if ratio > similarity_threshold:
            return Rejection(
                RejectionReason.DUPLICATE_SIMILARITY,
                f"similarity {ratio:.4f} with sentence {existing.sentence_id} "
                f"exceeds {similarity_threshold}",
            )
    return None
