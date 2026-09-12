"""라우트 전수 오류 매핑 검사 (05_API_SPEC.md, 10_ERROR_HANDLING.md).

`test_route_auth.py`와 같은 형태다. 배선 하나를 빠뜨린 endpoint가 조용히 다른
응답을 내는 것을 막는다 --- 실제로 `POST /api/study/session`만 `_http_errors()`
밖에 있어서 service 예외가 500으로 나갔다.

두 층으로 본다.

-   **매핑이 실제로 도는가**: `ErrorMappedRoute`에 올린 endpoint가 service 예외를
    어떤 상태 코드로 바꾸는지 요청으로 확인한다. 이것이 없으면 아래 구조 검사가
    "class가 붙어 있다"만 보고 초록이 된다.
-   **모든 endpoint가 그 위에 있는가**: study 라우트 전수를 훑는다. handler에
    `with`를 적는 방식이 아니라 router의 `route_class`로 걸리므로, 새 endpoint는
    `app.api.study.router`에 올리기만 하면 아무것도 하지 않아도 상속한다. 다른
    router에 올리면 여기서 빨개진다.

id 범위 검사도 같은 방식이다. client가 보내는 id는 path든 body든 `ResourceId`여야
하고, `int`로 선언한 새 파라미터가 생기면 전수 검사가 잡는다. DB에 bigint 범위 밖
정수를 넘기면 psycopg가 `NumericValueOutOfRange`를 던져 500이 나간다.

client 발급 event key도 같다. body의 `uuid.UUID` 필드를 전부 열거해서 server 발급
v5 key를 거부하는지 본다(ADR-008의 `키 공간 분리`).

DB가 필요 없다. 라우팅 표면과 pydantic 선언만 본다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any, get_args

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.api.study import ErrorMappedRoute
from app.main import create_app
from app.schemas.study import BIGINT_MAX, IdOutOfRangeError
from app.services.events import (
    NC_EVENT_NAMESPACE,
    EventKeyConflictError,
    ServerEventKeyConflictError,
)
from app.services.interactions import (
    EvidenceAlreadyRecordedError,
    ExplanationMissingError,
    ProbeNotFoundError,
    SentenceItemNotFoundError,
)
from app.services.presentation import PresentationClosedError, PresentationNotFoundError
from app.services.study_session import StudySessionClosedError, StudySessionNotFoundError

STUDY_PREFIX = "/api/study"

# 05_API_SPEC.md의 `Study Session` / `Interaction` endpoint 수. 늘어나는 것은
# 정상이지만 줄어들면 아래 전수 검사가 헐거워진 것이다.
STUDY_ROUTE_COUNT = 12

# 예외 메시지에는 내부 사정(테이블, id, 이유)이 들어 있다. 응답에 그대로 실리는지
# 보려면 응답 문구와 겹치지 않는 표식이 필요하다.
INTERNAL_DETAIL = "study_sessions row 41 belongs to user 7"

# 05_API_SPEC.md: 소유권(404) -> 상태 게이트(409) -> 그 밖의 검증(400).
# `ExplanationMissingError`는 Ready invariant 위반이므로 client 잘못이 아니다(500).
EXPECTED_STATUS: list[tuple[Exception, int]] = [
    (StudySessionNotFoundError(INTERNAL_DETAIL), 404),
    (PresentationNotFoundError(INTERNAL_DETAIL), 404),
    (SentenceItemNotFoundError(INTERNAL_DETAIL), 404),
    # 범위 밖 id는 어떤 행도 가리킬 수 없다. 존재하지 않는 id와 같이 404다.
    (IdOutOfRangeError(INTERNAL_DETAIL), 404),
    (StudySessionClosedError(INTERNAL_DETAIL), 409),
    (PresentationClosedError(INTERNAL_DETAIL), 409),
    # 노출당 evidence 상한. 게이트 409와 코드는 같고 사유 문구가 다르다(ADR-018).
    (EvidenceAlreadyRecordedError(INTERNAL_DETAIL), 409),
    (EventKeyConflictError(INTERNAL_DETAIL), 409),
    # server 발급 key 충돌은 client가 만들 수 없다. 409로 되돌려 주면 고칠 수 없는
    # 요청을 재시도하게 만든다(05_API_SPEC.md의 `키 공간 분리`).
    (ServerEventKeyConflictError(INTERNAL_DETAIL), 500),
    (ProbeNotFoundError(INTERNAL_DETAIL), 400),
    (ExplanationMissingError(INTERNAL_DETAIL), 500),
]


def _study_routes(app: FastAPI) -> list[tuple[str, APIRoute]]:
    """`/api/study` 아래의 (경로, 라우트). prefix 결합은 FastAPI에게 맡긴다."""
    found: list[tuple[str, APIRoute]] = []
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        path = context.path or ""
        if isinstance(route, APIRoute) and path.startswith(STUDY_PREFIX):
            found.append((path, route))
    return found


# --------------------------------------------------------------------------
# 매핑이 실제로 도는가
# --------------------------------------------------------------------------


def _one_route_app(exc: Exception, route_class: type[APIRoute]) -> FastAPI:
    router = APIRouter(route_class=route_class)

    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise exc

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.parametrize(
    ("exc", "expected"), EXPECTED_STATUS, ids=[type(e).__name__ for e, _ in EXPECTED_STATUS]
)
def test_the_route_class_maps_each_service_exception(exc: Exception, expected: int) -> None:
    client = TestClient(_one_route_app(exc, ErrorMappedRoute))

    response = client.get("/boom")

    assert response.status_code == expected
    # provider/DB 내부 사정을 응답에 담지 않는다(10_ERROR_HANDLING.md).
    assert INTERNAL_DETAIL not in response.text


@pytest.mark.parametrize(
    "exc",
    [exc for exc, status_code in EXPECTED_STATUS if status_code != 500],
    ids=[type(exc).__name__ for exc, status_code in EXPECTED_STATUS if status_code != 500],
)
def test_a_plain_route_leaks_the_service_exception(exc: Exception) -> None:
    """위 검사에 이빨이 있는지 본다.

    `ErrorMappedRoute`를 떼면 매핑이 사라지고 전부 500이 된다. 이것이 성립하지
    않으면(FastAPI가 어딘가에서 대신 매핑해 주면) 위 검사는 route class가 없어도
    통과하므로 아무것도 지키지 못한다.
    """
    client = TestClient(_one_route_app(exc, APIRoute), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500


# --------------------------------------------------------------------------
# 모든 endpoint가 그 위에 있는가
# --------------------------------------------------------------------------


def test_every_study_route_inherits_the_error_mapping() -> None:
    """handler 하나가 매핑 밖에 있으면 그 endpoint만 500을 흘린다."""
    routes = _study_routes(create_app())

    assert len(routes) >= STUDY_ROUTE_COUNT, (
        f"study 라우트가 {len(routes)}개만 열거됐다. 검사가 빈 목록 위에서 통과하고 있다"
    )
    unmapped = [path for path, route in routes if not isinstance(route, ErrorMappedRoute)]
    assert unmapped == [], (
        f"{unmapped}이(가) 예외 매핑 밖에 있다. `app.api.study.router`에 올려라 "
        "(그 router의 route_class가 매핑을 건다)"
    )


# --------------------------------------------------------------------------
# client가 보내는 id는 전부 범위 검사를 거치는가
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClientId:
    """client가 값을 정하는 id 파라미터 하나."""

    where: str
    name: str
    annotation: Any
    metadata: tuple[Any, ...]
    # body 필드면 그 필드를 선언한 model. path/query 파라미터면 None이다. 필드 하나만
    # 떼어내면 model에 붙은 `field_validator`가 보이지 않으므로 owner가 필요하다.
    owner: type[BaseModel] | None = None

    @property
    def base_type(self) -> object:
        # `Annotated[int, ...]`이면 int를 꺼낸다. path 파라미터는 Annotated 통째로,
        # body 필드는 (annotation, metadata)로 쪼개져 들어온다.
        if hasattr(self.annotation, "__metadata__"):
            return self.annotation.__origin__
        return self.annotation

    @property
    def is_integer_id(self) -> bool:
        # `client_event_id`는 UUID다. 여기서 걸러지고 아래 `is_uuid_id`가 받는다.
        return self.name.endswith("_id") and self.base_type is int

    @property
    def is_uuid_id(self) -> bool:
        return self.name.endswith("_id") and self.base_type is uuid.UUID

    def rejects(self, value: int) -> bool:
        declared: Any = (
            Annotated[(self.annotation, *self.metadata)] if self.metadata else self.annotation
        )
        adapter: TypeAdapter[Any] = TypeAdapter(declared)
        try:
            adapter.validate_python(value)
        except IdOutOfRangeError:
            return True
        return False

    def field_error_for(self, value: object) -> bool:
        """이 필드에 `value`를 넣었을 때 **이 필드에** 검증 오류가 붙는가.

        owner model 통째로 검증한다. 그래야 `field_validator`처럼 필드 annotation
        밖에 사는 검증도 함께 돈다(`ClientEventRequest._must_be_random_uuid`).
        다른 필수 필드는 `missing`으로 뜨지만 loc이 달라 판정에 끼어들지 않는다.
        """
        if self.owner is None:
            return False
        try:
            self.owner.model_validate({self.name: value})
        except ValidationError as exc:
            return any(error["loc"] == (self.name,) for error in exc.errors())
        return False


def _nested_models(annotation: object) -> list[type[BaseModel]]:
    """annotation 안에 들어 있는 model 전부.

    `Model`뿐 아니라 `Model | None`과 `list[Model]` 안도 본다. 여기서 멈추면 그 안의
    id 필드가 아래 전수 검사를 통째로 빠져나간다.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [nested for arg in get_args(annotation) for nested in _nested_models(arg)]


def _model_ids(
    model: type[BaseModel], where: str, seen: set[type[BaseModel]]
) -> Iterator[ClientId]:
    if model in seen:
        return
    seen.add(model)
    for name, info in model.model_fields.items():
        annotation = info.annotation
        nested = _nested_models(annotation)
        if nested:
            for sub in nested:
                yield from _model_ids(sub, where, seen)
            continue
        yield ClientId(
            where=where,
            name=name,
            annotation=annotation,
            metadata=tuple(info.metadata),
            owner=model,
        )


def _client_ids(app: FastAPI) -> Iterator[ClientId]:
    """path/query 파라미터와 request body 필드 전부."""
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        where = f"{sorted(context.methods or set())} {context.path}"
        for field in [*route.dependant.path_params, *route.dependant.query_params]:
            yield ClientId(
                where=f"{where} (path/query)",
                name=field.name,
                annotation=field.field_info.annotation,
                metadata=tuple(field.field_info.metadata),
            )
        body = route.body_field
        model = None if body is None else body.field_info.annotation
        if isinstance(model, type) and issubclass(model, BaseModel):
            yield from _model_ids(model, f"{where} (body)", set())


def test_the_id_audit_sees_the_declared_parameters() -> None:
    """아래 전수 검사가 빈 목록 위에서 통과하지 않게 한다."""
    ids = [cid for cid in _client_ids(create_app()) if cid.is_integer_id]

    names = {cid.name for cid in ids}
    assert {"session_id", "presentation_id", "sentence_item_id", "probe_id"} <= names, names


@pytest.mark.parametrize("value", [BIGINT_MAX + 1, 10**30, 0, -1])
def test_every_client_supplied_id_is_range_checked(value: int) -> None:
    """새 endpoint가 id를 `int`로 선언하면 여기서 빨개진다.

    범위 밖 정수를 그대로 조회에 넘기면 psycopg가 던지는 오류가 500으로 나간다.
    `app.schemas.study.ResourceId`로 선언하면 404가 된다.
    """
    unchecked = [
        f"{cid.where} {cid.name}"
        for cid in _client_ids(create_app())
        if cid.is_integer_id and not cid.rejects(value)
    ]

    assert unchecked == [], (
        f"{unchecked}이(가) 범위 밖 id를 통과시킨다. `app.schemas.study.ResourceId`로 선언하라"
    )


# --------------------------------------------------------------------------
# client가 발급하는 event key는 전부 v4 검사를 거치는가
#
# 위 id 검사와 같은 방식으로, 손으로 유지하는 목록이 아니라 앱의 라우트를 훑는다.
# 목록 방식이면 path 파라미터 없이 `client_event_id`를 직접 선언하는 새 endpoint가
# 아무 테스트도 빨갛게 만들지 않고 키 선점 결함(ADR-008)을 되살린다.
# --------------------------------------------------------------------------

# 05_API_SPEC.md에서 client가 key를 발급하는 endpoint 수. 줄어들면 검사가 헐거워진 것이다.
CLIENT_KEY_FIELD_COUNT = 7

# server가 나중에 쓸 key. 공개 상수와 공개된 자연키 형식으로 누구나 계산한다.
STOLEN_SERVER_KEY = str(uuid.uuid5(NC_EVENT_NAMESPACE, "session_finished:1"))


def _client_key_fields(app: FastAPI) -> list[ClientId]:
    return [cid for cid in _client_ids(app) if cid.is_uuid_id]


def test_the_client_key_audit_sees_the_declared_fields() -> None:
    """아래 전수 검사가 빈 목록 위에서, 또 "전부 거부"로 통과하지 않게 한다."""
    fields = _client_key_fields(create_app())

    assert {cid.name for cid in fields} == {"client_event_id"}, fields
    assert len(fields) >= CLIENT_KEY_FIELD_COUNT, (
        f"client key를 받는 필드가 {len(fields)}개만 열거됐다"
    )
    # v4는 통과해야 한다. 그렇지 않으면 아래 검사는 "무엇을 넣어도 거부"라서 통과한다.
    accepted = [cid.where for cid in fields if cid.field_error_for(str(uuid.uuid4()))]
    assert accepted == [], f"{accepted}이(가) 정상 v4 key를 거부한다"


def test_every_client_supplied_event_key_rejects_a_server_key() -> None:
    """새 endpoint가 `ClientEventRequest`를 거치지 않으면 여기서 빨개진다.

    v5 key를 client가 선점하면 `/finish`가 영구 409가 되고 idle timeout 만료까지
    막혀 세션이 끝나지도 새로 생기지도 않는다(ADR-008의 `키 공간 분리`).
    """
    unchecked = [
        f"{cid.where} {cid.name}"
        for cid in _client_key_fields(create_app())
        if not cid.field_error_for(STOLEN_SERVER_KEY)
    ]

    assert unchecked == [], (
        f"{unchecked}이(가) server 발급 v5 key를 통과시킨다. "
        "`app.schemas.study.ClientEventRequest`를 상속하라"
    )
