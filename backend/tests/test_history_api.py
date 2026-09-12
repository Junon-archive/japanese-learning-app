"""History endpoint HTTP 계약 (05_API_SPEC.md의 `History`).

`conftest.py`의 `db_client`를 쓰지 않는다. base_url이 http라서 `Secure` cookie가
httpx cookie jar에 저장되지 않고, 그러면 login은 200인데 이어지는 요청이 401이 되는
형태로 조용히 실패한다(test_study_api.py와 같은 이유).

여기서 고정하는 것:

-   두 목록은 **요청 사용자의 행만** 담는다. 다른 사용자의 session/item이 응답에 없다.
-   미인증 요청은 401이다.
-   고정 상한(50)을 넘지 않고, 넘으면 **오래된 것부터** 잘리며 `truncated`가 true다.
    정확히 50건이면 false다 --- 경계 양쪽을 둘 다 본다.
-   `completed_sentence_count`는 `completed_at IS NULL`인 presentation을 세지 않는다.
-   `exposure_count`는 `invalidated_at IS NOT NULL`인 노출을 세지 않는다.
-   `user_mastery` / `review_states`가 없는 item은 `null`로 나오고 목록에서 빠지지 않는다.
-   눌러만 본 item은 목록에 없다(`user_item_learning_state` 행이 없다).
-   조회가 상태를 바꾸지 않는다.

상한 50은 명세에서 **직접 옮겨 적는다.** 구현 상수를 import하면 "상한을 5000으로
바꾸는 변경"이 스스로를 승인한다(`test_route_auth.py`가 익명 허용 목록을 다루는 방식).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import DeclarativeBase, Session

from app.api.deps import get_db, get_now
from app.main import create_app
from app.models.content import LearningItem
from app.models.enums import CandidateStatus, EventType, LearningItemType
from app.models.learning import UserItemLearningState
from app.models.study import ItemExposure, LearningEvent, StudyPresentation, StudySession
from app.models.user import User
from app.services.auth import hash_password
from app.settings import get_settings
from tests import factories
from tests.clock import DEFAULT_START, MutableClock

pytestmark = pytest.mark.integration

ORIGIN = "https://app.test"
PASSWORD = "correct horse battery staple"

SESSIONS_PATH = "/api/history/sessions"
ITEMS_PATH = "/api/history/items"

# 05_API_SPEC.md의 `개수 상한`. 두 endpoint 공통이고 고정이다.
SPEC_HISTORY_LIMIT = 50

# history는 이 값들을 그대로 내보낸다(정책 파생이 아니다). 그래서 자리 채우기 값이면
# 충분하고, 오히려 config 기본값을 쓰면 "그대로 내보낸다"가 흐려진다.
SESSION_MINUTES_FILLER = 11
EXTENDED_MINUTES_FILLER = 7
ACTIVE_SECONDS_FILLER = 703
ALGORITHM_VERSION_FILLER = "test-mastery-v0"
FSRS_PARAMS_VERSION_FILLER = "test-fsrs-v0"


@pytest.fixture
def api(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, study_clock: MutableClock
) -> Iterator[TestClient]:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_now] = study_clock.now
    try:
        with TestClient(app, base_url="https://testserver", headers={"Origin": ORIGIN}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _login(api: TestClient, db: Session) -> User:
    user = factories.make_user(db)
    user.password_hash = hash_password(PASSWORD)
    db.flush()
    response = api.post("/api/auth/login", json={"login_id": user.login_id, "password": PASSWORD})
    assert response.status_code == 200
    return user


def _body(api: TestClient, path: str) -> dict[str, Any]:
    response = api.get(path)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _sessions(api: TestClient) -> list[dict[str, Any]]:
    return list(_body(api, SESSIONS_PATH)["sessions"])


def _items(api: TestClient) -> list[dict[str, Any]]:
    return list(_body(api, ITEMS_PATH)["items"])


def _make_session(
    db: Session,
    user: User,
    *,
    started_at: datetime = DEFAULT_START,
    ended_at: datetime | None = None,
    active_seconds: int = ACTIVE_SECONDS_FILLER,
    extended_minutes: int = 0,
) -> StudySession:
    study_session = factories.make_study_session(db, user, target_minutes=SESSION_MINUTES_FILLER)
    study_session.started_at = started_at
    study_session.last_activity_at = started_at
    study_session.ended_at = ended_at
    study_session.active_seconds = active_seconds
    study_session.extended_minutes = extended_minutes
    db.flush()
    return study_session


def _make_presentation(
    db: Session, user: User, study_session: StudySession, *, completed: bool
) -> StudyPresentation:
    sentence = factories.make_sentence(db)
    candidate = factories.make_candidate(db, user, sentence, status=CandidateStatus.READY)
    return factories.make_presentation(
        db,
        user,
        study_session,
        candidate,
        sentence,
        completed_at=DEFAULT_START if completed else None,
    )


def _make_learned_item(
    db: Session, user: User, *, lemma: str, updated_at: datetime = DEFAULT_START
) -> LearningItem:
    item = factories.make_learning_item(db, lemma=lemma)
    state = factories.make_learning_state(db, user, item)
    state.updated_at = updated_at
    db.flush()
    return item


# --------------------------------------------------------------------------
# 자기 데이터만 (13_ACCEPTANCE_CRITERIA.md)
# --------------------------------------------------------------------------


def test_session_history_contains_only_the_requesting_users_sessions(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    mine = _make_session(db_session, user)
    stranger = factories.make_user(db_session)
    theirs = _make_session(db_session, stranger)

    sessions = _sessions(api)

    assert [row["session_id"] for row in sessions] == [mine.id]
    assert theirs.id not in {row["session_id"] for row in sessions}


def test_item_history_contains_only_the_requesting_users_items(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    mine = _make_learned_item(db_session, user, lemma="気が乗らない")
    stranger = factories.make_user(db_session)
    theirs = _make_learned_item(db_session, stranger, lemma="仕方がない")

    items = _items(api)

    assert [row["learning_item_id"] for row in items] == [mine.id]
    assert theirs.id not in {row["learning_item_id"] for row in items}


def test_another_users_presentations_do_not_raise_the_completed_count(
    api: TestClient, db_session: Session
) -> None:
    """다른 사용자의 완료 presentation이 내 session 요약에 섞이지 않는다."""
    user = _login(api, db_session)
    mine = _make_session(db_session, user)
    _make_presentation(db_session, user, mine, completed=True)
    stranger = factories.make_user(db_session)
    stranger_session = _make_session(db_session, stranger)
    _make_presentation(db_session, stranger, stranger_session, completed=True)
    _make_presentation(db_session, stranger, stranger_session, completed=True)

    sessions = _sessions(api)

    assert [(row["session_id"], row["completed_sentence_count"]) for row in sessions] == [
        (mine.id, 1)
    ]


def test_another_users_exposures_do_not_raise_the_exposure_count(
    api: TestClient, db_session: Session
) -> None:
    """같은 learning_item을 남이 봤다고 내 노출 횟수가 오르지 않는다."""
    user = _login(api, db_session)
    item = _make_learned_item(db_session, user, lemma="任せる")
    stranger = factories.make_user(db_session)
    stranger_session = _make_session(db_session, stranger)
    stranger_presentation = _make_presentation(
        db_session, stranger, stranger_session, completed=True
    )
    sentence = factories.make_sentence(db_session)
    factories.make_exposure(db_session, stranger, item, stranger_presentation, sentence)

    items = _items(api)

    assert [(row["learning_item_id"], row["exposure_count"]) for row in items] == [(item.id, 0)]


def test_unauthenticated_requests_are_rejected(api: TestClient) -> None:
    """익명 허용 목록에 없다. `test_route_auth.py`가 전수로도 확인하지만, 두 endpoint의
    401은 이 파일이 고정하는 계약의 일부이므로 여기에도 둔다."""
    for path in (SESSIONS_PATH, ITEMS_PATH):
        response = api.get(path)
        assert response.status_code == 401, f"{path} -> {response.status_code}"


# --------------------------------------------------------------------------
# 개수 상한과 정렬 (05_API_SPEC.md의 `개수 상한`)
# --------------------------------------------------------------------------


# 경계 양쪽을 **둘 다** 요구한다. 한쪽만 보면 `truncated`를 상수로 박은 구현이 통과한다.
_TRUNCATION_CASES = [
    pytest.param(SPEC_HISTORY_LIMIT, False, id="exactly-the-limit"),
    pytest.param(SPEC_HISTORY_LIMIT + 1, True, id="one-over-the-limit"),
]


@pytest.mark.parametrize(("row_count", "expect_truncated"), _TRUNCATION_CASES)
def test_session_history_caps_the_rows_and_reports_truncation(
    api: TestClient, db_session: Session, row_count: int, expect_truncated: bool
) -> None:
    """상한을 넘으면 오래된 것부터 잘리고 `truncated`가 그 사실을 알린다.

    정확히 상한만큼이면 `truncated`는 false다 --- `len == 50`으로 판정하는 구현은
    잘리지 않았는데 잘렸다고 답한다(05_API_SPEC.md).
    """
    user = _login(api, db_session)
    created = [
        _make_session(db_session, user, started_at=DEFAULT_START + timedelta(minutes=index))
        for index in range(row_count)
    ]

    body = _body(api, SESSIONS_PATH)

    assert body["truncated"] is expect_truncated
    assert len(body["sessions"]) == min(row_count, SPEC_HISTORY_LIMIT)
    # 최근 것부터 담긴다.
    expected = [row.id for row in reversed(created)][:SPEC_HISTORY_LIMIT]
    assert [row["session_id"] for row in body["sessions"]] == expected
    if expect_truncated:
        assert created[0].id not in {row["session_id"] for row in body["sessions"]}


@pytest.mark.parametrize(("row_count", "expect_truncated"), _TRUNCATION_CASES)
def test_item_history_caps_the_rows_and_reports_truncation(
    api: TestClient, db_session: Session, row_count: int, expect_truncated: bool
) -> None:
    user = _login(api, db_session)
    created = [
        _make_learned_item(
            db_session,
            user,
            lemma=f"表現{index}",
            updated_at=DEFAULT_START + timedelta(minutes=index),
        )
        for index in range(row_count)
    ]

    body = _body(api, ITEMS_PATH)

    assert body["truncated"] is expect_truncated
    assert len(body["items"]) == min(row_count, SPEC_HISTORY_LIMIT)
    expected = [item.id for item in reversed(created)][:SPEC_HISTORY_LIMIT]
    assert [row["learning_item_id"] for row in body["items"]] == expected
    if expect_truncated:
        assert created[0].id not in {row["learning_item_id"] for row in body["items"]}


def test_a_short_history_is_not_reported_as_truncated(api: TestClient, db_session: Session) -> None:
    """행이 거의 없을 때도 false다. 빈 목록도 false다."""
    user = _login(api, db_session)

    assert _body(api, SESSIONS_PATH)["truncated"] is False
    assert _body(api, ITEMS_PATH)["truncated"] is False

    _make_session(db_session, user)
    _make_learned_item(db_session, user, lemma="任せる")

    assert _body(api, SESSIONS_PATH)["truncated"] is False
    assert _body(api, ITEMS_PATH)["truncated"] is False


def test_history_does_not_expose_a_total_count(api: TestClient, db_session: Session) -> None:
    """`total`을 내보내지 않는다. 내보내면 pagination을 만들라는 압력이 된다."""
    user = _login(api, db_session)
    _make_session(db_session, user)
    _make_learned_item(db_session, user, lemma="任せる")

    assert set(_body(api, SESSIONS_PATH)) == {"sessions", "truncated"}
    assert set(_body(api, ITEMS_PATH)) == {"items", "truncated"}


def test_sessions_started_at_the_same_moment_have_a_stable_order(
    api: TestClient, db_session: Session
) -> None:
    """`started_at DESC, session_id DESC`. 두 번째 키가 없으면 순서가 실행마다 흔들린다."""
    user = _login(api, db_session)
    first = _make_session(db_session, user)
    second = _make_session(db_session, user)

    sessions = _sessions(api)

    assert [row["session_id"] for row in sessions] == sorted([first.id, second.id], reverse=True)


# --------------------------------------------------------------------------
# GET /api/history/sessions 의 필드
# --------------------------------------------------------------------------


def test_session_payload_echoes_the_stored_columns(api: TestClient, db_session: Session) -> None:
    user = _login(api, db_session)
    ended_at = DEFAULT_START + timedelta(minutes=13)
    study_session = _make_session(
        db_session, user, ended_at=ended_at, extended_minutes=EXTENDED_MINUTES_FILLER
    )
    _make_presentation(db_session, user, study_session, completed=True)

    assert _sessions(api) == [
        {
            "session_id": study_session.id,
            "started_at": "2026-01-01T09:00:00Z",
            "ended_at": "2026-01-01T09:13:00Z",
            "active_seconds": ACTIVE_SECONDS_FILLER,
            "target_minutes": SESSION_MINUTES_FILLER,
            "extended_minutes": EXTENDED_MINUTES_FILLER,
            "completed_sentence_count": 1,
        }
    ]


def test_an_open_session_is_listed_with_a_null_ended_at(
    api: TestClient, db_session: Session
) -> None:
    """빼면 오늘 진행 중인 세션이 기록에서 사라진다."""
    user = _login(api, db_session)
    study_session = _make_session(db_session, user, ended_at=None)

    sessions = _sessions(api)

    assert [(row["session_id"], row["ended_at"]) for row in sessions] == [(study_session.id, None)]


def test_completed_sentence_count_ignores_incomplete_presentations(
    api: TestClient, db_session: Session
) -> None:
    """idle timeout으로 닫힌 session에는 영원히 미완료로 남는 행이 있다. 그것을 세면
    **보지 않고 떠난 문장이 학습 기록이 된다**(05_API_SPEC.md).

    한 session의 미완료 presentation은 최대 하나다(`uq_study_presentations_open`).
    그래서 미완료만 있는 session을 하나 더 두고 그쪽이 0인 것까지 본다.
    """
    user = _login(api, db_session)
    mixed = _make_session(db_session, user, started_at=DEFAULT_START + timedelta(minutes=1))
    _make_presentation(db_session, user, mixed, completed=True)
    _make_presentation(db_session, user, mixed, completed=False)
    abandoned = _make_session(db_session, user)
    _make_presentation(db_session, user, abandoned, completed=False)

    sessions = _sessions(api)

    assert [(row["session_id"], row["completed_sentence_count"]) for row in sessions] == [
        (mixed.id, 1),
        (abandoned.id, 0),
    ]


def test_a_session_without_presentations_reports_zero(api: TestClient, db_session: Session) -> None:
    user = _login(api, db_session)
    study_session = _make_session(db_session, user)

    assert [(row["session_id"], row["completed_sentence_count"]) for row in _sessions(api)] == [
        (study_session.id, 0)
    ]


def test_session_payload_hides_the_policy_snapshot_and_summary(
    api: TestClient, db_session: Session
) -> None:
    """`policy_snapshot_json`은 설정값 묶음이고 `summary_json`은 MVP에 채우는 경로가 없다."""
    user = _login(api, db_session)
    study_session = _make_session(db_session, user)
    study_session.policy_snapshot_json = {"review_ratio": 0.5}
    db_session.flush()

    (row,) = _sessions(api)

    assert "policy_snapshot_json" not in row
    assert "summary_json" not in row
    assert "0.5" not in api.get(SESSIONS_PATH).text


# --------------------------------------------------------------------------
# GET /api/history/items 의 필드
# --------------------------------------------------------------------------


def test_item_payload_joins_the_item_mastery_and_review_state(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    item = factories.make_learning_item(db_session, lemma="気が乗らない")
    state = factories.make_learning_state(db_session, user, item)
    state.updated_at = DEFAULT_START
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=0.32,
        algorithm_version=ALGORITHM_VERSION_FILLER,
    )
    review_state = factories.make_review_state(
        db_session, user, item, state=1, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.next_review_at = DEFAULT_START + timedelta(days=2)
    study_session = _make_session(db_session, user)
    presentation = _make_presentation(db_session, user, study_session, completed=True)
    sentence = factories.make_sentence(db_session)
    factories.make_exposure(db_session, user, item, presentation, sentence)
    db_session.flush()

    assert _items(api) == [
        {
            "learning_item_id": item.id,
            "lemma": "気が乗らない",
            "item_type": LearningItemType.EXPRESSION.value,
            "comprehension_mastery": 0.32,
            "exposure_count": 1,
            "next_review_at": "2026-01-03T09:00:00Z",
        }
    ]


def test_an_item_without_mastery_or_review_state_stays_with_nulls(
    api: TestClient, db_session: Session
) -> None:
    """`null`은 "아직 evidence 없음"이다. 0으로 바꿔 내리지 않고, 목록에서 빼지도 않는다."""
    user = _login(api, db_session)
    item = _make_learned_item(db_session, user, lemma="任せる")

    assert _items(api) == [
        {
            "learning_item_id": item.id,
            "lemma": "任せる",
            "item_type": LearningItemType.EXPRESSION.value,
            "comprehension_mastery": None,
            "exposure_count": 0,
            "next_review_at": None,
        }
    ]


def test_a_null_comprehension_mastery_row_is_not_reported_as_zero(
    api: TestClient, db_session: Session
) -> None:
    """`user_mastery` 행이 있는데 값이 NULL인 경우도 `null`이다."""
    user = _login(api, db_session)
    item = _make_learned_item(db_session, user, lemma="任せる")
    factories.make_mastery(
        db_session,
        user,
        item,
        comprehension_mastery=None,
        algorithm_version=ALGORITHM_VERSION_FILLER,
    )

    assert [row["comprehension_mastery"] for row in _items(api)] == [None]


def test_exposure_count_ignores_invalidated_exposures(api: TestClient, db_session: Session) -> None:
    """canonical source를 센다. flag 직후 cache 재계산이 어긋난 창에서 무효화된 노출이
    그대로 보이기 때문이다(05_API_SPEC.md)."""
    user = _login(api, db_session)
    item = _make_learned_item(db_session, user, lemma="任せる")
    study_session = _make_session(db_session, user)
    sentence = factories.make_sentence(db_session)
    valid = _make_presentation(db_session, user, study_session, completed=True)
    invalidated = _make_presentation(db_session, user, study_session, completed=True)
    factories.make_exposure(db_session, user, item, valid, sentence)
    dropped = factories.make_exposure(db_session, user, item, invalidated, sentence)
    dropped.invalidated_at = DEFAULT_START + timedelta(minutes=1)
    db_session.flush()

    assert [row["exposure_count"] for row in _items(api)] == [1]


def test_exposure_count_does_not_read_the_cache(api: TestClient, db_session: Session) -> None:
    """`review_states.meaningful_exposure_count`가 어긋나 있어도 canonical을 센다."""
    user = _login(api, db_session)
    item = _make_learned_item(db_session, user, lemma="任せる")
    review_state = factories.make_review_state(
        db_session, user, item, state=1, params_version=FSRS_PARAMS_VERSION_FILLER
    )
    review_state.meaningful_exposure_count = 9
    db_session.flush()

    assert [row["exposure_count"] for row in _items(api)] == [0]


def test_a_clicked_only_item_is_absent_from_item_history(
    api: TestClient, db_session: Session
) -> None:
    """눌러만 보고 지나간 item은 `user_item_learning_state` 행이 없으므로 목록에 없다.

    그 item에 노출과 click event를 붙여 둔다. 목록 대상을 `item_exposures`나
    `learning_events`로 잡은 구현은 여기서 빨개진다.
    """
    user = _login(api, db_session)
    learned = _make_learned_item(db_session, user, lemma="任せる")
    clicked = factories.make_learning_item(db_session, lemma="気が乗らない")
    study_session = _make_session(db_session, user)
    presentation = _make_presentation(db_session, user, study_session, completed=True)
    sentence = factories.make_sentence(db_session)
    factories.make_exposure(db_session, user, clicked, presentation, sentence)
    factories.make_event(
        db_session,
        user,
        study_session,
        client_event_id=uuid.uuid4(),
        event_type=EventType.ITEM_CLICKED,
        presentation=presentation,
        item=clicked,
    )

    items = _items(api)

    assert [row["learning_item_id"] for row in items] == [learned.id]


# --------------------------------------------------------------------------
# 읽기 전용 (05_API_SPEC.md: "둘 다 읽기 전용이다")
# --------------------------------------------------------------------------


def test_history_reads_do_not_touch_the_session(
    api: TestClient, db_session: Session, study_clock: MutableClock
) -> None:
    """조회가 `active_seconds`를 올리면 기록을 보는 행위가 학습 시간이 된다."""
    user = _login(api, db_session)
    study_session = _make_session(db_session, user)
    before = (
        study_session.last_activity_at,
        study_session.active_seconds,
        study_session.ended_at,
    )
    study_clock.advance(timedelta(minutes=4))

    _sessions(api)
    _items(api)
    db_session.refresh(study_session)

    assert (
        study_session.last_activity_at,
        study_session.active_seconds,
        study_session.ended_at,
    ) == before


def test_history_reads_create_no_rows(api: TestClient, db_session: Session) -> None:
    """event도 exposure도 learning state도 만들지 않는다."""
    user = _login(api, db_session)
    _make_session(db_session, user)
    _make_learned_item(db_session, user, lemma="任せる")
    counted = (LearningEvent, ItemExposure, UserItemLearningState, StudySession)
    before = {model.__name__: _count(db_session, model) for model in counted}

    _sessions(api)
    _items(api)

    assert {model.__name__: _count(db_session, model) for model in counted} == before


def _count(db: Session, model: type[DeclarativeBase]) -> int:
    return int(db.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())
