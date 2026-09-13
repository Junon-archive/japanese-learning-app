"""생성 결과의 영속화와 `completed` 전이 (`08_LLM_SPEC.md`, ADR-015).

여기가 **콘텐츠를 쓰는 유일한 자리**다. `sentences` / `sentence_items` /
`sentence_item_spans` / `sentence_item_explanations`와 provenance가 한 트랜잭션에서
들어가고, 같은 트랜잭션에서 job이 `completed`가 된다.

## 커밋 지점

`completed`를 콘텐츠 저장과 **같은** 트랜잭션에 둔다. 나누면 저장은 됐는데
`completed`가 아닌 job이 남고, 그 job이 재실행되어 콘텐츠를 두 번 만든다.
`queue.apply_completion()`이 flush만 하고 커밋하지 않는 이유가 이것이며, 그 커밋을
이 모듈이 소유한다.

## Ready invariant (불변식 #6)

`sentences.status = validated`로 올리는 지점은 `_promote_to_validated()` **하나**다.
그 함수는 이미 INSERT된 행을 보고 "tappable인데 validated explanation이 없는
`sentence_item`이 있는가"를 **같은 트랜잭션에서 다시** 묻는다. 판정 SQL은
materialization과 공유한다(`learning.selection.unexplained_sentence_ids`). 위반이면
그 문장의 savepoint를 통째로 되돌리므로 "explanation 없는 validated 문장"이 DB에
생기는 경로 자체가 없다. validation을 통과하지 못한 문장은 `draft`로도 남기지
않는다(`08_LLM_SPEC.md`의 `탈락한 콘텐츠의 처리`).

## at-least-once

worker 실행은 at-least-once이고 DB persistence는 idempotent해야 한다
(`09_BACKGROUND_JOBS.md`). 중복 방지는 세 겹이다.

``` text
1  validation 11번  정규화 해시 corpus 비교          jobs/generate_sentence_batch.py
2  영속화 직전      같은 hash가 이 job의 것이면 이미 저장된 것으로 본다   여기
3  UNIQUE           generation_jobs.idempotency_key  enqueue 시점
```

`normalized_hash`에 UNIQUE 제약을 걸지 않는다. 걸면 crash 후 재시도가
IntegrityError로 죽어 **콘텐츠는 있는데 job은 `failed`인** 더 나쁜 상태가 된다.

## 후리가나 (MVP-02, ADR-021 결정 4)

`_insert_sentence`가 문장 INSERT 직전에 payload의 tappable item(span + `explanation.reading`)으로
`compute_ruby`를 부른다. validation(08_LLM_SPEC.md의 13항목)은 이미 끝났고 ruby는 검증 항목이
아니다. **계산이 던지면 `ruby_json = NULL`로 저장을 계속한다** --- 문장은 그대로 `validated`가
되고 ready를 막지 않는다. `_promote_to_validated`는 `ruby_json`을 보지 않는다. 계산은 요청 로컬
식별자(payload의 item 순번)로 하고, 로그는 flush 뒤 실제 id로 남긴다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.furigana import MismatchKind, RubyComputation, RubyItem, compute_ruby
from app.jobs import observability, queue
from app.learning.selection import unexplained_sentence_ids
from app.llm.provider import ProviderRequest, ProviderResult
from app.llm.schemas import ExplanationPayload, SentencePayload
from app.llm.validation import Rejection, RejectionReason
from app.models.content import (
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.enums import ExplanationStatus, LlmTaskType, SentenceSourceType, SentenceStatus
from app.models.jobs import GenerationJob, PromptVersion
from app.normalization import normalized_sentence_hash
from app.render import ItemSpan

logger = logging.getLogger(__name__)

# 2번 방어가 낸 `duplicate_hash`임을 `detail`에 드러내는 표지.
#
# 사유 **코드**는 `08_LLM_SPEC.md`가 고정한 집합이라 늘리지 않는다. 그래서 11번
# (`llm/duplicates.find_duplicate`)과 이 backstop은 같은 `duplicate_hash`를 낸다. 표지가
# 없으면 corpus 비교가 잡은 건과 여기서 잡은 건을 밖에서 구별할 수 없고, corpus 범위
# 규칙(`load_corpus`의 "`quarantined`를 반드시 포함한다")을 빼도 이 backstop이 같은
# 사유로 잡아 주기 때문에 그 규칙이 **관측 불가능**해진다. `detail`은 집계 단위가 아니라
# 한 건의 진단이므로(`llm/validation.Rejection`) 여기에 단계를 적는다.
DUPLICATE_BACKSTOP_MARKER = "persistence backstop"


class PersistenceError(Exception):
    """저장이 실패했다. 재시도 대상이며 **성공처럼 응답하지 않는다.**

    호출자(`jobs/runner.py`)는 이것을 `record_retryable_failure`로 넘긴다. 세션은
    이미 rollback되어 있으므로 그 다음 상태 전이가 커밋될 수 있다.
    """


class _ReadyInvariantError(Exception):
    """저장 직전 재확인에서 explanation 없는 tappable item이 발견됐다."""


@dataclass(frozen=True)
class Provenance:
    """실제로 실행된 값 (`08_LLM_SPEC.md`의 `Provider 선택과 model 출처`).

    응답이 아니라 worker의 실행 context에서 온다. `provider`/`model`/`prompt_version`은
    `prompt_versions`의 active 행이 정하고 모델이 자기 신고할 자리가 없다.
    """

    provider: str
    model: str
    prompt_version: str
    generated_at: datetime


@dataclass(frozen=True)
class NewSentence:
    """저장할 문장 하나. `payload`는 이미 validation을 통과한 것이다.

    `item_ids`는 요청이 들고 있던 `item_ref -> learning_item_id` 맵이다. 모델이 준
    라벨을 DB id로 되돌리는 유일한 경로이며, **worker는 새 `learning_items`를 만들지
    않는다**(`08_LLM_SPEC.md`의 `worker가 만들지 않는 것`).
    """

    payload: SentencePayload
    item_ids: Mapping[str, int]
    parent_sentence_id: int | None


@dataclass(frozen=True)
class Completion:
    """이 attempt가 저장한 것과 버린 것.

    `stored`가 비어 있으면 job은 `completed`가 아니다 --- 상태 전이는 호출자가
    `queue`에 맡긴다(전량 탈락은 재시도 대상이다).
    """

    stored: tuple[int, ...]
    rejected: tuple[Rejection, ...]


@dataclass(frozen=True)
class NothingToDo:
    """provider를 부를 일이 없는 job. 곧바로 `completed`다.

    대상 item이 0건이거나(`08_LLM_SPEC.md`: "빈 결과는 실패가 아니다"), 이미
    `validated` explanation이 있거나, anchor가 quarantined인 경우다.

    `provenance`도 None이다. 부를 요청이 없으면 provenance를 읽을 이유도 없고
    (handler는 이 경우 `prompt_versions`를 조회하지 않는다), `provider.call` 로그도
    남지 않는다.
    """

    request: ProviderRequest | None = None
    provenance: Provenance | None = None

    def complete(
        self,
        db: Session,
        *,
        job: GenerationJob,
        response: ProviderResult | None,
        now: datetime,
    ) -> Completion:
        return complete_without_content(db, job=job, now=now)


def active_provenance(db: Session, *, task_type: LlmTaskType, now: datetime) -> Provenance | None:
    """`prompt_versions`의 `active = true` 행 하나로 provenance를 만든다.

    **모델명과 provider 이름은 코드가 아니라 이 행에서 온다**(원칙 8). 행이 없으면
    재시도해도 결과가 같으므로 호출자는 그 job을 `dead_letter`로 보낸다.
    """
    row = db.execute(
        sa.select(PromptVersion).where(
            PromptVersion.task_type == task_type,
            PromptVersion.active.is_(True),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return Provenance(
        provider=row.provider,
        model=row.model,
        prompt_version=row.version,
        generated_at=now,
    )


def save_sentences(
    db: Session,
    *,
    job: GenerationJob,
    sentences: Sequence[NewSentence],
    rejected: Sequence[Rejection],
    provenance: Provenance,
    now: datetime,
) -> Completion:
    """통과한 문장을 저장하고 같은 트랜잭션에서 job을 `completed`로 적는다.

    **부분 수용**이다. 3개 중 1개가 탈락해도 나머지 2개를 저장하고 탈락 건수와 사유를
    함께 기록한다. 하나도 저장하지 못하면 `completed`로 적지 않고 사유만 남긴다 ---
    전량 탈락은 재시도 대상이다(`09_BACKGROUND_JOBS.md`).
    """
    stored: list[int] = []
    rejections = list(rejected)
    try:
        for candidate in sentences:
            outcome = _store_one(db, job=job, candidate=candidate, provenance=provenance, now=now)
            if isinstance(outcome, Rejection):
                rejections.append(outcome)
            else:
                stored.append(outcome)
        _finish(db, job=job, now=now, stored=stored, key="sentence_ids", rejections=rejections)
    except SQLAlchemyError as error:
        db.rollback()
        raise PersistenceError(f"generated content could not be stored: {error}") from error
    return Completion(tuple(stored), tuple(rejections))


def save_explanation(
    db: Session,
    *,
    job: GenerationJob,
    sentence_item_id: int,
    explanation: ExplanationPayload,
    provenance: Provenance,
    now: datetime,
) -> Completion:
    """`EXPLAIN_ITEM`의 결과를 `validated`로 저장하고 job을 `completed`로 적는다.

    문장을 새로 만들지 않는다. 이미 `validated` explanation이 있으면 호출자가 애초에
    provider를 부르지 않으므로(`NothingToDo`) 여기서 다시 확인하지 않는다 --- 그
    사이에 다른 attempt가 넣었다면 행이 둘이 되지만, 둘 다 같은 item의 유효한
    설명이고 Ready invariant는 "하나라도 있는가"를 묻는다.
    """
    try:
        row = SentenceItemExplanation(
            sentence_item_id=sentence_item_id,
            reading=explanation.reading,
            core_meaning=explanation.core_meaning,
            meaning_in_context=explanation.meaning_in_context,
            nuance=explanation.nuance,
            example_sentence=explanation.example_sentence,
            example_translation=explanation.example_translation,
            provider=provenance.provider,
            model=provenance.model,
            prompt_version=provenance.prompt_version,
            generated_at=provenance.generated_at,
            status=ExplanationStatus.VALIDATED,
        )
        db.add(row)
        db.flush()
        explanation_id = row.id
        _finish(
            db,
            job=job,
            now=now,
            stored=[explanation_id],
            key="sentence_item_explanation_ids",
            rejections=[],
        )
    except SQLAlchemyError as error:
        db.rollback()
        raise PersistenceError(f"explanation could not be stored: {error}") from error
    return Completion((explanation_id,), ())


def complete_without_content(db: Session, *, job: GenerationJob, now: datetime) -> Completion:
    """만들 것이 없었던 job을 `completed`로 끝낸다. 빈 결과는 실패가 아니다."""
    try:
        queue.apply_completion(db, job=job, now=now, result={"sentence_ids": [], "rejected": []})
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise PersistenceError(f"job could not be completed: {error}") from error
    return Completion((), ())


def record_rejections(
    db: Session, *, job: GenerationJob, rejected: Sequence[Rejection]
) -> Completion:
    """저장할 것이 하나도 없다. 사유만 남기고 상태는 호출자가 정한다."""
    try:
        _log_rejections(job=job, rejections=rejected)
        queue.record_rejections(db, job=job, rejected=[_rejection(item) for item in rejected])
    except SQLAlchemyError as error:
        db.rollback()
        raise PersistenceError(f"rejections could not be recorded: {error}") from error
    return Completion((), tuple(rejected))


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _finish(
    db: Session,
    *,
    job: GenerationJob,
    now: datetime,
    stored: Sequence[int],
    key: str,
    rejections: Sequence[Rejection],
) -> None:
    """저장 결과를 `result_ref`에 적고 **한 번** 커밋한다.

    `stored`가 비어 있으면 `completed`로 적지 않는다. 저장된 콘텐츠가 없는 attempt를
    성공으로 끝내면 그 job은 다시 돌지 않고, 비어 있는 pool은 그대로 남는다.
    """
    _log_rejections(job=job, rejections=rejections)
    rejected = [_rejection(item) for item in rejections]
    if not stored:
        queue.record_rejections(db, job=job, rejected=rejected)
        return
    queue.apply_completion(db, job=job, now=now, result={key: list(stored), "rejected": rejected})
    db.commit()


def _store_one(
    db: Session,
    *,
    job: GenerationJob,
    candidate: NewSentence,
    provenance: Provenance,
    now: datetime,
) -> int | Rejection:
    """문장 하나를 저장하고 id를 돌려준다. 저장하지 않았으면 사유를 돌려준다.

    at-least-once 2번 방어가 여기다. 같은 `normalized_hash`가 이미 있고 그것이 **이
    job이 만든 것**이면 이전 attempt가 이미 저장한 것으로 보고 성공 처리한다. 다른
    job의 것이면 corpus 비교(11번)가 놓친 duplicate이므로 탈락이다.

    그 탈락의 `detail`에는 `DUPLICATE_BACKSTOP_MARKER`를 붙인다. 11번과 사유 코드가
    같아서, 표지가 없으면 "corpus가 잡았는가 backstop이 잡았는가"를 구별할 수 없다.

    `sentences.status`는 보지 않는다. 여기서 묻는 것은 "이 hash가 DB에 이미 있는가"이고
    그 답은 상태와 무관하다. `quarantined`를 빼면 사용자가 격리한 문장의 복제가
    저장되고(불변식 #7), `retired`를 빼면 재실행 idempotency가 상태 변화에 흔들린다.
    """
    digest = normalized_sentence_hash(candidate.payload.japanese)
    existing = db.execute(
        sa.select(Sentence.id, Sentence.generation_job_id)
        .where(Sentence.normalized_hash == digest)
        .order_by(Sentence.id)
    ).first()
    if existing is not None:
        sentence_id, generation_job_id = existing
        if generation_job_id == job.id:
            return int(sentence_id)
        return Rejection(
            RejectionReason.DUPLICATE_HASH,
            f"normalized_hash matches sentence {sentence_id} ({DUPLICATE_BACKSTOP_MARKER})",
        )

    try:
        with db.begin_nested():
            return _insert_sentence(
                db, job=job, candidate=candidate, digest=digest, provenance=provenance, now=now
            )
    except _ReadyInvariantError as error:
        # savepoint가 통째로 되돌아갔다. 이 문장의 어떤 행도 DB에 남지 않는다.
        return Rejection(RejectionReason.MISSING_EXPLANATION, str(error))


def _insert_sentence(
    db: Session,
    *,
    job: GenerationJob,
    candidate: NewSentence,
    digest: str,
    provenance: Provenance,
    now: datetime,
) -> int:
    payload = candidate.payload
    ruby, ruby_error = _compute_ruby(payload, now=now)
    sentence = Sentence(
        japanese=payload.japanese,
        korean_translation=payload.korean_translation,
        source_type=SentenceSourceType.GENERATED,
        difficulty_json={"label": payload.difficulty_label.value},
        provenance_json=_provenance_json(provenance, parent=candidate.parent_sentence_id),
        generation_job_id=job.id,
        parent_sentence_id=candidate.parent_sentence_id,
        normalized_hash=digest,
        # `validated`로 올리는 것은 `_promote_to_validated` 하나뿐이다. 그 함수가
        # 같은 트랜잭션에서 Ready invariant를 다시 확인한다.
        status=SentenceStatus.DRAFT,
        ruby_json=None if ruby is None else ruby.ruby_json,
        created_at=now,
    )
    db.add(sentence)
    db.flush()

    sentence_item_ids: list[int] = []
    for item in payload.items:
        sentence_item = SentenceItem(
            sentence_id=sentence.id,
            learning_item_id=candidate.item_ids[item.item_ref],
            surface_form=item.surface_form,
            is_tappable=item.is_tappable,
            created_at=now,
        )
        db.add(sentence_item)
        db.flush()
        sentence_item_ids.append(sentence_item.id)
        for span in item.spans:
            db.add(
                SentenceItemSpan(
                    sentence_item_id=sentence_item.id,
                    start_codepoint=span.start_codepoint,
                    end_codepoint=span.end_codepoint,
                    span_order=span.span_order,
                )
            )
        if item.explanation is not None:
            db.add(
                SentenceItemExplanation(
                    sentence_item_id=sentence_item.id,
                    reading=item.explanation.reading,
                    core_meaning=item.explanation.core_meaning,
                    meaning_in_context=item.explanation.meaning_in_context,
                    nuance=item.explanation.nuance,
                    example_sentence=item.explanation.example_sentence,
                    example_translation=item.explanation.example_translation,
                    provider=provenance.provider,
                    model=provenance.model,
                    prompt_version=provenance.prompt_version,
                    generated_at=provenance.generated_at,
                    status=ExplanationStatus.VALIDATED,
                )
            )
    db.flush()
    _promote_to_validated(db, sentence=sentence)
    _log_ruby(
        sentence_id=sentence.id,
        ruby=ruby,
        error=ruby_error,
        sentence_item_ids=sentence_item_ids,
    )
    return sentence.id


def _compute_ruby(
    payload: SentencePayload, *, now: datetime
) -> tuple[RubyComputation | None, Exception | None]:
    """tappable item으로 ruby를 계산한다. 실패하면 `(None, 예외)` --- 저장은 계속한다.

    `RubyItem.sentence_item_id`에는 payload 안의 item **순번**을 넣는다. 아직 DB id가 없고,
    `item_ref`는 한 문장에서 겹칠 수 있는 요청 라벨이다. 순번은 `_log_ruby`에서 실제 id로 바뀐다.
    tappable item의 explanation은 validation이 보장한다. 없으면 `_promote_to_validated`가 그
    문장을 되돌리므로 여기서는 빈 읽기(계층 1 불성립)로만 다룬다.
    """
    items = [
        RubyItem(
            sentence_item_id=index,
            spans=tuple(
                ItemSpan(span.start_codepoint, span.end_codepoint, span.span_order)
                for span in item.spans
            ),
            explanation_reading="" if item.explanation is None else item.explanation.reading,
        )
        for index, item in enumerate(payload.items)
        if item.is_tappable
    ]
    try:
        return compute_ruby(payload.japanese, items, now=now), None
    except Exception as error:
        return None, error


_MISMATCH_EVENTS: Mapping[MismatchKind, str] = {
    MismatchKind.READING_MISMATCH: observability.RUBY_READING_MISMATCH,
    MismatchKind.EXPLANATION_OVERRIDE: observability.RUBY_EXPLANATION_OVERRIDE,
}


def _log_ruby(
    *,
    sentence_id: int,
    ruby: RubyComputation | None,
    error: Exception | None,
    sentence_item_ids: Sequence[int],
) -> None:
    if ruby is None:
        if error is not None:
            observability.log_ruby_failed(sentence_id=sentence_id, error=error)
        return
    observability.log_ruby_computed(
        sentence_id=sentence_id,
        algorithm_version=int(ruby.ruby_json["algorithm_version"]),
        spans=len(ruby.spans),
        omitted_tappable_boundary=ruby.omitted_tappable_boundary,
        omitted_numeric=ruby.omitted_numeric,
        omitted_no_reading=ruby.omitted_no_reading,
        corrected_explanation_tokens=ruby.corrected_explanation_tokens,
        corrected_table_rules=ruby.corrected_table_rules,
    )
    for mismatch in ruby.mismatches:
        observability.log_ruby_mismatch(
            event=_MISMATCH_EVENTS[mismatch.kind],
            sentence_id=sentence_id,
            sentence_item_id=sentence_item_ids[int(mismatch.sentence_item_id)],
        )


def _promote_to_validated(db: Session, *, sentence: Sentence) -> None:
    """`sentences.status = validated`로 올리는 **유일한** 함수 (불변식 #6).

    올리기 전에 저장된 행을 보고 Ready invariant를 다시 묻는다. in-memory payload가
    아니라 DB를 보는 이유는, 검사하는 대상이 정확히 "방금 INSERT가 실제로 무엇을
    남겼는가"이기 때문이다. explanation을 빠뜨린 코드 경로는 payload 검사로는
    보이지 않는다.
    """
    missing = db.execute(
        unexplained_sentence_ids().where(SentenceItem.sentence_id == sentence.id)
    ).first()
    if missing is not None:
        raise _ReadyInvariantError(
            f"tappable sentence_item {missing[0]} has no validated explanation"
        )
    sentence.status = SentenceStatus.VALIDATED
    db.flush()


def _provenance_json(provenance: Provenance, *, parent: int | None) -> dict[str, Any]:
    """`sentences.provenance_json`. `parent_sentence_id`는 near_original일 때만 있다."""
    recorded: dict[str, Any] = {
        "provider": provenance.provider,
        "model": provenance.model,
        "prompt_version": provenance.prompt_version,
        "generated_at": provenance.generated_at.isoformat(),
    }
    if parent is not None:
        recorded["parent_sentence_id"] = parent
    return recorded


def _rejection(rejection: Rejection) -> dict[str, str]:
    return {"reason": rejection.reason.value, "detail": rejection.detail}


def _log_rejections(*, job: GenerationJob, rejections: Sequence[Rejection]) -> None:
    """사유 **코드**는 `result_ref`와 로그 둘 다에 남는다(`08_LLM_SPEC.md`).

    `detail`은 로그에 싣지 않는다. 그 문자열에는 생성된 문장 조각이 들어간다 --- 검사
    6의 사유는 `app.render`의 `spans cover '...' but surface_form is '...'`를 그대로
    담고 앞의 따온 값은 응답 문장의 slice다(검사 13은 모델이 지어낸 `item_ref`를
    담는다). `11_OBSERVABILITY.md`와 `04_SECURITY_AND_DATA.md`는 provider 응답 원문을
    로그에 남기지 않는다. 진단은 `result_ref.rejected`(DB)에서 한다 --- 집계 단위인
    사유 코드는 여기 있고, 개별 detail은 그 job 행에 있다.
    """
    for rejection in rejections:
        logger.info("generation job %s rejected content: %s", job.id, rejection.reason.value)
