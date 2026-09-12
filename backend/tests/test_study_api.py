"""Study endpoint HTTP 계약 (05_API_SPEC.md).

`conftest.py`의 `db_client`를 쓰지 않는다. base_url이 http라서 `Secure` cookie가
httpx cookie jar에 저장되지 않고, 그러면 login은 200인데 이어지는 요청이 401이 되는
형태로 조용히 실패한다(test_auth_api.py와 같은 이유).

여기서 고정하는 것은 **응답의 모양**이다.

-   `/next` 응답 어디에도 `korean_translation`이 없다. 번역은 reveal에서만 나온다.
-   id는 전부 JSON number다(ADR-005).
-   Ready Pool이 비면 200 + `presentation: null`이다. 오류가 아니다.
-   남의 presentation은 404다. 403으로 갈라주면 그것이 존재 여부 oracle이 된다.

미인증 401은 여기서 다시 확인하지 않는다. `test_route_auth.py`가 **라우트 전수**로
검사하므로 여기에 endpoint별 사본을 두면 새 endpoint를 추가할 때 한쪽만 늘어난다.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import cast

import httpx2
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_now
from app.config import get_config
from app.main import create_app
from app.models import (
    ItemExposure,
    LearningEvent,
    Sentence,
    StudyPresentation,
    StudySession,
    User,
    UserMastery,
)
from app.models.enums import CandidateStatus, EventType, PresentationRole
from app.services.auth import hash_password
from app.services.events import (
    NC_EVENT_NAMESPACE,
    EventKeyConflictError,
    server_client_event_id,
)
from app.settings import get_settings
from tests import factories
from tests.clock import MutableClock

pytestmark = pytest.mark.integration

ORIGIN = "https://app.test"
PASSWORD = "correct horse battery staple"

# id를 받는 study endpoint의 request body. 값이 `_BODY_ID`면 그 자리에도 시험할 id를
# 넣는다. path 파라미터를 가진 라우트는 **전부** 여기에 있어야 하고, 없으면
# `test_every_id_endpoint_rejects_an_out_of_range_id`가 그 사실을 실패로 알린다.
_BODY_ID = "{id}"
_REQUEST_BODY: dict[str, dict[str, object] | None] = {
    "/api/study/session/{session_id}/next": None,
    "/api/study/session/{session_id}/finish": None,
    "/api/study/session/{session_id}/extend": {},
    "/api/study/presentations/{presentation_id}/complete": None,
    "/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click": {},
    "/api/study/presentations/{presentation_id}/items/{sentence_item_id}/explanation-revealed": {},
    "/api/study/presentations/{presentation_id}/translation/reveal": {},
    "/api/study/presentations/{presentation_id}/self-report": {
        "sentence_item_id": _BODY_ID,
        "value": "unknown",
    },
    "/api/study/presentations/{presentation_id}/probe-response": {
        "probe_id": _BODY_ID,
        "value": "known",
    },
    "/api/study/presentations/{presentation_id}/flag": {"reason": "unnatural"},
}

_TARGET_START = 5
_TARGET_END = 8


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


def _seed_ready_sentence(db: Session, user: User) -> Sentence:
    """`new` role로 바로 제시할 수 있는 문장 하나 (Ready invariant 충족)."""
    sentence = factories.make_sentence(db)
    item = factories.make_learning_item(db)
    sentence_item = factories.make_sentence_item(db, sentence, item, surface_form="任せる")
    factories.make_span(db, sentence_item, start=_TARGET_START, end=_TARGET_END)
    factories.make_explanation(db, sentence_item)
    candidate = factories.make_candidate(
        db,
        user,
        sentence,
        status=CandidateStatus.READY,
        presentation_role=PresentationRole.NEW,
    )
    factories.make_candidate_target(db, candidate, item)
    return sentence


def _start(api: TestClient) -> int:
    response = api.post("/api/study/session")
    assert response.status_code == 200
    session_id = response.json()["session"]["session_id"]
    assert isinstance(session_id, int)
    return int(session_id)


def _next(api: TestClient, session_id: int) -> httpx2.Response:
    return api.post(f"/api/study/session/{session_id}/next")


# --------------------------------------------------------------------------
# 응답 모양
# --------------------------------------------------------------------------


def test_the_next_response_never_carries_the_translation(
    api: TestClient, db_session: Session
) -> None:
    """필드가 없으면 새어 나갈 수 없다. reveal 전에는 존재 자체가 없어야 한다."""
    user = _login(api, db_session)
    sentence = _seed_ready_sentence(db_session, user)
    session_id = _start(api)

    response = _next(api, session_id)

    assert response.status_code == 200
    body = response.json()
    assert body["presentation"] is not None
    assert "korean_translation" not in json.dumps(body, ensure_ascii=False)
    assert sentence.korean_translation not in json.dumps(body, ensure_ascii=False)
    assert body["presentation"]["translation_revealed"] is False


def test_the_next_response_has_no_offsets_and_rebuilds_the_sentence(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    sentence = _seed_ready_sentence(db_session, user)
    session_id = _start(api)

    payload = _next(api, session_id).json()["presentation"]

    assert "".join(segment["text"] for segment in payload["render_segments"]) == sentence.japanese
    for segment in payload["render_segments"]:
        assert set(segment) == {"text", "sentence_item_id"}
    assert isinstance(payload["presentation_id"], int)
    assert isinstance(payload["sentence_id"], int)
    assert isinstance(payload["tappable_items"][0]["sentence_item_id"], int)
    assert isinstance(payload["tappable_items"][0]["learning_item_id"], int)


def test_revealing_the_translation_is_the_only_way_to_get_it(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    sentence = _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]

    response = api.post(
        f"/api/study/presentations/{presentation_id}/translation/reveal",
        json={"client_event_id": str(uuid.uuid4())},
    )

    assert response.status_code == 200
    assert response.json() == {"korean_translation": sentence.korean_translation}
    # 같은 presentation을 다시 받으면 reveal 사실이 반영된다.
    again = _next(api, session_id).json()["presentation"]
    assert again["translation_revealed"] is True


def test_an_empty_pool_answers_200_with_a_null_presentation(
    api: TestClient, db_session: Session
) -> None:
    """무한 spinner를 만들지 않는다(10_ERROR_HANDLING.md의 `Empty Pool`)."""
    _login(api, db_session)
    session_id = _start(api)

    response = _next(api, session_id)

    assert response.status_code == 200
    assert response.json() == {"presentation": None}


# --------------------------------------------------------------------------
# 소유권
# --------------------------------------------------------------------------


def test_another_users_presentation_answers_404_not_403(
    api: TestClient, db_session: Session
) -> None:
    cfg = get_config()
    other = factories.make_user(db_session)
    other_sentence = factories.make_sentence(db_session)
    other_session = factories.make_study_session(
        db_session, other, target_minutes=cfg.learning.default_session_minutes
    )
    other_candidate = factories.make_candidate(
        db_session, other, other_sentence, status=CandidateStatus.SHOWN
    )
    foreign = factories.make_presentation(
        db_session, other, other_session, other_candidate, other_sentence
    )
    _login(api, db_session)

    response = api.post(
        f"/api/study/presentations/{foreign.id}/complete",
    )

    assert response.status_code == 404
    assert foreign.completed_at is None


def test_another_users_session_answers_404(api: TestClient, db_session: Session) -> None:
    cfg = get_config()
    other = factories.make_user(db_session)
    other_session = factories.make_study_session(
        db_session, other, target_minutes=cfg.learning.default_session_minutes
    )
    _login(api, db_session)

    assert _next(api, other_session.id).status_code == 404
    assert api.post(f"/api/study/session/{other_session.id}/finish").status_code == 404


# --------------------------------------------------------------------------
# 한 문장을 끝까지
# --------------------------------------------------------------------------


def test_a_sentence_from_next_to_complete(api: TestClient, db_session: Session) -> None:
    """Core E2E 2~8단계를 HTTP로 훑는다. live LLM 호출은 한 번도 없다."""
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    payload = _next(api, session_id).json()["presentation"]
    presentation_id = payload["presentation_id"]
    sentence_item_id = payload["tappable_items"][0]["sentence_item_id"]

    clicked = api.post(
        f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click",
        json={"client_event_id": str(uuid.uuid4())},
    )
    assert clicked.status_code == 200
    assert clicked.json()["meaning_in_context"]

    revealed = api.post(
        f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}/explanation-revealed",
        json={"client_event_id": str(uuid.uuid4())},
    )
    assert revealed.status_code == 204

    reported = api.post(
        f"/api/study/presentations/{presentation_id}/self-report",
        json={
            "client_event_id": str(uuid.uuid4()),
            "sentence_item_id": sentence_item_id,
            "value": "unknown",
        },
    )
    assert reported.status_code == 204

    completed = api.post(f"/api/study/presentations/{presentation_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["presentation_id"] == presentation_id

    exposures = db_session.execute(
        sa.select(sa.func.count())
        .select_from(ItemExposure)
        .where(ItemExposure.study_presentation_id == presentation_id)
    ).scalar_one()
    assert exposures == 1


def test_next_after_complete_moves_on(api: TestClient, db_session: Session) -> None:
    """`/next`가 직전 문장을 암묵 완료시키지 않는다. client가 `/complete`를 호출한다."""
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    first = _next(api, session_id).json()["presentation"]["presentation_id"]

    repeated = _next(api, session_id).json()["presentation"]["presentation_id"]
    assert repeated == first

    api.post(f"/api/study/presentations/{first}/complete")
    second = _next(api, session_id).json()["presentation"]["presentation_id"]

    assert second != first
    count = db_session.execute(
        sa.select(sa.func.count())
        .select_from(StudyPresentation)
        .where(StudyPresentation.study_session_id == session_id)
    ).scalar_one()
    assert count == 2


def test_finishing_closes_the_open_presentation_over_http(
    api: TestClient, db_session: Session
) -> None:
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]

    response = api.post(f"/api/study/session/{session_id}/finish")

    assert response.status_code == 200
    assert response.json()["ended_at"] is not None
    exposures = db_session.execute(
        sa.select(sa.func.count())
        .select_from(ItemExposure)
        .where(ItemExposure.study_presentation_id == presentation_id)
    ).scalar_one()
    assert exposures == 1


# --------------------------------------------------------------------------
# 오류 응답
# --------------------------------------------------------------------------


def test_an_invalid_probe_id_answers_400(api: TestClient, db_session: Session) -> None:
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]

    response = api.post(
        f"/api/study/presentations/{presentation_id}/probe-response",
        json={
            "client_event_id": str(uuid.uuid4()),
            "probe_id": presentation_id,
            "value": "known",
        },
    )

    assert response.status_code == 400


def test_flagging_answers_204_and_quarantines(api: TestClient, db_session: Session) -> None:
    user = _login(api, db_session)
    sentence = _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]

    response = api.post(
        f"/api/study/presentations/{presentation_id}/flag",
        json={"client_event_id": str(uuid.uuid4()), "reason": "unnatural"},
    )

    assert response.status_code == 204
    db_session.refresh(sentence)
    assert sentence.status.value == "quarantined"


def test_an_unknown_flag_reason_is_rejected(api: TestClient, db_session: Session) -> None:
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]

    response = api.post(
        f"/api/study/presentations/{presentation_id}/flag",
        json={"client_event_id": str(uuid.uuid4()), "reason": "boring"},
    )

    assert response.status_code == 422


def test_extending_takes_the_minutes_from_config(api: TestClient, db_session: Session) -> None:
    cfg = get_config()
    _login(api, db_session)
    session_id = _start(api)
    key = str(uuid.uuid4())

    first = api.post(f"/api/study/session/{session_id}/extend", json={"client_event_id": key})
    resent = api.post(f"/api/study/session/{session_id}/extend", json={"client_event_id": key})

    assert first.status_code == 200
    assert first.json()["extended_minutes"] == cfg.learning.extra_session_minutes
    assert resent.json()["extended_minutes"] == cfg.learning.extra_session_minutes


def test_starting_a_session_maps_a_service_error_instead_of_500(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /session`도 service 예외를 상태 코드로 옮긴다.

    이 handler만 매핑 밖에 있어서 500 `Internal Server Error`가 나갔다. 매핑은
    이제 router의 `route_class`가 걸므로 handler가 따로 할 일이 없다
    (`test_route_error_mapping.py`가 전수로 고정한다).
    """
    _login(api, db_session)

    def boom(*args: object, **kwargs: object) -> None:
        raise EventKeyConflictError("session_started key collided")

    monkeypatch.setattr("app.services.study_session.start_or_resume", boom)

    response = api.post("/api/study/session")

    assert response.status_code == 409
    assert "Internal Server Error" not in response.text


def _id_endpoints(api: TestClient) -> list[str]:
    """path 파라미터를 받는 study 라우트의 경로 템플릿 전부."""
    paths: list[str] = []
    app = cast(FastAPI, api.app)
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        path = context.path or ""
        if not isinstance(route, APIRoute) or not path.startswith("/api/study"):
            continue
        if route.dependant.path_params:
            paths.append(path)
    return paths


@pytest.mark.parametrize(
    "value",
    # bigint 상한 바로 위/한참 위, 상한 자체, 그리고 어떤 행도 갖지 않는 0과 음수.
    [2**63, 10**30, 2**63 - 1, 0, -1],
    ids=["just-over-bigint", "far-over-bigint", "bigint-max", "zero", "negative"],
)
def test_every_id_endpoint_rejects_an_out_of_range_id(
    api: TestClient, db_session: Session, value: int
) -> None:
    """client 입력으로 500을 만들 수 없다. 없는 id와 같은 404다.

    bigint 범위 밖 정수를 조회에 넘기면 psycopg가 `NumericValueOutOfRange`를 던져
    500이 나갔다. 존재 여부 oracle을 만들지 않으려고 상한 안쪽 값과 같은 404다.
    """
    _login(api, db_session)
    paths = _id_endpoints(api)
    assert len(paths) >= 10, f"id를 받는 라우트가 {len(paths)}개만 열거됐다"

    for path in paths:
        assert path in _REQUEST_BODY, f"{path}의 request body가 이 테스트에 없다"
        extra = _REQUEST_BODY[path]
        body: dict[str, object] | None = None
        if extra is not None:
            body = {"client_event_id": str(uuid.uuid4())}
            body.update({k: (value if v == _BODY_ID else v) for k, v in extra.items()})
        response = api.post(re.sub(r"\{[^}]+\}", str(value), path), json=body)
        assert response.status_code == 404, f"{path} <- {value}: {response.status_code}"
        assert response.json() == {"detail": "Not found"}, path


# --------------------------------------------------------------------------
# 키 공간 분리 (05_API_SPEC.md, ADR-008의 `후속 결정`)
# --------------------------------------------------------------------------


def _stolen_finish_key(session_id: int) -> str:
    """server가 나중에 쓸 key. 공개 상수와 공개된 자연키 형식으로 누구나 계산한다."""
    return str(server_client_event_id(EventType.SESSION_FINISHED, study_session_id=session_id))


def test_a_client_cannot_take_the_key_that_finish_will_use(
    api: TestClient, db_session: Session
) -> None:
    """v5 key 선점이 422로 막히고 `/finish`가 살아 있다.

    막지 않으면 그 세션은 영구히 끝나지 않는다(ADR-008). event도 남으면 안 된다 ---
    body 검증 실패이므로 요청은 handler에 닿지 않는다.
    """
    user = _login(api, db_session)
    session_id = _start(api)
    stolen = _stolen_finish_key(session_id)

    preempt = api.post(f"/api/study/session/{session_id}/extend", json={"client_event_id": stolen})

    assert preempt.status_code == 422
    recorded = db_session.execute(
        sa.select(sa.func.count())
        .select_from(LearningEvent)
        .where(LearningEvent.user_id == user.id, LearningEvent.client_event_id == stolen)
    ).scalar_one()
    assert recorded == 0

    finished = api.post(f"/api/study/session/{session_id}/finish")
    assert finished.status_code == 200
    assert finished.json()["ended_at"] is not None


def test_a_client_cannot_brick_the_idle_timeout_with_a_v5_key(
    api: TestClient, db_session: Session, study_clock: MutableClock
) -> None:
    """선점이 성공하면 idle timeout 만료도 같은 key를 쓰므로 `POST /session`이 영구 500이다.

    세션이 끝나지도, 새로 생기지도 않는 상태 --- DB를 직접 고치지 않으면 복구되지
    않는다. 그것이 이 결함의 핵심이었다.
    """
    cfg = get_config()
    _login(api, db_session)
    first_id = _start(api)

    preempt = api.post(
        f"/api/study/session/{first_id}/extend",
        json={"client_event_id": _stolen_finish_key(first_id)},
    )
    assert preempt.status_code == 422

    study_clock.advance(timedelta(minutes=cfg.session.study_session_idle_timeout_minutes + 1))
    restarted = api.post("/api/study/session")

    assert restarted.status_code == 200
    body = restarted.json()
    assert body["timed_out_session_id"] == first_id
    assert body["session"]["session_id"] != first_id


def test_no_endpoint_accepts_a_client_event_id_outside_version_4(
    api: TestClient, db_session: Session
) -> None:
    """검증이 `ClientEventRequest` 한 곳에만 있어도 전 endpoint에 걸리는지 본다.

    endpoint마다 붙이는 방식이면 하나를 빠뜨린 곳이 그대로 구멍이다. 여기서 훑는
    목록은 `_REQUEST_BODY`이고, 새 endpoint가 빠지면
    `test_every_id_endpoint_rejects_an_out_of_range_id`가 먼저 그 사실을 알린다.

    이 목록은 손으로 유지하므로 목록 자체가 헐거워지는 것은 막지 못한다. 라우트를
    훑는 전수 검사는 `test_route_error_mapping.py`의
    `test_every_client_supplied_event_key_rejects_a_server_key`다. 여기서는 검증이
    **실제 HTTP 경로에서** 도는지를 본다.
    """
    _login(api, db_session)
    v5 = str(uuid.uuid5(NC_EVENT_NAMESPACE, "anything at all"))
    checked = 0

    for path, extra in _REQUEST_BODY.items():
        if extra is None:
            continue
        body: dict[str, object] = {"client_event_id": v5}
        body.update({k: (1 if v == _BODY_ID else v) for k, v in extra.items()})
        response = api.post(re.sub(r"\{[^}]+\}", "1", path), json=body)
        assert response.status_code == 422, f"{path} -> {response.status_code}"
        checked += 1

    assert checked >= 6, f"client_event_id를 받는 endpoint가 {checked}개만 검사됐다"


# --------------------------------------------------------------------------
# 세션·presentation 상태 게이트 (05_API_SPEC.md, ADR-014)
# --------------------------------------------------------------------------


def _interaction_requests(
    presentation_id: int, sentence_item_id: int
) -> list[tuple[str, dict[str, object]]]:
    """상호작용 5종. 닫힌 session / 완료된 presentation에서 전부 409여야 한다."""
    return [
        (
            f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click",
            {"client_event_id": str(uuid.uuid4())},
        ),
        (
            f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}"
            "/explanation-revealed",
            {"client_event_id": str(uuid.uuid4())},
        ),
        (
            f"/api/study/presentations/{presentation_id}/translation/reveal",
            {"client_event_id": str(uuid.uuid4())},
        ),
        (
            f"/api/study/presentations/{presentation_id}/self-report",
            {
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": sentence_item_id,
                "value": "known",
            },
        ),
        (
            f"/api/study/presentations/{presentation_id}/probe-response",
            {"client_event_id": str(uuid.uuid4()), "probe_id": 1, "value": "known"},
        ),
    ]


def test_a_finished_session_rejects_the_five_interactions(
    api: TestClient, db_session: Session, study_clock: MutableClock
) -> None:
    """끝난 세션의 상호작용은 409다. 새 evidence도, 갱신된 시계도 남지 않는다.

    self-report는 끝난 세션에서 **새 mastery 행을 만들었다.** presentation을 닫을 때
    exposure 확정과 무신호 처리가 이미 끝났으므로 그 뒤의 explicit evidence는 같은
    노출을 두 번 평가한다(ADR-014). probe-response가 400이 아니라 409인 것은 판정
    순서가 소유권 -> 상태 -> 그 밖의 검증이기 때문이다.
    """
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    payload = _next(api, session_id).json()["presentation"]
    presentation_id = payload["presentation_id"]
    sentence_item_id = payload["tappable_items"][0]["sentence_item_id"]
    assert api.post(f"/api/study/session/{session_id}/finish").status_code == 200
    session = db_session.get(StudySession, session_id)
    assert session is not None
    last_activity_at = session.last_activity_at
    # 시계를 움직여 둔다. 멈춰 있으면 `touch()`가 같은 값을 다시 써도 아래 단언이
    # 통과해 버려서 아무것도 지키지 못한다.
    study_clock.advance(timedelta(minutes=1))

    for path, body in _interaction_requests(presentation_id, sentence_item_id):
        response = api.post(path, json=body)
        assert response.status_code == 409, f"{path} -> {response.status_code}"
        assert response.json() == {"detail": "Session is already finished"}, path

    db_session.refresh(session)
    assert session.last_activity_at == last_activity_at
    mastery_rows = db_session.execute(
        sa.select(sa.func.count()).select_from(UserMastery).where(UserMastery.user_id == user.id)
    ).scalar_one()
    assert mastery_rows == 0


def test_completing_again_after_finish_answers_200(
    api: TestClient, db_session: Session, study_clock: MutableClock
) -> None:
    """성공한 `/complete`의 재시도가 그 사이 도착한 `/finish` 때문에 실패로 보이면 안 된다."""
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]
    api.post(f"/api/study/session/{session_id}/finish")
    session = db_session.get(StudySession, session_id)
    assert session is not None
    last_activity_at = session.last_activity_at
    study_clock.advance(timedelta(minutes=1))

    response = api.post(f"/api/study/presentations/{presentation_id}/complete")

    assert response.status_code == 200
    assert response.json()["presentation_id"] == presentation_id
    db_session.refresh(session)
    # 이미 끝난 요청의 재시도다. 끝난 세션의 시계를 다시 밀지 않는다.
    assert session.last_activity_at == last_activity_at


def test_a_completed_presentation_rejects_the_five_interactions(
    api: TestClient, db_session: Session
) -> None:
    """session이 열려 있어도 완료된 presentation이면 409다.

    이중 평가는 열린 session 안에서도 일어난다(`/complete` 직후 같은 pid).
    """
    user = _login(api, db_session)
    _seed_ready_sentence(db_session, user)
    _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    payload = _next(api, session_id).json()["presentation"]
    presentation_id = payload["presentation_id"]
    sentence_item_id = payload["tappable_items"][0]["sentence_item_id"]
    assert api.post(f"/api/study/presentations/{presentation_id}/complete").status_code == 200

    for path, body in _interaction_requests(presentation_id, sentence_item_id):
        response = api.post(path, json=body)
        assert response.status_code == 409, f"{path} -> {response.status_code}"
        assert response.json() == {"detail": "Presentation is already completed"}, path

    # 세션은 계속 살아 있다. 다음 문장은 정상으로 나온다.
    assert _next(api, session_id).json()["presentation"] is not None


def test_flagging_still_works_after_the_session_is_finished(
    api: TestClient, db_session: Session, study_clock: MutableClock
) -> None:
    """`/flag`만 상태 게이트의 예외다 (10_ERROR_HANDLING.md의 `Content Flag 동작`).

    exposure는 presentation을 닫을 때 생기므로 "이미 생성된 `item_exposures` 무효화"는
    **완료 이후의 flag만** 참으로 만든다. flag까지 막으면 그 조항이 도달 불가능해진다.
    단 끝난 세션의 시계는 밀지 않는다(ADR-014).
    """
    user = _login(api, db_session)
    sentence = _seed_ready_sentence(db_session, user)
    session_id = _start(api)
    presentation_id = _next(api, session_id).json()["presentation"]["presentation_id"]
    api.post(f"/api/study/session/{session_id}/finish")
    session = db_session.get(StudySession, session_id)
    assert session is not None
    last_activity_at = session.last_activity_at
    exposures = (
        db_session.execute(
            sa.select(ItemExposure).where(ItemExposure.study_presentation_id == presentation_id)
        )
        .scalars()
        .all()
    )
    assert exposures, "완료 시점에 exposure가 생겼어야 이 테스트가 의미를 갖는다"
    study_clock.advance(timedelta(minutes=1))

    response = api.post(
        f"/api/study/presentations/{presentation_id}/flag",
        json={"client_event_id": str(uuid.uuid4()), "reason": "unnatural"},
    )

    assert response.status_code == 204
    db_session.refresh(sentence)
    assert sentence.status.value == "quarantined"
    for exposure in exposures:
        db_session.refresh(exposure)
        assert exposure.invalidated_at is not None
    db_session.refresh(session)
    assert session.last_activity_at == last_activity_at


def test_ownership_is_decided_before_the_state_gate(api: TestClient, db_session: Session) -> None:
    """남의 것은 상태와 무관하게 404다. 409로 갈라주면 그것이 존재 여부 oracle이 된다."""
    cfg = get_config()
    other = factories.make_user(db_session)
    other_sentence = factories.make_sentence(db_session)
    other_session = factories.make_study_session(
        db_session, other, target_minutes=cfg.learning.default_session_minutes
    )
    other_session.ended_at = other_session.last_activity_at
    other_candidate = factories.make_candidate(
        db_session, other, other_sentence, status=CandidateStatus.SHOWN
    )
    foreign = factories.make_presentation(
        db_session, other, other_session, other_candidate, other_sentence
    )
    foreign.completed_at = other_session.last_activity_at
    db_session.flush()
    _login(api, db_session)

    response = api.post(
        f"/api/study/presentations/{foreign.id}/self-report",
        json={
            "client_event_id": str(uuid.uuid4()),
            "sentence_item_id": 1,
            "value": "known",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_reading_the_open_session_returns_null_when_there_is_none(
    api: TestClient, db_session: Session
) -> None:
    _login(api, db_session)

    response = api.get("/api/study/session")

    assert response.status_code == 200
    assert response.json() == {"session": None}
