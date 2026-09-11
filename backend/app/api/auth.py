"""Auth endpoint (05_API_SPEC.md의 Authentication).

인증과 Origin 검증은 이 모듈이 붙이지 않는다. `app.api.router`가 조립하면서
`api_router`의 router 레벨 dependency로 건다. endpoint마다 붙이면 하나를 빠뜨리는
순간 무인증 API가 생기기 때문이다.

-   `router`      : 인증이 필요한 endpoint (logout, me).
-   `anonymous_router`: 05_API_SPEC.md의 익명 허용 목록에 있는 login 하나뿐.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, UserResponse
from app.services.auth import (
    DUMMY_PASSWORD_HASH,
    SESSION_COOKIE_NAME,
    create_session,
    normalize_login_id,
    revoke_session,
    verify_password,
)
from app.settings import get_settings

_SECONDS_PER_DAY = 24 * 60 * 60

router = APIRouter(prefix="/api/auth", tags=["auth"])

# `POST /api/auth/login`은 호출 시점에 세션이 없다(05_API_SPEC.md의 익명 접근 허용
# 목록). 그래도 상태를 바꾸므로 app 레벨 `require_trusted_origin`은 그대로 받는다.
anonymous_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, ttl_days: int) -> None:
    """ADR-004. 이름과 속성은 설정값이 아니다. 환경별 스위치를 두지 않는다."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl_days * _SECONDS_PER_DAY,
        path="/",
        # Domain을 지정하지 않는다(host-only). 지정하면 형제 subdomain 전체로 나간다.
        secure=True,
        httponly=True,
        samesite="strict",
    )


@anonymous_router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    """실패 사유(없는 사용자 / 틀린 password / 비활성)를 구분하지 않는다."""
    login_id = normalize_login_id(payload.login_id)
    user = db.execute(select(User).where(User.login_id == login_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        # 사용자가 없어도 같은 비용을 치른다. 응답 시간이 user enumeration oracle이
        # 되지 않게 한다.
        verify_password(DUMMY_PASSWORD_HASH, payload.password)
        raise _invalid_credentials()
    if not verify_password(user.password_hash, payload.password):
        raise _invalid_credentials()

    ttl_days = get_settings().auth_session_ttl_days
    token = create_session(db, user_id=user.id, ttl_days=ttl_days)
    # cookie를 내주기 전에 세션 저장을 확정한다. commit이 실패하면 500이 나가고
    # cookie는 설정되지 않는다(저장 실패를 성공처럼 응답하지 않는다).
    db.commit()
    _set_session_cookie(response, token, ttl_days)
    return _to_user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: Annotated[Session, Depends(get_db)],
    session_token: Annotated[str, Cookie(alias=SESSION_COOKIE_NAME)],
) -> Response:
    """cookie가 없으면 api_router의 인증 dependency가 이미 401을 냈다."""
    revoke_session(db, session_token)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    # 설정할 때와 같은 속성으로 덮어써야 브라우저가 기존 cookie를 지운다.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="",
        max_age=0,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/me")
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _to_user_response(current_user)


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.id,
        login_id=user.login_id,
        timezone=user.timezone,
        starting_level=user.starting_level,
    )


def _invalid_credentials() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
