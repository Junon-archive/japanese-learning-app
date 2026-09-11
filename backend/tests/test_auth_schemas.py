"""`LoginRequest`의 입력 제약.

login_id에만 상한이 있다. password에는 상한이 없다 --- spec/04_SECURITY_AND_DATA.md
의 `Password 요구사항 (MVP 확정)`이 "최대 길이를 정하지 않는다"로 확정했다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import LOGIN_ID_MAX_LENGTH, LoginRequest


def test_password_has_no_upper_bound() -> None:
    """상한을 다시 넣으면 여기서 걸린다.

    상한은 Argon2id 비용을 줄여주지 않고, 계정 생성 경로(scripts/create_user.py)에는
    상한이 없어서 "생성은 되는데 로그인은 422"인 password를 만들어낸다.
    """
    password = "a" * 5000

    assert LoginRequest(login_id="junon", password=password).password == password


def test_oversized_login_id_is_rejected() -> None:
    """users.login_id CHECK가 3~64자다. 더 긴 값은 어차피 아무와도 일치하지 않는다."""
    with pytest.raises(ValidationError):
        LoginRequest(login_id="a" * (LOGIN_ID_MAX_LENGTH + 1), password="pw")
