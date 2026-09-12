"""Content flag와 즉시 quarantine (10_ERROR_HANDLING.md의 `Content Flag 동작`).

사용자가 문장을 `unnatural` / `wrong` 등으로 신고하면 **즉시** 다음이 일어난다.

``` text
content_flags INSERT
sentences.status                   -> quarantined
그 문장의 user_sentence_candidates -> quarantined   (아직 소비되지 않은 것)
그 presentation의 item_exposures   -> invalidated_at = now
영향받은 item의 review_states.meaningful_exposure_count 재계산
content_flagged event
```

Admin UI는 Future지만 quarantine 동작 자체는 MVP 필수다.

**mastery와 FSRS 상태는 되돌리지 않는다.** 10_ERROR_HANDLING.md는 "그 presentation에서
발생한 mastery failure를 능력 저하 evidence로 **사용하지 않는다**"고만 말하고 되돌리는
방법을 정하지 않았으며, mastery는 EMA라서 역산이 불가능하다(alpha와 순서를 모두
알아도 중간값을 복원할 수 없고, `evidence_count`를 줄이면 이후 EMA가 또 달라진다).
FSRS도 마찬가지로 `Card` 상태를 이전으로 되돌리는 API가 없다(ADR-003). 그래서 여기서는
**되돌릴 수 있는 것만 되돌린다** --- `item_exposures.invalidated_at`은 명세가 직접
지시한 유일한 무효화 수단이고 canonical source가 그 행이므로 노출 수는 정확해진다.
evidence 무효화 규칙이 정해지면 그때 이 모듈에 추가한다. 지금 EMA를 근사해서 되돌리면
"복원됐다"는 잘못된 신호만 남는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.learning.exposure import count_valid_exposures, invalidate_presentation_exposures
from app.models.content import ContentFlag, Sentence
from app.models.enums import CandidateStatus, ContentFlagReason, EventType, SentenceStatus
from app.models.learning import ReviewState, UserSentenceCandidate
from app.models.study import StudyPresentation
from app.services.events import record_event
from app.services.presentation import load_owned_presentation
from app.services.study_session import load_owned_session, touch

# 아직 소비되지 않은 candidate만 quarantine으로 옮긴다. `consumed`를 덮어쓰면 "이미
# 보여준 뒤 소비됐다"는 사실이 사라지고, `expired`는 이미 선택 대상이 아니다.
_QUARANTINABLE_CANDIDATE_STATUSES = (
    CandidateStatus.QUEUED,
    CandidateStatus.READY,
    CandidateStatus.SHOWN,
)


def flag_content(
    db: Session,
    *,
    user_id: int,
    presentation_id: int,
    reason: ContentFlagReason,
    note: str | None,
    client_event_id: uuid.UUID,
    now: datetime,
    cfg: AppConfig,
) -> None:
    """`POST /api/study/presentations/{pid}/flag`.

    `record_event()`가 `created = False`를 돌려주면(재전송) **모든 부수효과를
    건너뛴다**(불변식 #10). 두 번째 flag row를 만들거나 이미 무효화된 exposure의
    `invalidated_at`을 다시 쓰지 않는다.

    **닫힌 session과 완료된 presentation에서도 받는다.** 다른 상호작용 5종은 그
    상태에서 409지만(05_API_SPEC.md의 `세션·presentation 상태 게이트`) flag만
    예외다 --- 위 모듈 docstring의 `item_exposures` 무효화는 exposure가 presentation을
    닫을 때 생기므로 **완료 이후의 flag만** 참으로 만든다. 그래서
    `begin_interaction()`을 쓰지 않고 소유권만 확인한다.

    단 **닫힌 session의 `last_activity_at`은 밀지 않는다**(ADR-014). 끝난 세션의
    길이와 `active_seconds`를 뒤늦게 바꾸지 않으면서 신고는 받는다.
    """
    presentation = load_owned_presentation(db, user_id=user_id, presentation_id=presentation_id)
    session = load_owned_session(db, user_id=user_id, session_id=presentation.study_session_id)
    if session.ended_at is None:
        touch(session, now=now, cfg=cfg.session)

    _, created = record_event(
        db,
        user_id=user_id,
        study_session_id=presentation.study_session_id,
        event_type=EventType.CONTENT_FLAGGED,
        client_event_id=client_event_id,
        presentation_id=presentation.id,
        sentence_id=presentation.sentence_id,
        payload={"reason": reason.value},
        now=now,
    )
    if not created:
        db.commit()
        return

    db.add(
        ContentFlag(
            user_id=user_id,
            sentence_id=presentation.sentence_id,
            study_presentation_id=presentation.id,
            reason=reason,
            note=note,
            created_at=now,
        )
    )
    _quarantine_sentence(db, sentence_id=presentation.sentence_id)
    _quarantine_candidates(db, sentence_id=presentation.sentence_id, now=now)
    _invalidate_exposures(db, presentation=presentation, now=now)
    db.commit()


def _quarantine_sentence(db: Session, *, sentence_id: int) -> None:
    sentence = db.get(Sentence, sentence_id)
    if sentence is None:  # pragma: no cover - FK가 막는다
        return
    sentence.status = SentenceStatus.QUARANTINED


def _quarantine_candidates(db: Session, *, sentence_id: int, now: datetime) -> None:
    """이 문장의 candidate를 **사용자 구분 없이** 격리한다.

    `sentences`는 global content이므로 status를 quarantined로 바꾸는 순간 그 문장은
    누구에게도 쓸 수 없다. 신고한 사용자의 candidate만 옮기면 다른 사용자의 Ready
    Pool에 quarantine된 문장을 가리키는 ready candidate가 남는다.
    """
    db.execute(
        sa.update(UserSentenceCandidate)
        .where(
            UserSentenceCandidate.sentence_id == sentence_id,
            UserSentenceCandidate.status.in_(_QUARANTINABLE_CANDIDATE_STATUSES),
        )
        .values(status=CandidateStatus.QUARANTINED, updated_at=now)
        # 세션에 남은 ORM 인스턴스를 동기화하지 않는다. quarantine 판정은 항상
        # status 컬럼을 다시 질의한다(`presentation._is_quarantined`).
        .execution_options(synchronize_session=False)
    )


def _invalidate_exposures(db: Session, *, presentation: StudyPresentation, now: datetime) -> None:
    """그 presentation의 exposure를 무효화하고 캐시를 다시 계산한다.

    행을 지우지 않는다. `item_exposures`는 immutable log이고 무효화는
    `invalidated_at`으로 표현한다. 캐시는 증감이 아니라 **유효 건수를 다시 세어
    대입한다** --- 되돌림에서 `-= 1`을 쓰면 이미 무효화된 행을 두 번 빼거나 덜 뺀다.
    """
    item_ids = invalidate_presentation_exposures(db, presentation_id=presentation.id, now=now)
    for item_id in dict.fromkeys(item_ids):
        state = db.execute(
            sa.select(ReviewState).where(
                ReviewState.user_id == presentation.user_id,
                ReviewState.learning_item_id == item_id,
            )
        ).scalar_one_or_none()
        if state is None:
            continue
        state.meaningful_exposure_count = count_valid_exposures(
            db, user_id=presentation.user_id, learning_item_id=item_id
        )
