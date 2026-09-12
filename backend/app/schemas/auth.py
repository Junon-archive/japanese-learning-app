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
    # 평문 password가 422 본문에 실려 나가는 것은 **여기서 막히지 않는다.** 막는 것은
    # `app/main.py`의 `_validation_error_handler`이고, 그것이 오류에서 `input`(제출된
    # 값 그 자체)을 지운다. 상한을 없앤 것으로 닫힌 것은 `string_too_long` 하나뿐이고,
    # `missing`(client가 `loginId`처럼 이름을 틀린 경우)과 `model_attributes_type`
    # (body가 배열로 감싸인 경우)은 그대로 body 전체를 반향하고 있었다. 스키마 쪽에서
    # 유출을 막을 수 있다고 여기지 마라 --- 반향을 지우는 곳은 handler 한 곳이다.
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
