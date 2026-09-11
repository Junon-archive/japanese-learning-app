"""session cookie 헤더 문자열 (ADR-004). DB 불필요.

`Max-Age`를 리터럴로 고정하면 TTL 설정을 무시하는 구현이 통과한다(M8). 기대값은
항상 인자로 준 ttl에서 유도한다.
"""

from __future__ import annotations

import pytest
from fastapi import Response

from app.api.auth import _set_session_cookie
from app.services.auth import SESSION_COOKIE_NAME
from app.settings import Settings

# 초/일은 단위 환산이지 설정값이 아니므로 테스트가 직접 들고 있는다. 구현에서
# import해 오면 환산 자체가 틀려도 양쪽이 같이 틀린 채 통과한다.
SECONDS_PER_DAY = 24 * 60 * 60

TTL_DAYS_CASES = (1, 3, 11, 30)


@pytest.mark.parametrize("ttl_days", TTL_DAYS_CASES)
def test_set_session_cookie_header_is_exact(ttl_days: int) -> None:
    """속성 하나가 빠지면 브라우저 방어가 통째로 사라지므로 문자열 전체를 고정한다."""
    response = Response()

    _set_session_cookie(response, "TOKEN", ttl_days)

    assert response.headers["set-cookie"] == (
        f"{SESSION_COOKIE_NAME}=TOKEN; HttpOnly; Max-Age={ttl_days * SECONDS_PER_DAY}; "
        "Path=/; SameSite=strict; Secure"
    )


def test_the_parametrized_ttls_include_a_non_default_value() -> None:
    """전부 기본값과 같으면 "ttl 인자를 쓰는가"를 구분하지 못한다."""
    default = Settings.model_fields["auth_session_ttl_days"].default
    assert set(TTL_DAYS_CASES) - {default}


def test_the_cookie_name_carries_the_host_prefix() -> None:
    """`__Host-` prefix는 Secure / Path=/ / Domain 미지정을 브라우저가 강제하게 한다.

    이름을 바꾸면 형제 subdomain이 같은 이름의 cookie를 덮어쓸 수 있게 된다.
    """
    # 이름 자체가 ADR-004의 결정이다. 바꾸면 기존 세션이 전부 끊긴다.
    assert SESSION_COOKIE_NAME == "__Host-nc_session"


def test_set_session_cookie_does_not_pin_a_domain() -> None:
    response = Response()

    _set_session_cookie(response, "TOKEN", 1)

    assert "Domain=" not in response.headers["set-cookie"]
