"""API 라우팅 조립 + fail-closed 인증 배선 (05_API_SPEC.md의 `익명 접근 허용 목록`).

여기가 **유일한** 조립 지점이다. 새 endpoint는 `api_router`에 올린다. 그러면
아무것도 하지 않아도 인증(`get_current_user`)과 Origin 검증(`require_trusted_origin`,
app 레벨)을 상속한다.

    # app/api/study.py
    router = APIRouter(prefix="/api/sessions", tags=["study"])
    # app/api/router.py
    api_router.include_router(study.router)

익명 접근은 `ANONYMOUS_ROUTES`에 적힌 둘뿐이고, 그 둘만 `anonymous_router`에 올린다.
목록에 없는 경로가 인증 없이 도달 가능하면 `assert_fail_closed()`가 **앱 부팅을
실패시킨다**. router에 dependency 붙이는 것을 "잊는" 경로를 남기지 않기 위해서다
(dependency를 빠뜨린 router를 `app.include_router()`로 직접 붙여도 부팅이 실패한다).

검사가 **해석할 수 있는 라우트는 `APIRoute`뿐이다.** `app.mount()`가 만드는
Starlette `Mount`와 WebSocket 라우트는 FastAPI dependency 스택 밖이거나 HTTP
method가 없어서 "인증을 요구하는가"를 판정할 수 없다. 그래서 이 검사는 모르는
라우트를 안전하다고 보지 않고 **거부한다**: `APPROVED_UNVERIFIABLE_ROUTES`에
명시적으로 적히지 않은 비-`APIRoute`가 앱에 붙어 있으면 부팅이 실패한다.

미들웨어로 걸지 않는 이유: 미들웨어는 경로 문자열로 예외를 처리해야 하고
(`/api/health`, CORS preflight), 라우팅 결과를 모르기 때문에 오타 난 경로가
조용히 인증을 우회한다. dependency는 라우트에 붙으므로 전수 검사가 가능하다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.api import auth, health, history, study
from app.api.deps import get_current_user, require_trusted_origin

# 05_API_SPEC.md의 `익명 접근 허용 목록`. 이 집합을 늘리려면 명세를 먼저 고친다.
ANONYMOUS_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("POST", "/api/auth/login"),
    }
)

# dependency 트리로 인증을 판정할 수 **없는데** 존재가 승인된 라우트의 경로.
# 여기 없는 비-`APIRoute`는 부팅을 실패시킨다. 기본값은 거부다.
#
# 지금 들어 있는 넷은 FastAPI가 스스로 다는 자동 문서 경로다. dependency 트리가
# 없는 Starlette `Route`이고, `APP_ENV`로 통제된다(05_API_SPEC.md: "FastAPI 자동
# 문서 경로는 이 목록과 별개이며 APP_ENV로 제어한다"). production에서는 아예
# 생성되지 않으므로 여기 적혀 있어도 존재하지 않는다.
#
# 여기에 경로를 추가한다는 것은 **그 경로 아래 전부가 익명·무검증 표면임을
# 받아들인다**는 뜻이다(mount된 sub-app은 app 레벨 dependency도, Origin 검증도
# 상속하지 않는다). 05_API_SPEC.md의 익명 접근 절을 먼저 고친다.
APPROVED_UNVERIFIABLE_ROUTES: frozenset[str] = frozenset(
    {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)

# 앱 전체(`FastAPI(dependencies=...)`)에 거는 dependency. GET/OPTIONS에서는 아무 일도
# 하지 않으므로 익명 경로에 붙어도 `GET /api/health`와 CORS preflight를 막지 않는다.
ROOT_DEPENDENCIES = [Depends(require_trusted_origin)]

# 익명 허용 목록에 있는 endpoint만 여기에 올린다.
anonymous_router = APIRouter()
anonymous_router.include_router(health.router)
anonymous_router.include_router(auth.anonymous_router)

# 그 밖의 **모든** endpoint는 여기에 올린다. 인증은 구조적으로 상속된다.
api_router = APIRouter(dependencies=[Depends(get_current_user)])
api_router.include_router(auth.router)
api_router.include_router(history.router)
api_router.include_router(study.router)


class FailClosedError(RuntimeError):
    """라우팅 표면이 명세의 fail-closed 규칙을 어겼다. 앱을 띄우면 안 된다."""


@dataclass(frozen=True)
class RouteSecurity:
    """라우트 하나(method 하나)의 실제 보안 배선."""

    method: str
    path: str
    requires_authentication: bool
    requires_trusted_origin: bool

    @property
    def is_anonymous_by_spec(self) -> bool:
        return (self.method, self.path) in ANONYMOUS_ROUTES


@dataclass(frozen=True)
class UnverifiableRoute:
    """보안 배선을 판정할 수 없는 라우트. 승인되지 않으면 부팅을 막는다."""

    kind: str
    path: str
    reason: str


def _unverifiable_reason(context: RouteContext) -> str | None:
    """이 라우트를 `RouteSecurity`로 해석할 수 없는 이유. 해석 가능하면 None.

    `APIRoute`만 FastAPI dependency 트리를 갖는다. `Mount`(sub-app, 정적 파일)는
    dependency 스택 밖에서 요청을 처리하고, WebSocket 라우트는 HTTP method가 없어
    method별 판정이 성립하지 않는다. 둘 다 "인증을 요구하는가"에 답할 수 없다.
    """
    route = context.original_route
    if not isinstance(route, APIRoute):
        return (
            f"{type(route).__name__} is outside the FastAPI dependency tree, "
            "so its authentication cannot be determined"
        )
    if not context.methods:
        return "route declares no HTTP method"
    if getattr(context, "dependant", None) is None:
        return "route has no resolved dependant"
    return None


def iter_unverifiable_routes(app: FastAPI) -> Iterator[UnverifiableRoute]:
    """`iter_route_security()`가 해석하지 못하는 라우트를 전부 훑는다.

    `iter_route_security()`가 조용히 건너뛰는 것들이다. 검사에서 빠졌다는 사실
    자체를 `assert_fail_closed()`가 볼 수 있어야 "모르면 실패"가 성립한다.
    """
    for context in iter_route_contexts(app.routes):
        reason = _unverifiable_reason(context)
        if reason is None:
            continue
        yield UnverifiableRoute(
            kind=type(context.original_route).__name__,
            path=context.path or "",
            reason=reason,
        )


def _dependency_calls(dependant: Dependant) -> set[Any]:
    """이 라우트가 실제로 실행하는 dependency 함수 전부(중첩 포함)."""
    calls: set[Any] = set()
    stack = list(dependant.dependencies)
    while stack:
        sub = stack.pop()
        if sub.call is not None:
            calls.add(sub.call)
        stack.extend(sub.dependencies)
    return calls


def iter_route_security(app: FastAPI) -> Iterator[RouteSecurity]:
    """앱에 등록된 모든 `APIRoute`의 보안 배선을 (method, path)별로 훑는다.

    해석할 수 없는 라우트(`/docs` 같은 Starlette `Route`, `Mount`, WebSocket)는
    여기서 빠진다. 그것들은 `iter_unverifiable_routes()`가 따로 보고하고,
    `assert_fail_closed()`가 승인 여부를 판정한다.
    """
    for context in iter_route_contexts(app.routes):
        if _unverifiable_reason(context) is not None:
            continue
        dependant: Dependant = context.dependant
        calls = _dependency_calls(dependant)
        path = context.path or ""
        # 선언된 method를 하나도 빼지 않는다. HEAD/OPTIONS를 예외로 두면
        # 그 method로 선언된 endpoint가 검사망을 빠져나간다.
        for method in sorted(context.methods or set()):
            yield RouteSecurity(
                method=method,
                path=path,
                requires_authentication=get_current_user in calls,
                requires_trusted_origin=require_trusted_origin in calls,
            )


def assert_fail_closed(app: FastAPI) -> None:
    """라우트 전수 검사. 위반이 하나라도 있으면 `FailClosedError`로 부팅을 막는다."""
    for unverifiable in iter_unverifiable_routes(app):
        if unverifiable.path in APPROVED_UNVERIFIABLE_ROUTES:
            continue
        raise FailClosedError(
            f"{unverifiable.kind} {unverifiable.path} cannot be audited: "
            f"{unverifiable.reason}. Serve it as an APIRoute on "
            "app.api.router.api_router, or — if it really must live outside the "
            "dependency tree — add its path to "
            "app.api.router.APPROVED_UNVERIFIABLE_ROUTES after amending "
            "05_API_SPEC.md, accepting that everything under it is anonymous."
        )

    seen_anonymous: set[tuple[str, str]] = set()
    for route in iter_route_security(app):
        where = f"{route.method} {route.path}"
        if not route.requires_trusted_origin:
            raise FailClosedError(
                f"{where} is not covered by require_trusted_origin; "
                "every route must inherit app.api.router.ROOT_DEPENDENCIES"
            )
        if route.is_anonymous_by_spec:
            seen_anonymous.add((route.method, route.path))
            if route.requires_authentication:
                raise FailClosedError(
                    f"{where} is on the anonymous allowlist but requires authentication"
                )
            continue
        if not route.requires_authentication:
            raise FailClosedError(
                f"{where} is reachable without authentication. Mount it on "
                "app.api.router.api_router, or add it to ANONYMOUS_ROUTES after "
                "amending 05_API_SPEC.md."
            )

    missing = ANONYMOUS_ROUTES - seen_anonymous
    if missing:
        raise FailClosedError(
            f"anonymous allowlist names routes that do not exist: {sorted(missing)}"
        )


def install_routes(app: FastAPI) -> None:
    app.include_router(anonymous_router)
    app.include_router(api_router)
    assert_fail_closed(app)
