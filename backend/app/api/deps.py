"""FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import new_session
from app.models.user import User
from app.services.auth import SESSION_COOKIE_NAME, resolve_session
from app.settings import get_settings

# CORS preflight(OPTIONS)와 조회(GET/HEAD)는 상태를 바꾸지 않는다.
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_now() -> datetime:
    """이 요청이 보는 시각. 요청당 **한 번**만 읽힌다 (ADR-007).

    FastAPI는 같은 요청 안에서 같은 dependency 호출을 캐시하므로, handler와 그
    아래의 어떤 dependency가 `Depends(get_now)`를 몇 번 선언하든 값은 하나다.
    이후로는 `now: datetime` **값**으로만 전달한다.

    테스트는 `app.dependency_overrides[get_now]`로 시각을 옮긴다. freezegun이나
    `datetime` monkeypatch를 쓰지 않는다.
    """
    return utc_now()


def get_db() -> Iterator[Session]:
    """요청 하나당 세션 하나. commit은 호출부가 명시적으로 한다."""
    with new_session() as session:
        yield session


def require_trusted_origin(request: Request) -> None:
    """상태 변경 요청에 대한 strict Origin 검증 (spec/04_SECURITY_AND_DATA.md).

    CORSMiddleware는 CSRF 방어가 아니다. `Content-Type: text/plain` POST는 preflight
    없이 handler에 도달해 부수효과를 낸다. 서버가 직접 Origin을 확인해야 한다.

    Referer 폴백을 두지 않는다. Referer는 privacy 설정으로 지워질 수 있어서 폴백을
    두는 순간 "헤더가 없으면 통과"라는 우회로가 생긴다.
    """
    if request.method not in _STATE_CHANGING_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None or origin not in get_settings().cors_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    now: Annotated[datetime, Depends(get_now)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """유효한 auth session cookie가 없으면 401.

    cookie 없음 / 조회 실패 / 폐기됨 / 만료됨 / 비활성 사용자를 **구분하지 않는다.**
    구분하면 그 자체가 oracle이 된다. `WWW-Authenticate`도 붙이지 않는다. 붙이면
    브라우저가 기본 인증 팝업을 띄운다.
    """
    if session_token is None:
        raise _not_authenticated()
    user = resolve_session(db, session_token, now=now)
    if user is None:
        raise _not_authenticated()
    # last_used_at 갱신은 이 요청의 성패와 무관한 기록이므로 여기서 확정한다.
    db.commit()
    return user


def _not_authenticated() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
