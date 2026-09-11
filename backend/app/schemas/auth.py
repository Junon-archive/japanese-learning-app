"""Auth endpoint 스키마 (05_API_SPEC.md의 Authentication)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import StartingLevel

# `users.login_id`의 CHECK 제약이 3~64자다 (0001_initial_schema). 더 긴 입력은
# 어차피 어떤 사용자와도 일치할 수 없다.
LOGIN_ID_MAX_LENGTH = 64


class LoginRequest(BaseModel):
    login_id: str = Field(max_length=LOGIN_ID_MAX_LENGTH)
    # password에는 **상한을 두지 않는다.** spec/04_SECURITY_AND_DATA.md의
    # `Password 요구사항 (MVP 확정)`이 "최대 길이를 정하지 않는다"로 확정했다.
    # Argon2id 비용은 memory/time 파라미터가 지배하고 입력 길이에 거의 비례하지
    # 않으므로 상한이 막아주는 것이 없다. 반대로 상한을 두면 계정 생성 경로
    # (scripts/create_user.py, 상한 없음)와 어긋나서 "만들 수는 있는데 로그인은
    # 422로 영구 차단되는" password가 생긴다.
    #
    # 그리고 pydantic `max_length`는 **제출된 평문 password를 응답 본문에 반향한다.**
    # 상한이 있던 시절 실측: 초과 입력에 FastAPI가
    # `{"type":"string_too_long", ..., "input":"<평문 password>"}`를 422로 돌려줬다.
    # 그 본문은 프록시/터널 로그와 브라우저 HAR에 그대로 남는다. 상한을 다시 넣으면
    # 이 유출 경로도 함께 돌아온다. 다시 넣지 않는다.
    password: str


class UserResponse(BaseModel):
    """`GET /api/auth/me`의 응답.

    password_hash와 session token 관련 필드는 절대 포함하지 않는다.
    id는 DB 정수 PK를 JSON number로 그대로 낸다 (ADR-005).
    """

    user_id: int
    login_id: str
    timezone: str
    starting_level: StartingLevel
