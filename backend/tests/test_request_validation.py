"""422 응답이 제출된 값을 반향하지 않는다 (10_ERROR_HANDLING.md).

FastAPI 기본 handler는 pydantic 오류의 `input`을 그대로 내보낸다. 그리고 pydantic은
필드 하나가 어긋나면 **body 전체**를 `input`에 싣는다. 그래서 client가 `loginId`처럼
이름 하나만 틀리거나 body를 배열로 감싸기만 해도 평문 password가 422 본문으로
돌아 나왔다 --- 터널/프록시 로그와 브라우저 HAR에 그대로 남는 경로다.

`app/main.py`의 `_validation_error_handler`가 `input`/`ctx`를 지운다. 여기서는 그
handler가 실제 요청에서 도는지, 그리고 `loc`/`msg`가 남아 진단 가치가 살아 있는지를
본다. 상태 코드는 422 그대로다.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.conftest import STUDY_PASSWORD, StudyApi

pytestmark = pytest.mark.integration

# 응답 본문에 나타나면 안 되는 값. 실제 password와 겹치지 않는 표식이어야
# "우연히 없었다"와 구분된다.
SECRET = "PLAINTEXT-SECRET-PW"

# study 요청에도 같은 규칙이 걸리는지 볼 때 쓰는 표식. secret은 아니지만 규칙은 하나다.
STUDY_MARKER = "LEAKED-STUDY-VALUE"


def _details(payload: object) -> list[dict[str, Any]]:
    assert isinstance(payload, dict), payload
    detail = payload["detail"]
    assert isinstance(detail, list), detail
    return detail


@pytest.mark.parametrize(
    ("label", "body"),
    [
        # PWA client가 camelCase로 보내는 경우.
        ("camel-case-field", {"loginId": "seed-user", "password": SECRET}),
        # 필드명 오타.
        ("typo-field", {"login_id": "seed-user", "passwordd": SECRET}),
        # 재시도 래퍼가 payload를 배열로 감싸는 경우.
        ("array-wrapped", [{"login_id": "seed-user", "password": SECRET}]),
    ],
)
def test_login_422_does_not_echo_the_submitted_password(
    study_api: StudyApi, label: str, body: object
) -> None:
    response = study_api.client.post("/api/auth/login", json=body)

    assert response.status_code == 422, label
    assert SECRET not in response.text, f"{label}: 평문 password가 422 본문에 실렸다"


def test_a_login_422_still_says_which_field_is_wrong(study_api: StudyApi) -> None:
    """반향만 지운다. 무엇이 잘못됐는지는 client가 알 수 있어야 한다."""
    response = study_api.client.post("/api/auth/login", json={"login_id": "seed-user"})

    assert response.status_code == 422
    (error,) = _details(response.json())
    assert error["loc"] == ["body", "password"]
    assert error["type"] == "missing"
    assert error["msg"]
    assert "input" not in error and "ctx" not in error


def test_a_correct_login_still_works(study_api: StudyApi) -> None:
    """handler가 정상 경로를 건드리지 않았는지 본다."""
    response = study_api.client.post(
        "/api/auth/login",
        json={"login_id": study_api.user.login_id, "password": STUDY_PASSWORD},
    )

    assert response.status_code == 200


def _study_422_bodies() -> list[tuple[str, dict[str, object]]]:
    """study endpoint에서 422가 나는 body들. 전부 표식을 담고 있다."""
    v5 = str(uuid.uuid5(uuid.NAMESPACE_URL, "anything"))
    return [
        ("uuid-parsing", {"client_event_id": STUDY_MARKER}),
        # v4가 아닌 key는 `ClientEventRequest`의 field_validator가 거부한다(ADR-008).
        # 그 오류의 `ctx`에는 ValueError가 들어 있다.
        ("client-key-version", {"client_event_id": v5}),
        (
            "enum-value",
            {
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": 1,
                "value": STUDY_MARKER,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("label", "body"), _study_422_bodies(), ids=[label for label, _ in _study_422_bodies()]
)
def test_study_422_does_not_echo_the_submitted_body(
    study_api: StudyApi, label: str, body: dict[str, object]
) -> None:
    """auth만이 아니라 모든 endpoint에 같은 규칙이 걸린다."""
    response = study_api.client.post("/api/study/presentations/1/self-report", json=body)

    assert response.status_code == 422, response.text
    assert STUDY_MARKER not in response.text, f"{label}: 제출된 값이 422 본문에 실렸다"
    for error in _details(response.json()):
        assert "input" not in error and "ctx" not in error, error
