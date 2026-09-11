"""라우트 전수 인증 검사 (05_API_SPEC.md `익명 접근 허용 목록`, 04_SECURITY_AND_DATA.md).

`app.api.router`의 `ANONYMOUS_ROUTES` / `assert_fail_closed`를 **import하지 않는다.**
구현이 들고 있는 목록을 기준으로 삼으면 "목록을 늘리는 변경"과 "검사를 지우는
변경"이 스스로를 승인한다. 허용 목록은 이 파일이 명세에서 직접 옮겨 적는다.

두 층으로 본다.

-   구조 검사(DB 불필요): FastAPI가 실제로 실행할 dependency 트리를 해석한다.
    dependency를 endpoint에 붙였든 router에 붙였든 app에 붙였든 결과가 같으므로
    배선 형태가 바뀌어도 "이 경로가 인증을 요구하는가"라는 사실만 본다.
-   동작 검사(integration): 실제 요청을 보내 401/403을 확인한다.

어느 쪽이 더 견고한가: 동작 검사다. 구조 검사는 "dependency가 걸려 있다"까지만
보증하므로 `get_current_user`가 예외를 삼키도록 바뀌면 통과한다. 반대로 동작
검사만 두면 라우트가 DB/설정 문제로 500을 낼 때 401이 아닌 이유가 흐려지고,
DB 없이는 돌릴 수 없어 `make test-unit`에서 사라진다. 그래서 둘 다 둔다.
구조 검사는 빠른 경보, 동작 검사는 최종 근거다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_trusted_origin
from app.main import create_app
from app.services.auth import hash_password
from app.settings import get_settings
from tests import factories

# 05_API_SPEC.md의 `익명 접근 허용 목록`. 늘리려면 명세를 먼저 고치고 여기를 고친다.
SPEC_ANONYMOUS_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("POST", "/api/auth/login"),
    }
)

# 05_API_SPEC.md: FastAPI 자동 문서 경로는 익명 허용 목록과 별개이며 APP_ENV로
# 제어한다. dependency 트리가 없어서 구조 검사로는 판정할 수 없는 경로는 이 넷뿐이다.
SPEC_UNVERIFIABLE_ROUTES = frozenset(
    {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)

# 04_SECURITY_AND_DATA.md: 상태를 바꾸는 요청만 Origin을 검증한다. GET/HEAD/OPTIONS에
# 요구하면 정상 탐색과 CORS preflight가 막힌다.
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ORIGIN = "https://app.test"
LOGIN_ID = "route.audit"
PASSWORD = "correct horse battery staple"


def _dependency_calls(dependant: Dependant) -> frozenset[Any]:
    """이 라우트가 실제로 실행할 dependency 함수 전부(중첩 포함)."""
    calls: set[Any] = set()
    stack = list(dependant.dependencies)
    while stack:
        sub = stack.pop()
        if sub.call is not None:
            calls.add(sub.call)
        stack.extend(sub.dependencies)
    return frozenset(calls)


def _route_security(app: FastAPI) -> dict[tuple[str, str], frozenset[Any]]:
    """(method, full path) -> 그 라우트가 실행할 dependency 집합.

    `iter_route_contexts`는 FastAPI가 라우팅에 쓰는 평탄화 함수다. prefix 결합과
    router/app 레벨 dependency 상속을 FastAPI 자신과 같은 규칙으로 해석하므로
    `include_router` 구조가 바뀌어도 결과가 흔들리지 않는다.
    """
    surface: dict[tuple[str, str], frozenset[Any]] = {}
    for context in iter_route_contexts(app.routes):
        dependant: Dependant | None = getattr(context, "dependant", None)
        if dependant is None:
            # `/docs`, `/openapi.json` 같은 FastAPI 자동 경로. APP_ENV가 통제한다.
            continue
        calls = _dependency_calls(dependant)
        path: str = getattr(context, "path", "") or ""
        methods: set[str] = getattr(context, "methods", None) or set()
        # 선언된 method를 하나도 빼지 않는다. HEAD/OPTIONS를 예외로 두면 그 method로
        # 선언된 endpoint가 검사망을 빠져나간다.
        for method in methods:
            surface[(method, path)] = calls
    return surface


# --------------------------------------------------------------------------
# 구조 검사 (DB 불필요)
# --------------------------------------------------------------------------


def test_the_route_surface_is_not_empty() -> None:
    """나머지 검사가 공집합 위에서 통과하지 않게 한다.

    라우트 열거가 조용히 0건이 되면(평탄화 방식이 바뀌는 등) 아래 두 테스트는
    아무것도 감시하지 않으면서 초록이 된다.
    """
    surface = _route_security(create_app())

    assert set(surface) >= set(SPEC_ANONYMOUS_ROUTES), (
        f"명세의 익명 경로가 라우팅 표면에 없다. 열거된 것: {sorted(surface)}"
    )
    assert len(surface) > len(SPEC_ANONYMOUS_ROUTES), (
        "인증이 필요한 라우트가 하나도 열거되지 않았다"
    )


def test_no_route_escapes_the_structural_audit() -> None:
    """열거되지 않는 라우트가 있으면 두 층의 검사가 **동시에** 눈을 감는다.

    `_route_security()`는 dependency 트리가 있는 라우트만 본다. `app.mount()`가
    만드는 sub-app이나 WebSocket 라우트는 여기서 조용히 빠지므로, 빠졌다는 사실
    자체를 검사한다. 명세가 허용하는 예외는 APP_ENV가 통제하는 문서 경로뿐이다.
    """
    app = create_app()
    audited = {path for _, path in _route_security(app)}

    for context in iter_route_contexts(app.routes):
        path: str = getattr(context, "path", "") or ""
        if path in SPEC_UNVERIFIABLE_ROUTES:
            continue
        assert path in audited, (
            f"{type(context.original_route).__name__} {path} is reachable but the "
            "authentication audit cannot see it"
        )


def test_mounting_a_sub_application_fails_the_boot() -> None:
    """M7 회귀: mount는 인증도 Origin 검증도 상속하지 않는다. 부팅이 막혀야 한다.

    Wave 4에서 정적 파일을 `app.mount()`로 붙이려는 순간 여기서 빨개진다. 승인
    절차는 `app.api.router.APPROVED_UNVERIFIABLE_ROUTES`이고 명세를 먼저 고친다.
    """
    app = create_app()
    leaky = FastAPI()

    @leaky.get("/leak")
    def leak() -> dict[str, str]:  # pragma: no cover - 부팅이 막히므로 호출되지 않는다
        return {"secret": "user data via sub-app"}

    app.mount("/sub", leaky)

    with pytest.raises(RuntimeError) as caught, TestClient(app):
        pass  # pragma: no cover - 위 컨텍스트 진입이 실패한다

    assert "/sub" in str(caught.value)


def test_a_websocket_route_fails_the_boot() -> None:
    """WebSocket 라우트는 HTTP method가 없어 method별 인증 판정이 성립하지 않는다.

    `require_trusted_origin(request: Request)`이 WebSocket scope에서 죽는 것에
    기대면 안 된다. 그건 보증이 아니라 사고다. 검사 단계에서 막는다.
    """
    app = create_app()

    @app.websocket("/ws")
    async def socket(  # pragma: no cover - 부팅이 막히므로 호출되지 않는다
        websocket: WebSocket,
    ) -> None:
        await websocket.accept()

    with pytest.raises(RuntimeError) as caught, TestClient(app):
        pass  # pragma: no cover - 위 컨텍스트 진입이 실패한다

    assert "/ws" in str(caught.value)


def test_exactly_the_spec_allowlist_is_anonymous() -> None:
    """05_API_SPEC.md. 무인증 경로가 하나라도 늘면 여기서 깨진다."""
    surface = _route_security(create_app())

    anonymous = {route for route, calls in surface.items() if get_current_user not in calls}
    assert anonymous == set(SPEC_ANONYMOUS_ROUTES)


def test_every_state_changing_route_validates_the_origin() -> None:
    """04_SECURITY_AND_DATA.md. CORSMiddleware는 CSRF 방어가 아니다."""
    surface = _route_security(create_app())

    state_changing = {route for route in surface if route[0] in STATE_CHANGING_METHODS}
    assert state_changing, "상태 변경 라우트가 하나도 없다 (테스트 전제가 깨졌다)"

    unprotected = {
        route for route in state_changing if require_trusted_origin not in surface[route]
    }
    assert unprotected == set()


def test_authenticated_routes_do_not_reach_the_handler_without_a_session() -> None:
    """인증 dependency는 handler보다 먼저 돈다.

    `get_current_user`가 handler 파라미터로만 선언되어 있어도 FastAPI는 handler
    실행 전에 해석하므로 401이 먼저 나간다. 그 전제를 dependency 트리에서 확인한다.
    """
    surface = _route_security(create_app())

    protected = {route for route, calls in surface.items() if get_current_user in calls}
    assert protected, "인증이 걸린 라우트가 하나도 없다"
    for route in protected:
        # get_current_user는 DB 세션 없이는 세션을 해석할 수 없다. 둘이 함께
        # 걸려 있지 않으면 인증이 형태만 남은 것이다.
        assert get_db in surface[route], route


# --------------------------------------------------------------------------
# 동작 검사 (실제 요청)
# --------------------------------------------------------------------------


@pytest.fixture
def anonymous_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """cookie를 한 번도 싣지 않는 client. https base_url이어야 Secure cookie가 오간다."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, base_url="https://testserver") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _concrete(path: str) -> str:
    """path 파라미터를 실제 요청에 쓸 수 있는 값으로 바꾼다.

    인증은 path 파라미터 검증보다 먼저 돌므로 값 자체는 무엇이든 상관없다. 치환을
    하지 않으면 Wave 2에서 `/api/sessions/{session_id}` 같은 경로가 404가 되어
    "인증을 요구하는가"가 아니라 "경로가 매치되는가"를 재는 테스트가 된다.
    """
    return re.sub(r"\{[^}]+\}", "1", path)


def _send(
    client: TestClient,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    # 상태 변경 method에는 body가 필요할 수 있다. 인증/Origin 검사는 body보다 먼저
    # 돌기 때문에 내용은 무엇이든 상관없다.
    payload: dict[str, object] | None = {} if method in STATE_CHANGING_METHODS else None
    return client.request(method, _concrete(path), headers=headers, json=payload)


@pytest.mark.integration
def test_no_route_outside_the_allowlist_answers_an_anonymous_request(
    anonymous_client: TestClient,
) -> None:
    """M7 회귀: 사용자 데이터를 돌려주는 무인증 endpoint가 추가되면 여기서 빨개진다."""
    surface = _route_security(anonymous_client.app)  # type: ignore[arg-type]
    checked = 0
    for method, path in sorted(surface):
        if (method, path) in SPEC_ANONYMOUS_ROUTES:
            continue
        response = _send(anonymous_client, method, path, headers={"Origin": ORIGIN})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        # 브라우저 기본 인증 팝업을 띄우지 않는다.
        assert "www-authenticate" not in response.headers, f"{method} {path}"
        checked += 1
    assert checked, "인증을 요구하는 라우트가 하나도 검사되지 않았다"


@pytest.mark.integration
def test_state_changing_routes_reject_a_missing_origin(anonymous_client: TestClient) -> None:
    surface = _route_security(anonymous_client.app)  # type: ignore[arg-type]
    checked = 0
    for method, path in sorted(surface):
        if method not in STATE_CHANGING_METHODS:
            continue
        response = _send(anonymous_client, method, path)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
        checked += 1
    assert checked, "상태 변경 라우트가 하나도 검사되지 않았다"


@pytest.mark.integration
def test_health_answers_without_a_session(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/health").status_code == 200


@pytest.mark.integration
def test_login_answers_without_a_session(anonymous_client: TestClient, db_session: Session) -> None:
    """익명 허용 목록이 형태만 남지 않았는지 본다. login이 인증을 요구하면 로그인할 수 없다."""
    user = factories.make_user(db_session, login_id=LOGIN_ID)
    user.password_hash = hash_password(PASSWORD)
    db_session.flush()

    response = anonymous_client.post(
        "/api/auth/login",
        json={"login_id": LOGIN_ID, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 200
