"""`GENERATE_REVIEW_CONTEXT` handler (`08_LLM_SPEC.md`).

payload는 `{user_id, learning_item_id, context_stage, anchor_sentence_id}`이고 응답
스키마는 `GENERATE_SENTENCE_BATCH`와 **같으며** `sentences`는 1개다. 그래서 응답
처리는 `jobs/generate_sentence_batch.SentencePlan`을 그대로 쓴다. 다른 것은 요청
context와 저장 시 lineage뿐이다.

``` text
near_original  anchor를 요청에 싣고 "표현 유지, 주변 문맥만 최소 변경"을 지시한다
               parent_sentence_id = anchor,  similarity(12번) 면제
varied         anchor와 다른 상황.  parent_sentence_id = NULL
new_context    varied와 같다.       parent_sentence_id = NULL
```

**면제는 task와 요청 stage에서 계산한다.** provider 응답 필드에서 받지 않는다 ---
모델이 스스로 중복 검사를 면제받게 된다. 계산은
`app.llm.duplicates.skips_similarity_check` 하나가 한다. exact hash(11번)는
near_original에도 그대로 적용한다.

**불변식 #7**: `anchor_sentence_id`가 quarantined면 이 job은 콘텐츠를 만들지 않고
끝난다. anchor 재지정은 request 경로(materialization)의 소관이고 worker가 그것을
흉내내면 같은 item의 학습 문맥을 두 곳에서 바꾸게 된다.

commit하지 않는다(G7).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.config import AppConfig
from app.jobs import persistence, queue
from app.jobs.generate_sentence_batch import (
    SentencePlan,
    avoid_examples,
    load_corpus,
    new_item_refs,
    sentence_policy,
    target_item,
)
from app.jobs.persistence import NothingToDo
from app.llm.duplicates import skips_similarity_check
from app.llm.prompts import UnknownPromptVersionError
from app.llm.tasks import ReviewContextInput, build_review_context_request, item_ref
from app.models.content import LearningItem, Sentence
from app.models.enums import ContextStage, LlmTaskType, SentenceStatus
from app.models.jobs import GenerationJob
from app.models.user import User

TASK_TYPE = LlmTaskType.GENERATE_REVIEW_CONTEXT

# 요청에 target이 하나뿐이므로 라벨도 하나다.
_LABEL = item_ref(0)


def prepare(
    db: Session, *, job: GenerationJob, cfg: AppConfig, now: datetime
) -> SentencePlan | NothingToDo | queue.PermanentReason:
    """anchor와 stage를 읽어 요청을 조립한다. DB 읽기만 한다."""
    payload = job.payload_json or {}
    user_id = payload.get("user_id")
    item_id = payload.get("learning_item_id")
    anchor_id = payload.get("anchor_sentence_id")
    stage = _stage(payload.get("context_stage"))
    if (
        not isinstance(user_id, int)
        or not isinstance(item_id, int)
        or not isinstance(anchor_id, int)
        or stage is None
    ):
        return queue.PermanentReason.INVALID_PAYLOAD

    user = db.get(User, user_id)
    item = db.get(LearningItem, item_id)
    anchor = db.get(Sentence, anchor_id)
    if user is None or item is None or anchor is None:
        return queue.PermanentReason.MISSING_REFERENCE

    if anchor.status == SentenceStatus.QUARANTINED:
        # 불변식 #7. 격리된 anchor를 기준으로 만든 문맥은 그 자체가 오염된 문맥이고,
        # anchor를 다시 고르는 것은 materialization의 일이다.
        return NothingToDo()

    provenance = persistence.active_provenance(db, task_type=TASK_TYPE, now=now)
    if provenance is None:
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    request_input = ReviewContextInput(
        learner_level=user.starting_level.value,
        target=target_item(item, label=_LABEL),
        context_stage=stage,
        anchor_japanese=anchor.japanese,
        max_sentence_length_chars=cfg.content.max_sentence_length_chars,
        avoid_japanese=tuple(
            avoid_examples(db, learning_item_id=item.id, limit=cfg.llm.avoid_examples_per_item)
        ),
    )
    try:
        request = build_review_context_request(
            request_input,
            model=provenance.model,
            prompt_version=provenance.prompt_version,
        )
    except UnknownPromptVersionError:
        return queue.PermanentReason.NO_ACTIVE_PROMPT_VERSION

    item_ids = {_LABEL: item.id}
    skip_similarity = skips_similarity_check(task_type=TASK_TYPE, context_stage=stage)
    return SentencePlan(
        request=request,
        provenance=provenance,
        policy=sentence_policy(cfg),
        corpus=load_corpus(db, exclude_job_id=job.id),
        requested_refs=frozenset({_LABEL}),
        new_refs=new_item_refs(db, user_id=user.id, item_ids=item_ids),
        item_ids=item_ids,
        similarity_threshold=cfg.content.duplicate_similarity_threshold,
        skip_similarity=skip_similarity,
        # lineage는 stage에서 나온다. `near_original`만 anchor의 자식이다.
        parent_sentence_id=anchor.id if stage is ContextStage.NEAR_ORIGINAL else None,
    )


def _stage(value: object) -> ContextStage | None:
    return next((stage for stage in ContextStage if stage.value == value), None)
