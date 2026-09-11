"""제약이 실제로 **거부하는지** 본다. 스키마 형태 검사는 test_schema_invariants.py.

형태 검사만으로는 부족하다. 제약이 존재해도 기대한 값을 실제로 막지 못하면
불변식은 지켜지지 않는다.

아래 filler 상수들은 NOT NULL을 채우기 위한 값이며 각 테스트의 주장과 무관하다.
정책값(`default_session_minutes`, `max_job_attempts` 등)은 config에서 온다.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ItemExposure, LearningItem, Sentence, StudyPresentation, User
from app.models.enums import CandidateStatus, ContextStage, ExposureModality
from tests import factories

pytestmark = pytest.mark.integration

SESSION_MINUTES_FILLER = 1
MAX_ATTEMPTS_FILLER = 1
ALGORITHM_VERSION_FILLER = "test"
FSRS_PARAMS_VERSION_FILLER = "test"


def _presentation_fixture(
    db_session: Session,
) -> tuple[User, LearningItem, StudyPresentation, Sentence]:
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    sentence = factories.make_sentence(db_session)
    study_session = factories.make_study_session(
        db_session, user, target_minutes=SESSION_MINUTES_FILLER
    )
    candidate = factories.make_candidate(db_session, user, sentence, status=CandidateStatus.READY)
    presentation = factories.make_presentation(db_session, user, study_session, candidate, sentence)
    return user, item, presentation, sentence


def test_the_same_item_cannot_be_exposed_twice_in_one_presentation(db_session: Session) -> None:
    """불변식 5: exposure는 presentation당 item 1회.

    이 unique가 없으면 click / explanation reveal / self-report가 각각 exposure로
    집계되어 최소 5회 노출이 조기 충족되고 reinforcement 노출이 사라진다.
    exposure는 immutable log이므로 잘못 쌓인 뒤에는 사후 복구가 어렵다.
    """
    user, item, presentation, sentence = _presentation_fixture(db_session)
    factories.make_exposure(db_session, user, item, presentation, sentence)

    with pytest.raises(IntegrityError):
        factories.make_exposure(db_session, user, item, presentation, sentence)


def test_exposures_of_the_same_item_in_different_presentations_are_allowed(
    db_session: Session,
) -> None:
    """같은 item이라도 presentation이 다르면 별도 exposure다. 위 unique가 너무
    넓게 걸리면 반복 노출 자체가 기록되지 않는다."""
    user, item, presentation, sentence = _presentation_fixture(db_session)
    factories.make_exposure(db_session, user, item, presentation, sentence)

    study_session = factories.make_study_session(
        db_session, user, target_minutes=SESSION_MINUTES_FILLER
    )
    candidate = factories.make_candidate(db_session, user, sentence, status=CandidateStatus.READY)
    other = factories.make_presentation(db_session, user, study_session, candidate, sentence)
    second = factories.make_exposure(db_session, user, item, other, sentence)

    assert second.id is not None
    count = db_session.scalar(
        sa.select(sa.func.count()).select_from(ItemExposure).where(ItemExposure.user_id == user.id)
    )
    assert count == 2


def _insert_exposure_with_modality(db_session: Session, modality: str) -> None:
    """ORM은 Enum 타입이 먼저 막으므로 DB 방어선을 보려면 raw SQL로 넣어야 한다."""
    user, item, presentation, sentence = _presentation_fixture(db_session)
    db_session.execute(
        sa.text(
            "INSERT INTO item_exposures "
            "(user_id, learning_item_id, study_presentation_id, sentence_id,"
            " modality, context_stage) "
            "VALUES (:user_id, :item_id, :presentation_id, :sentence_id,"
            " :modality, :context_stage)"
        ),
        {
            "user_id": user.id,
            "item_id": item.id,
            "presentation_id": presentation.id,
            "sentence_id": sentence.id,
            "modality": modality,
            "context_stage": ContextStage.ANCHOR.value,
        },
    )


def test_listening_modality_is_rejected(db_session: Session) -> None:
    """MVP의 modality는 `reading`뿐이다(04_DB_SPEC.md, listening은 Future).

    `listening`은 CHECK 이전에 VARCHAR(7) 길이에서 잘려 DataError가 된다.
    둘 다 DatabaseError이고 중요한 것은 "DB가 거부한다"이므로 상위 타입으로 받는다.
    CHECK 자체가 살아 있는지는 아래 test_unknown_modality_violates_the_check가 본다.
    """
    with pytest.raises(sa.exc.DatabaseError):
        _insert_exposure_with_modality(db_session, "listening")


def test_unknown_modality_violates_the_check(db_session: Session) -> None:
    """길이가 `reading`과 같아 VARCHAR 길이 제한에 걸리지 않는 값. CHECK가 막아야 한다."""
    with pytest.raises(IntegrityError):
        _insert_exposure_with_modality(db_session, "audioxx")


def test_valid_modality_is_accepted(db_session: Session) -> None:
    """위 테스트가 "INSERT가 그냥 실패한다"가 아니라 값 때문에 실패함을 보인다."""
    user, item, presentation, sentence = _presentation_fixture(db_session)
    exposure = factories.make_exposure(db_session, user, item, presentation, sentence)
    assert exposure.modality == ExposureModality.READING


def test_duplicate_client_event_id_for_one_user_is_rejected(db_session: Session) -> None:
    """불변식 10: event POST는 client_event_id 기반 idempotency를 가진다.

    이 제약이 없으면 재전송이 mastery evidence를 두 번 만든다.
    """
    user = factories.make_user(db_session)
    study_session = factories.make_study_session(
        db_session, user, target_minutes=SESSION_MINUTES_FILLER
    )
    client_event_id = uuid.uuid4()
    factories.make_event(db_session, user, study_session, client_event_id=client_event_id)

    with pytest.raises(IntegrityError):
        factories.make_event(db_session, user, study_session, client_event_id=client_event_id)


def test_the_same_client_event_id_from_another_user_is_allowed(db_session: Session) -> None:
    """idempotency 범위는 (user_id, client_event_id)다. 전역 unique가 아니다."""
    client_event_id = uuid.uuid4()
    for _ in range(2):
        user = factories.make_user(db_session)
        study_session = factories.make_study_session(
            db_session, user, target_minutes=SESSION_MINUTES_FILLER
        )
        event = factories.make_event(
            db_session, user, study_session, client_event_id=client_event_id
        )
        assert event.id is not None


def test_duplicate_job_idempotency_key_is_rejected(db_session: Session) -> None:
    """09_BACKGROUND_JOBS.md: worker 실행은 at-least-once다.

    이 unique가 없으면 retry가 콘텐츠를 중복 생성하고 provider 비용이 두 배가 된다.
    """
    key = f"batch-{uuid.uuid4().hex}"
    factories.make_generation_job(db_session, idempotency_key=key, max_attempts=MAX_ATTEMPTS_FILLER)

    with pytest.raises(IntegrityError):
        factories.make_generation_job(
            db_session, idempotency_key=key, max_attempts=MAX_ATTEMPTS_FILLER
        )


def test_unknown_job_type_is_rejected(db_session: Session) -> None:
    """04_DB_SPEC.md: job_type 허용값은 3개뿐이고 pool replenishment는 job_type이 아니다."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            sa.text(
                "INSERT INTO generation_jobs "
                "(job_type, status, idempotency_key, max_attempts, next_attempt_at) "
                "VALUES ('POOL_REPLENISHMENT', 'queued', :key, 1, now())"
            ),
            {"key": f"pool-{uuid.uuid4().hex}"},
        )


def test_mastery_above_one_is_rejected(db_session: Session) -> None:
    """mastery는 0..1 점수다(02_LEARNING_POLICY.md)."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    with pytest.raises(IntegrityError):
        factories.make_mastery(
            db_session,
            user,
            item,
            comprehension_mastery=1.5,
            algorithm_version=ALGORITHM_VERSION_FILLER,
        )


def test_mastery_null_means_not_measured_and_is_allowed(db_session: Session) -> None:
    """NULL은 "능력 0"이 아니라 "아직 evidence가 없음"이다. 이것을 막으면
    boolean Known/Unknown 모델로 퇴화한다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    mastery = factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=None,
        algorithm_version=ALGORITHM_VERSION_FILLER,
    )
    assert mastery.comprehension_mastery is None
    assert mastery.listening_mastery is None


def test_duplicate_mastery_row_for_one_item_is_rejected(db_session: Session) -> None:
    """mastery의 identity는 (user_id, learning_item_id)다. 두 행이 생기면
    어느 쪽이 진짜인지 알 수 없다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=None,
        algorithm_version=ALGORITHM_VERSION_FILLER,
    )
    with pytest.raises(IntegrityError):
        factories.make_mastery(
            db_session,
            user,
            item,
            comprehension_mastery=None,
            algorithm_version=ALGORITHM_VERSION_FILLER,
        )


def test_review_state_value_outside_the_fsrs_enum_is_rejected(db_session: Session) -> None:
    """ADR-003: state는 1=Learning, 2=Review, 3=Relearning뿐이다. 0은 없다."""
    user = factories.make_user(db_session)
    item = factories.make_learning_item(db_session)
    with pytest.raises(IntegrityError):
        factories.make_review_state(
            db_session, user, item, state=0, params_version=FSRS_PARAMS_VERSION_FILLER
        )


def test_uppercase_login_id_is_rejected(db_session: Session) -> None:
    """04_DB_SPEC.md login_id: 정규화(ASCII lowercase)된 값만 저장한다.

    대소문자만 다른 중복 계정을 DB 차원에서 막는다.
    """
    with pytest.raises(IntegrityError):
        factories.make_user(db_session, login_id="Tester@example.com")


def test_too_short_login_id_is_rejected(db_session: Session) -> None:
    """허용 형식은 `^[a-z0-9._+@-]{3,64}$`다."""
    with pytest.raises(IntegrityError):
        factories.make_user(db_session, login_id="ab")
