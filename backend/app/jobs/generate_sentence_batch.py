"""`GENERATE_SENTENCE_BATCH` handler (`08_LLM_SPEC.md`).

payload는 `{user_id, presentation_role}` **둘뿐**이고 대상 item은 worker가 실행
시점에 다시 계산한다. replenishment의 `idempotency_key`가 하루 창이고 enqueue가
`ON CONFLICT DO NOTHING`이라, payload에 item 목록을 넣으면 그날 첫 job의 목록이
그대로 굳어 실행 시점에는 이미 낡는다.

## 이 모듈이 두 task를 겸하는 이유

`SentencePlan`과 응답 처리(`complete`)를 `GENERATE_REVIEW_CONTEXT`
(`jobs/review_context.py`)와 공유한다. 두 task는 **같은 응답 스키마**를 쓰고 차이는
요청 context와 저장 시 lineage(`parent_sentence_id`)·similarity 면제뿐이다
(`08_LLM_SPEC.md`). 응답 처리를 복제하면 duplicate 누적이나 부분 수용 규칙이 한쪽
에서만 고쳐진다.

## batch 안의 중복

`find_duplicate`는 문장 **하나**를 corpus와 비교한다. 그래서 통과한 문장을 corpus에
이어 붙이며 다음 문장을 검사한다. 이것을 빼면 같은 응답에 두 번 들어온 같은 문장이
둘 다 저장된다.

commit하지 않는다(G7). 상태 전이는 `jobs/queue.py`, 저장은 `jobs/persistence.py`다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.jobs import persistence, queue
from app.jobs.persistence import Completion, NewSentence, NothingToDo, Provenance
from app.learning.exploration import eligible_exploration_targets, exploration_sort_key
from app.learning.exposure import count_valid_exposures
from app.learning.selection import has_ready_sentence
from app.llm.duplicates import CorpusSentence, find_duplicate
from app.llm.prompts import UnknownPromptVersionError
from app.llm.provider import ProviderRequest, ProviderResult
from app.llm.schemas import SentencePayload
from app.llm.tasks import (
    SentenceBatchInput,
    TargetItem,
    build_sentence_batch_request,
    item_ref,
    parse_sentence_batch,
    requested_refs,
)
from app.llm.validation import Rejection, SentencePolicy, ValidatedSentence, validate_sentence
from app.models.content import LearningItem, Sentence, SentenceItem
from app.models.enums import LlmTaskType, PresentationRole, SentenceStatus
from app.models.jobs import GenerationJob
from app.models.learning import ReviewState, UserItemLearningState, UserMastery
from app.models.user import User
from app.normalization import normalized_sentence_hash

TASK_TYPE = LlmTaskType.GENERATE_SENTENCE_BATCH


@dataclass(frozen=True)
class SentencePlan:
    """provider 응답이 문장 batch인 두 task의 실행 계획.

    `corpus`와 정책값은 **provider 호출 전에** 모아 둔 값이다. 응답 처리 중에 DB를
    다시 읽지 않으므로 validation 구간에 트랜잭션이 열리지 않는다(ADR-015).

    `skip_similarity`는 **task와 요청 stage에서 계산한 값**이다. 응답 필드에서 받지
    않는다 --- 모델이 "이건 near_original이야"라고 신고하면 스스로 중복 검사를
    면제받게 된다(`app.llm.duplicates`).
    """

    request: ProviderRequest | None
    provenance: Provenance
    policy: SentencePolicy
    corpus: tuple[CorpusSentence, ...]
    requested_refs: frozenset[str]
    new_refs: frozenset[str]
    item_ids: Mapping[str, int]
    similarity_threshold: float
    skip_similarity: bool
    parent_sentence_id: int | None

    def complete(
        self,
        db: Session,
        *,
        job: GenerationJob,
        response: ProviderResult | None,
        now: datetime,
    ) -> Completion:
        """응답을 검증하고 통과한 문장을 저장한다.

        `mark_validated`는 **하나라도 통과했을 때만** 찍는다. 전량 탈락은 검증을
        통과한 것이 아니고 그 job은 재시도 대상이다(`09_BACKGROUND_JOBS.md`).
        """
        if response is None:  # pragma: no cover - runner가 request=None일 때만 부른다
            return persistence.complete_without_content(db, job=job, now=now)

        batch = parse_sentence_batch(response.text)
        accepted, rejected = self._screen(batch.sentences)
        if not accepted:
            return persistence.record_rejections(db, job=job, rejected=rejected)

        queue.mark_validated(db, job=job)
        return persistence.save_sentences(
            db,
            job=job,
            sentences=accepted,
            rejected=rejected,
            provenance=self.provenance,
            now=now,
        )

    def _screen(
        self, sentences: Sequence[SentencePayload]
    ) -> tuple[list[NewSentence], list[Rejection]]:
        """검사 2~13. 통과한 문장은 다음 문장의 비교 corpus에 이어 붙인다."""
        corpus = list(self.corpus)
        accepted: list[NewSentence] = []
        rejected: list[Rejection] = []

        for index, payload in enumerate(sentences):
            checked = validate_sentence(
                payload,
                requested_refs=self.requested_refs,
                new_refs=self.new_refs,
                policy=self.policy,
            )
            if isinstance(checked, Rejection):
                rejected.append(checked)
                continue
            duplicate = find_duplicate(
                checked.sentence.japanese,
                corpus,
                similarity_threshold=self.similarity_threshold,
                skip_similarity=self.skip_similarity,
            )
            if duplicate is not None:
                rejected.append(duplicate)
                continue
            accepted.append(self._new_sentence(checked))
            corpus.append(_batch_local(checked.sentence.japanese, index=index))

        return accepted, rejected

    def _new_sentence(self, checked: ValidatedSentence) -> NewSentence:
        return NewSentence(
            payload=checked.sentence,
            item_ids=self.item_ids,
            parent_sentence_id=self.parent_sentence_id,
        )


def prepare(
    db: Session, *, job: GenerationJob, cfg: AppConfig, now: datetime
) -> SentencePlan | NothingToDo | queue.PermanentReason:
    """실행 시점에 대상 item을 다시 계산하고 요청을 조립한다. DB 읽기만 한다."""
    payload = job.payload_json or {}
    user_id = payload.get("user_id")
    role = _role(payload.get("presentation_role"))
    if not isinstance(user_id, int) or role is None:
        return queue.PermanentReason.INVALID_PAYLOAD

    user = db.get(User, user_id)
    if user is None:
        return queue.PermanentReason.MISSING_REFERENCE

    provenance = persistence.active_provenance(db, task_type=TASK_TYPE, now=now)
    if provenance is None:
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    targets = _generation_targets(db, user=user, role=role, cfg=cfg, now=now)
    if not targets:
        # 대상이 0건이면 provider를 부르지 않는다. 빈 결과는 실패가 아니다.
        return NothingToDo()

    labels = [item_ref(index) for index in range(len(targets))]
    request_input = SentenceBatchInput(
        learner_level=user.starting_level.value,
        targets=tuple(
            target_item(item, label=label) for label, item in zip(labels, targets, strict=True)
        ),
        preferred_targets_per_sentence=cfg.learning.preferred_new_items_per_sentence,
        max_targets_per_sentence=cfg.learning.max_new_items_per_sentence,
        max_sentence_length_chars=cfg.content.max_sentence_length_chars,
        avoid_japanese=tuple(
            japanese
            for item in targets
            for japanese in avoid_examples(
                db, learning_item_id=item.id, limit=cfg.llm.avoid_examples_per_item
            )
        ),
    )
    try:
        request = build_sentence_batch_request(
            request_input,
            model=provenance.model,
            prompt_version=provenance.prompt_version,
        )
    except UnknownPromptVersionError:
        # active 행이 가리키는 version의 본문이 코드에 없다. 재시도해도 같다.
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    item_ids = {label: item.id for label, item in zip(labels, targets, strict=True)}
    return SentencePlan(
        request=request,
        provenance=provenance,
        policy=sentence_policy(cfg),
        corpus=load_corpus(db, exclude_job_id=job.id),
        requested_refs=requested_refs(request_input.targets),
        new_refs=new_item_refs(db, user_id=user.id, item_ids=item_ids),
        item_ids=item_ids,
        similarity_threshold=cfg.content.duplicate_similarity_threshold,
        skip_similarity=False,
        parent_sentence_id=None,
    )


# --------------------------------------------------------------------------
# 두 sentence task가 공유하는 조회 (review_context.py도 쓴다)
# --------------------------------------------------------------------------


def sentence_policy(cfg: AppConfig) -> SentencePolicy:
    """검사 3·5·10의 정책값. 숫자는 전부 config에서 온다."""
    return SentencePolicy(
        max_sentence_length_chars=cfg.content.max_sentence_length_chars,
        max_targets_per_sentence=cfg.learning.max_new_items_per_sentence,
        max_new_items_per_sentence=cfg.learning.max_new_items_per_sentence,
    )


def load_corpus(db: Session, *, exclude_job_id: int | None) -> tuple[CorpusSentence, ...]:
    """검사 11·12의 비교 corpus (`08_LLM_SPEC.md`의 `duplicate 비교 corpus`).

    `status != 'retired'`인 `sentences` **전체**이며 사용자별로 자르지 않는다 ---
    `sentences`는 global content다. `quarantined`를 반드시 포함한다. 빼면 사용자가
    flag해서 격리한 문장을 다음 generation이 그대로 다시 만들고, 새 id를 받은 그
    문장이 `validated`가 되어 다시 Ready로 선택된다.

    `exclude_job_id`가 만든 문장만 뺀다. at-least-once로 같은 job이 다시 돌 때 자기가
    이미 저장한 문장을 duplicate로 보면, 그 job은 영원히 전량 탈락으로 재시도하다가
    `failed`가 된다. 그 재실행의 중복 방지는 `persistence`의 hash 대조가 한다.
    """
    statement = sa.select(Sentence.id, Sentence.japanese, Sentence.normalized_hash).where(
        Sentence.status != SentenceStatus.RETIRED
    )
    if exclude_job_id is not None:
        statement = statement.where(
            sa.or_(
                Sentence.generation_job_id.is_(None),
                Sentence.generation_job_id != exclude_job_id,
            )
        )
    return tuple(
        CorpusSentence(sentence_id=sentence_id, japanese=japanese, normalized_hash=digest)
        for sentence_id, japanese, digest in db.execute(statement.order_by(Sentence.id)).all()
    )


def avoid_examples(db: Session, *, learning_item_id: int, limit: int) -> list[str]:
    """그 item이 이미 등장한 기존 문장의 `japanese`. 중복 생성을 줄이는 **힌트**다.

    실제 판정은 deterministic duplicate 검사가 한다(`08_LLM_SPEC.md`).
    """
    statement = (
        sa.select(Sentence.japanese)
        .join(SentenceItem, SentenceItem.sentence_id == Sentence.id)
        .where(
            SentenceItem.learning_item_id == learning_item_id,
            Sentence.status != SentenceStatus.RETIRED,
        )
        .distinct()
        .order_by(Sentence.japanese)
        .limit(limit)
    )
    return list(db.execute(statement).scalars().all())


def new_item_refs(db: Session, *, user_id: int, item_ids: Mapping[str, int]) -> frozenset[str]:
    """검사 10이 세는 "신규 target". 판정은 materialization과 같다.

    "그 사용자에게 `review_states` 행이 없으면 신규"
    (`06_LEARNING_ENGINE.md`의 `공통 필드`).
    """
    if not item_ids:
        return frozenset()
    known = set(
        db.execute(
            sa.select(ReviewState.learning_item_id).where(
                ReviewState.user_id == user_id,
                ReviewState.learning_item_id.in_(set(item_ids.values())),
            )
        )
        .scalars()
        .all()
    )
    return frozenset(label for label, item_id in item_ids.items() if item_id not in known)


def target_item(item: LearningItem, *, label: str) -> TargetItem:
    """요청에 싣는 target. DB id를 싣지 않는다 --- 되돌림은 `item_ref` 맵이 한다."""
    return TargetItem(
        item_ref=label,
        item_type=item.type.value,
        lemma=item.lemma,
        reading=item.reading,
        default_meaning=item.default_meaning,
    )


# --------------------------------------------------------------------------
# 대상 선정 (`08_LLM_SPEC.md`의 `GENERATE_SENTENCE_BATCH 대상 선정`)
# --------------------------------------------------------------------------


def _generation_targets(
    db: Session, *, user: User, role: PresentationRole, cfg: AppConfig, now: datetime
) -> list[LearningItem]:
    """role별 대상 조건·정렬 + "Ready 문장이 0건" 조건. 앞에서 최대 batch 크기만큼.

    조건은 `06_LEARNING_ENGINE.md`의 role별 규칙을 그대로 쓰고, 거기에 **그 item을
    포함하면서 Ready invariant를 만족하는 문장이 0건**을 추가로 건다. 문장이 이미
    있는 item에 새 문장을 만들면 pool이 아니라 비용만 는다.

    문장은 있는데 현재 `context_stage` 조건에 맞는 것만 없는 경우는 이 job이 아니라
    `GENERATE_REVIEW_CONTEXT`가 맡는다. 두 job의 경계가 이것이다.
    """
    ordered = _role_targets(db, user=user, role=role, cfg=cfg, now=now)
    chosen: list[LearningItem] = []
    for item in ordered:
        if has_ready_sentence(db, learning_item_id=item.id):
            continue
        chosen.append(item)
        if len(chosen) >= cfg.llm.sentences_per_batch:
            break
    return chosen


def _role_targets(
    db: Session, *, user: User, role: PresentationRole, cfg: AppConfig, now: datetime
) -> list[LearningItem]:
    if role is PresentationRole.EXPLORATION:
        return _exploration_targets(db, user=user, cfg=cfg, now=now)
    if role is PresentationRole.NEW:
        return _new_targets(db, user_id=user.id)
    return _review_targets(db, user_id=user.id)


def _exploration_targets(
    db: Session, *, user: User, cfg: AppConfig, now: datetime
) -> list[LearningItem]:
    """`Exploration Item 선정`의 후보 조건과 3단 정렬을 그대로 쓴다."""
    items = list(db.execute(sa.select(LearningItem)).scalars().all())
    eligible = eligible_exploration_targets(
        db,
        user_id=user.id,
        item_ids=[item.id for item in items],
        now=now,
        recent_days=cfg.learning.exploration_recent_days,
    )
    return sorted(
        (item for item in items if item.id in eligible),
        key=lambda item: exploration_sort_key(item, starting_level=user.starting_level),
    )


def _new_targets(db: Session, *, user_id: int) -> list[LearningItem]:
    """`is_active_learning_target = true`이고 유효 exposure가 0건인 item (ADR-013)."""
    statement = (
        sa.select(LearningItem)
        .join(
            UserItemLearningState,
            UserItemLearningState.learning_item_id == LearningItem.id,
        )
        .where(
            UserItemLearningState.user_id == user_id,
            UserItemLearningState.is_active_learning_target.is_(True),
        )
        .order_by(LearningItem.id)
    )
    return [
        item
        for item in db.execute(statement).scalars().all()
        if count_valid_exposures(db, user_id=user_id, learning_item_id=item.id) == 0
    ]


def _review_targets(db: Session, *, user_id: int) -> list[LearningItem]:
    """`review_states` 행이 있고 유효 exposure가 1건 이상인 item.

    정렬은 Review Ordering과 같은 `next_review_at ASC -> mastery ASC(NULL이 가장
    낮다) -> learning_item_id ASC`이며, canonical 정의는
    `06_LEARNING_ENGINE.md`다. 여기서는 같은 순서를 SQL로 표현한다.
    """
    statement = (
        sa.select(LearningItem)
        .join(ReviewState, ReviewState.learning_item_id == LearningItem.id)
        .outerjoin(
            UserMastery,
            sa.and_(
                UserMastery.user_id == ReviewState.user_id,
                UserMastery.learning_item_id == ReviewState.learning_item_id,
            ),
        )
        .where(ReviewState.user_id == user_id)
        .order_by(
            ReviewState.next_review_at,
            UserMastery.comprehension_mastery.nulls_first(),
            LearningItem.id,
        )
    )
    return [
        item
        for item in db.execute(statement).scalars().all()
        if count_valid_exposures(db, user_id=user_id, learning_item_id=item.id) > 0
    ]


# --------------------------------------------------------------------------
# 내부
# --------------------------------------------------------------------------


def _role(value: object) -> PresentationRole | None:
    return next((role for role in PresentationRole if role.value == value), None)


def _batch_local(japanese: str, *, index: int) -> CorpusSentence:
    """이번 batch에서 방금 통과한 문장. 아직 DB에 없으므로 id가 음수다."""
    return CorpusSentence(
        sentence_id=-(index + 1),
        japanese=japanese,
        normalized_hash=normalized_sentence_hash(japanese),
    )
