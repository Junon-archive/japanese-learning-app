"""문장 안에서 일어나는 상호작용 (05_API_SPEC.md의 `Interaction`).

click / explanation reveal / translation reveal / self-report / probe 응답.

**여기에는 `record_meaningful_exposure()` 호출이 없다.** exposure는
`app/services/presentation.py`의 `finalize_presentation()`이 presentation당 item
1회로 확정한다(불변식 #5). click과 reveal과 self-report를 각각 세면 최소 5회 노출이
조기 충족되어 reinforcement가 사라진다.

**모든 부수효과는 `record_event()`가 `created = True`일 때만 일어난다**(불변식 #10).
재전송이 EMA를 한 번 더 돌리거나 `reps`를 한 번 더 올리면 event row가 중복되지
않는 것만으로는 idempotency가 성립하지 않는다.

**provider를 부르지 않는다**(불변식 #1). explanation은 precomputed DB data이고,
없으면 live LLM fallback이 아니라 예외다 --- 그 문장은 애초에 Ready가 아니었어야
한다(08_LLM_SPEC.md의 Ready invariant).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.learning.mastery import record_explicit_evidence
from app.learning.progression import promote_incidental, record_probe_outcome
from app.models.content import (
    LearningItem,
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
)
from app.models.enums import EventType, ExplanationStatus, ExplicitSignal, LearningItemType
from app.models.learning import ReviewState, UserItemLearningState
from app.models.study import EVIDENCE_UNIQUE_INDEX, LearningEvent
from app.services.events import record_event
from app.services.presentation import (
    FSRS_RATING_EVENTS,
    PROBE_ANSWER_EVENTS,
    PROBE_RESPONSE_EVENTS,
    begin_interaction,
)
from app.srs.review import record_explicit_review

# self-report 3값 -> event_type. 표는 05_API_SPEC.md의 `event idempotency key`다.
SELF_REPORT_EVENTS: dict[ExplicitSignal, EventType] = {
    ExplicitSignal.KNOWN: EventType.SELF_REPORT_KNOWN,
    ExplicitSignal.UNCERTAIN: EventType.SELF_REPORT_UNCERTAIN,
    ExplicitSignal.UNKNOWN: EventType.SELF_REPORT_UNKNOWN,
}


class SentenceItemNotFoundError(Exception):
    """그 `sentence_item_id`가 이 presentation의 문장에 없다 (HTTP 404)."""


class ExplanationMissingError(Exception):
    """validated explanation이 없다 (HTTP 500).

    **live LLM fallback을 하지 않는다.** explanation이 없는 item을 포함한 문장은
    애초에 Ready가 아니어야 하므로(08_LLM_SPEC.md), 여기에 도달했다는 것은 Ready
    invariant가 깨졌다는 신호다. 조용히 생성해서 메우면 그 위반이 영영 드러나지
    않고, request handler가 provider 응답을 기다리게 된다(불변식 #1).
    """


class ProbeNotFoundError(Exception):
    """`probe_id`가 이 사용자/presentation의 `mastery_probe_shown` event가 아니다 (HTTP 400)."""


class EvidenceAlreadyRecordedError(Exception):
    """그 `(presentation, learning_item)`에 explicit evidence가 이미 있다 (HTTP 409).

    07_SRS_SPEC.md의 `노출당 evidence 1건`. self-report 3종과 probe 응답 3종을 합쳐
    세고 `mastery_probe_skipped`는 세지 않는다.

    `PresentationClosedError`의 **형제이고 상속 관계가 아니다.** 둘을 한 타입으로
    묶으면 client가 두 409를 구분할 수 없는데 복구 동작이 반대다 --- 게이트 409는
    "화면 상태가 서버와 어긋났다"라서 세션 재획득으로 이어지고, 이쪽은 "이미
    기록했습니다"이므로 **어떤 재시도도 성공하지 못하고 해서도 안 된다**(ADR-018).
    """


@dataclass(frozen=True)
class ExplanationView:
    sentence_item_id: int
    learning_item_id: int
    canonical_form: str
    reading: str
    item_type: LearningItemType
    core_meaning: str
    meaning_in_context: str
    nuance: str
    example_sentence: str
    example_translation: str | None


@dataclass(frozen=True)
class ProbeResult:
    probe_id: int
    learning_item_id: int
    signal: ExplicitSignal | None


# --------------------------------------------------------------------------
# click / reveal
# --------------------------------------------------------------------------


def click_item(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    sentence_item_id: int,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> ExplanationView:
    """`item_clicked`를 남기고 precomputed 설명을 돌려준다.

    click만으로는 **아무것도 승격되지 않는다**(02_LEARNING_POLICY.md의 `Incidental
    Item Click`). mastery도 FSRS도 건드리지 않고 raw event로만 남는다. 이후 사용자가
    `몰랐음` / `애매함`을 고르면 그때 `self_report()`가 학습 target으로 승격시킨다.

    설명 반환은 부수효과가 아니라 조회다. 그래서 `created`가 False여도(재전송) 같은
    설명을 그대로 돌려준다.
    """
    presentation = begin_interaction(
        db, user_id=user_id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    item = _sentence_item(
        db, sentence_id=presentation.sentence_id, sentence_item_id=sentence_item_id
    )
    record_event(
        db,
        user_id=user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.ITEM_CLICKED,
        client_event_id=client_event_id,
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        learning_item_id=item.learning_item_id,
        now=now,
    )
    view = _explanation(db, item=item)
    db.commit()
    return view


def reveal_explanation(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    sentence_item_id: int,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> None:
    """`explanation_revealed`. 무신호다 --- FSRS rating도 mastery도 만들지 않는다."""
    presentation = begin_interaction(
        db, user_id=user_id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    item = _sentence_item(
        db, sentence_id=presentation.sentence_id, sentence_item_id=sentence_item_id
    )
    record_event(
        db,
        user_id=user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.EXPLANATION_REVEALED,
        client_event_id=client_event_id,
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        learning_item_id=item.learning_item_id,
        now=now,
    )
    db.commit()


def reveal_translation(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> str:
    """`translation_revealed`를 남기고 한국어 번역을 돌려준다.

    번역이 `/next` 응답에 없는 이유가 이것이다. reveal을 거쳐야만 나오므로 event가
    "사용자가 실제로 번역을 봤다"를 뜻한다(05_API_SPEC.md).
    """
    presentation = begin_interaction(
        db, user_id=user_id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    record_event(
        db,
        user_id=user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.TRANSLATION_REVEALED,
        client_event_id=client_event_id,
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        now=now,
    )
    sentence = db.get(Sentence, presentation.sentence_id)
    if sentence is None:  # pragma: no cover - FK가 막는다
        raise SentenceItemNotFoundError(f"sentence {presentation.sentence_id} is missing")
    translation = sentence.korean_translation
    db.commit()
    return translation


# --------------------------------------------------------------------------
# explicit evidence
# --------------------------------------------------------------------------


def self_report(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    sentence_item_id: int,
    signal: ExplicitSignal,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> None:
    """`몰랐음 / 애매함 / 알고 있었음` 하나를 기록한다."""
    presentation = begin_interaction(
        db, user_id=user_id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    item = _sentence_item(
        db, sentence_id=presentation.sentence_id, sentence_item_id=sentence_item_id
    )
    # 판정 단위는 `learning_item_id`다. `sentence_item_id`로 세면 한 문장에 같은
    # learning item을 가리키는 sentence item이 둘일 때 evidence 2건이 통과한다.
    _reject_if_evidence_exists(
        db,
        user_id=user_id,
        presentation_id=presentation.id,
        learning_item_id=item.learning_item_id,
        client_event_id=client_event_id,
    )

    with _evidence_conflict_as_409(
        db, presentation_id=presentation.id, learning_item_id=item.learning_item_id
    ):
        _, created = record_event(
            db,
            user_id=user_id,
            study_session_id=presentation.study_session_id,
            event_type=SELF_REPORT_EVENTS[signal],
            client_event_id=client_event_id,
            presentation_id=presentation.id,
            sentence_id=presentation.sentence_id,
            learning_item_id=item.learning_item_id,
            now=now,
        )
    if created:
        _apply_explicit_evidence(
            db,
            user_id=user_id,
            learning_item_id=item.learning_item_id,
            sentence_id=presentation.sentence_id,
            signal=signal,
            now=now,
            cfg=cfg,
        )
    db.commit()


def respond_to_probe(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    probe_id: int,
    signal: ExplicitSignal | None,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> ProbeResult:
    """probe 응답 1건. `signal = None`이 skip이다.

    대상 item은 **조회한 probe event의 값**이다. client가 보낸 값을 쓰지 않으므로
    위조된 대상에 evidence를 붙일 수 없다(05_API_SPEC.md, ADR-009).

    probe 하나에 응답은 최대 1건이다. 이미 응답이 있으면 새로 기록하지 않고 기존
    결과를 돌려준다 --- 같은 probe에 known과 unknown을 연달아 보내 EMA를 흔드는
    경로를 막는다.
    """
    presentation = begin_interaction(
        db, user_id=user_id, presentation_id=presentation_id, now=now, cfg=cfg
    )
    probe = _probe_event(db, user_id=user_id, presentation_id=presentation.id, probe_id=probe_id)
    item_id = probe.learning_item_id
    if item_id is None:  # pragma: no cover - 기록 시 항상 채운다
        raise ProbeNotFoundError(f"probe {probe_id} has no learning item")

    answered = _existing_probe_response(
        db, user_id=user_id, presentation_id=presentation.id, learning_item_id=item_id
    )
    if answered is not None:
        return ProbeResult(
            probe_id=probe.id,
            learning_item_id=item_id,
            signal=_signal_of(answered.event_type),
        )
    if signal is not None:
        # skip은 evidence가 아니므로 상한에 걸리지 않고, 상한 때문에 거부되어서도
        # 안 된다(02_LEARNING_POLICY.md의 `Skip`).
        _reject_if_evidence_exists(
            db,
            user_id=user_id,
            presentation_id=presentation.id,
            learning_item_id=item_id,
            client_event_id=client_event_id,
        )

    with _evidence_conflict_as_409(db, presentation_id=presentation.id, learning_item_id=item_id):
        _, created = record_event(
            db,
            user_id=user_id,
            study_session_id=presentation.study_session_id,
            event_type=PROBE_RESPONSE_EVENTS[signal],
            client_event_id=client_event_id,
            presentation_id=presentation.id,
            sentence_id=presentation.sentence_id,
            learning_item_id=item_id,
            now=now,
        )
    if created:
        # 답했든 건너뛰었든 물어본 사실은 남는다(`last_probe_at`). skip은 여기서
        # 끝이며 mastery도 FSRS도 건드리지 않는다.
        record_probe_outcome(
            db, user_id=user_id, learning_item_id=item_id, response=signal, now=now
        )
        if signal is not None:
            _apply_explicit_evidence(
                db,
                user_id=user_id,
                learning_item_id=item_id,
                sentence_id=presentation.sentence_id,
                signal=signal,
                now=now,
                cfg=cfg,
            )
    db.commit()
    return ProbeResult(probe_id=probe.id, learning_item_id=item_id, signal=signal)


def _apply_explicit_evidence(
    db: Session,
    *,
    user_id: int,
    learning_item_id: int,
    sentence_id: int,
    signal: ExplicitSignal,
    now: datetime,
    cfg: AppConfig,
) -> None:
    """explicit evidence 1건을 mastery와(조건부로) FSRS에 반영한다.

    mastery는 **항상** 갱신한다. 사용자가 말한 것은 그 자체로 증거다.

    FSRS는 조건부다. `알고 있았음`만으로 아직 학습 target이 아닌 item을 SRS에
    등록하지 않는다(02_LEARNING_POLICY.md의 `Incidental Item Click`: "`알고 있었음`이면
    SRS 신규 item으로 강제 등록하지 않는다"). 그래서 스케줄을 만드는 조건을 둘로 둔다.

    ``` text
    이미 review_states 행이 있다        -> 기록한다 (진행 중인 복습)
    이 신호로 학습 target이 되어 있다   -> 기록한다 (몰랐음/애매함이 승격시킨 경우 포함)
    그 밖(아직 target이 아닌 incidental / exploration item에 대한 `알고 있었음`)
                                        -> FSRS 행을 만들지 않는다
    ```

    `promote_incidental()`을 먼저 부르는 이유가 이것이다. 승격 결과를 본 뒤에 FSRS
    기록 여부를 정해야 `몰랐음 -> 신규 learning target 등록`이 한 번에 성립한다.

    `sentence_id`는 지금 보고 있는 문장이다. 승격이 일어나면 그것이 그 item의 최초
    학습 문맥(`anchor_sentence_id`)이 된다(07_SRS_SPEC.md의 `anchor_sentence_id 지정`).
    """
    record_explicit_evidence(
        db,
        user_id=user_id,
        learning_item_id=learning_item_id,
        signal=signal,
        now=now,
        alpha=cfg.learning.mastery_ema_alpha,
    )
    promote_incidental(
        db,
        user_id=user_id,
        learning_item_id=learning_item_id,
        sentence_id=sentence_id,
        signal=signal,
        now=now,
    )
    if _has_review_state(
        db, user_id=user_id, learning_item_id=learning_item_id
    ) or _is_active_target(db, user_id=user_id, learning_item_id=learning_item_id):
        record_explicit_review(
            db,
            user_id=user_id,
            learning_item_id=learning_item_id,
            signal=signal,
            now=now,
            config=cfg,
        )


# --------------------------------------------------------------------------
# 조회
# --------------------------------------------------------------------------


def _sentence_item(db: Session, *, sentence_id: int, sentence_item_id: int) -> SentenceItem:
    """이 presentation의 문장에 속한 sentence_item만 받는다.

    문장 소속을 확인하지 않으면 임의의 `sentence_item_id`로 화면에 없던 표현에
    evidence를 붙일 수 있다.
    """
    item = db.execute(
        sa.select(SentenceItem).where(
            SentenceItem.id == sentence_item_id,
            SentenceItem.sentence_id == sentence_id,
        )
    ).scalar_one_or_none()
    if item is None:
        raise SentenceItemNotFoundError(f"sentence item {sentence_item_id} is not in this sentence")
    return item


def _explanation(db: Session, *, item: SentenceItem) -> ExplanationView:
    row = db.execute(
        sa.select(SentenceItemExplanation, LearningItem)
        .join(LearningItem, LearningItem.id == item.learning_item_id)
        .where(
            SentenceItemExplanation.sentence_item_id == item.id,
            SentenceItemExplanation.status == ExplanationStatus.VALIDATED,
        )
        .order_by(SentenceItemExplanation.id)
        .limit(1)
    ).first()
    if row is None:
        raise ExplanationMissingError(
            f"sentence item {item.id} has no validated explanation; "
            "the sentence should never have been Ready"
        )
    explanation, learning_item = row
    return ExplanationView(
        sentence_item_id=item.id,
        learning_item_id=item.learning_item_id,
        # canonical form은 문장 안의 활용형이 아니라 item의 표제형이다.
        canonical_form=learning_item.lemma,
        reading=explanation.reading,
        item_type=learning_item.type,
        core_meaning=explanation.core_meaning,
        meaning_in_context=explanation.meaning_in_context,
        nuance=explanation.nuance,
        example_sentence=explanation.example_sentence,
        example_translation=explanation.example_translation,
    )


def _probe_event(
    db: Session, *, user_id: int, presentation_id: int, probe_id: int
) -> LearningEvent:
    """05_API_SPEC.md가 요구하는 세 조건을 모두 확인한다. 하나라도 어긋나면 400이다."""
    event = db.execute(
        sa.select(LearningEvent).where(
            LearningEvent.id == probe_id,
            LearningEvent.user_id == user_id,
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.event_type == EventType.MASTERY_PROBE_SHOWN,
        )
    ).scalar_one_or_none()
    if event is None:
        raise ProbeNotFoundError(f"probe {probe_id} is not a probe of this presentation")
    return event


def _existing_probe_response(
    db: Session, *, user_id: int, presentation_id: int, learning_item_id: int
) -> LearningEvent | None:
    return db.execute(
        sa.select(LearningEvent)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.learning_item_id == learning_item_id,
            LearningEvent.event_type.in_(PROBE_ANSWER_EVENTS),
        )
        .order_by(LearningEvent.id)
        .limit(1)
    ).scalar_one_or_none()


def _reject_if_evidence_exists(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    learning_item_id: int,
    client_event_id: uuid.UUID,
) -> None:
    """노출당 evidence 1건을 강제한다 (07_SRS_SPEC.md의 `노출당 evidence 1건`).

    `record_event()` **전에** 판정한다. 뒤에서 판정하면 이미 나간 INSERT가 호출부의
    rollback으로 지워지기를 기대해야 하는데, 명세는 "409이면 event를 기록하지 않고
    mastery·FSRS·`context_stage`도 건드리지 않는다"를 요구한다(05_API_SPEC.md의
    `노출당 evidence 상한`).

    **이 SELECT가 상한의 전부는 아니다.** SELECT와 INSERT 사이에 잠금이 없으므로 서로
    다른 `client_event_id` 2건의 동시 요청은 각자 "evidence 없음"을 읽고 둘 다 기록으로
    넘어간다. 그것을 막는 것은 DB의 `uq_learning_events_evidence`이고, 거부를 409로
    옮기는 것은 아래 `_evidence_conflict_as_409()`다. 이 SELECT를 지우면 안 된다 ---
    2회차 요청이 정상 경로에서 event를 **애초에 내지 않는** 근거가 이것이다.

    **같은 `client_event_id`의 event는 제외한다.** 그것은 재전송이고 재전송
    멱등성이 이 상한보다 먼저 판정된다(같은 절의 `판정 순서`에서 3 < 4). 제외하지
    않으면 성공한 요청의 네트워크 재시도가 자기가 만든 evidence에 걸려 409가 된다.

    세는 집합은 `FSRS_RATING_EVENTS`다. `PROBE_ANSWER_EVENTS`를 쓰면
    `mastery_probe_skipped`가 evidence로 세어진다.
    """
    existing = db.execute(
        sa.select(LearningEvent.id)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.learning_item_id == learning_item_id,
            LearningEvent.event_type.in_(FSRS_RATING_EVENTS),
            LearningEvent.client_event_id != client_event_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise _already_recorded(presentation_id=presentation_id, learning_item_id=learning_item_id)


def _already_recorded(
    *, presentation_id: int, learning_item_id: int
) -> EvidenceAlreadyRecordedError:
    return EvidenceAlreadyRecordedError(
        f"learning item {learning_item_id} already has evidence in presentation {presentation_id}"
    )


@contextmanager
def _evidence_conflict_as_409(
    db: Session, *, presentation_id: int, learning_item_id: int
) -> Iterator[None]:
    """`uq_learning_events_evidence` 위반을 `EvidenceAlreadyRecordedError`로 옮긴다.

    이 경로는 **도달 가능하고 의미가 정해져 있다.** 위 SELECT를 둘 다 통과한 동시 요청
    2건 중 하나는 index에 걸리는데, 그 요청에 명세가 요구하는 응답은 이미 409다
    (05_API_SPEC.md의 `노출당 evidence 상한`: 2회차는 409). 잠금으로 직렬화해 SELECT가
    먼저 보게 만드는 길도 있지만 그렇게 얻는 것이 없다 --- 어느 쪽이든 결과는 같은
    409이고, 잠금은 evidence마다 행 하나를 더 잡는다.

    **다른 제약 위반은 삼키지 않는다.** psycopg가 알려주는 위반 index 이름이 그
    index일 때만 옮기고, 그 밖(예: `uq_user_mastery_user_id_learning_item_id`)은 그대로
    올려 500이 되게 둔다. 그쪽은 서버 불변식이 깨진 것이므로 409로 덮으면 "이미
    기록했습니다"라는 거짓말이 되고 진단도 사라진다.

    `rollback()`이 필요하다. IntegrityError 뒤의 트랜잭션은 abort 상태라 이후 어떤
    statement도 실패하고, 호출부는 그 세션으로 아무것도 하지 못한다. 되돌려지는 것은 진
    요청이 만든 것뿐이고(`touch()`의 `last_activity_at` 포함) 그것이 "409이면 아무것도
    건드리지 않는다"와 같은 방향이다.
    """
    try:
        yield
    except IntegrityError as exc:
        if _violated_constraint(exc) != EVIDENCE_UNIQUE_INDEX:
            raise
        db.rollback()
        raise _already_recorded(
            presentation_id=presentation_id, learning_item_id=learning_item_id
        ) from exc


def _violated_constraint(error: IntegrityError) -> str | None:
    """위반한 제약/index의 이름. psycopg가 알려주지 않으면 None이다."""
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _signal_of(event_type: EventType) -> ExplicitSignal | None:
    for signal, mapped in PROBE_RESPONSE_EVENTS.items():
        if mapped is event_type:
            return signal
    return None  # pragma: no cover - 조회가 응답 event만 돌려준다


def _has_review_state(db: Session, *, user_id: int, learning_item_id: int) -> bool:
    return (
        db.execute(
            sa.select(ReviewState.id).where(
                ReviewState.user_id == user_id,
                ReviewState.learning_item_id == learning_item_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def _is_active_target(db: Session, *, user_id: int, learning_item_id: int) -> bool:
    return bool(
        db.execute(
            sa.select(UserItemLearningState.is_active_learning_target).where(
                UserItemLearningState.user_id == user_id,
                UserItemLearningState.learning_item_id == learning_item_id,
            )
        ).scalar_one_or_none()
    )
