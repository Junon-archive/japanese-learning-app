"""cloudflared 예시 설정 (ADR-020 결정 4).

예시는 사용자가 기존 터널 설정의 catch-all 앞에 규칙 하나로 옮겨 적는 조각이다. 여기서는
그 조각이 API만 IPv4 loopback으로 노출하고 catch-all로 끝나는지를 본다.

실제 도메인이 없다는 것은 여기서 보지 않는다. 테스트에 도메인을 적는 순간 그 자체가
노출이다. 대신 자리표시자가 있는지를 본다.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import yaml

from .conftest import REPO_ROOT

EXAMPLE_CONFIG = REPO_ROOT / "infra" / "cloudflared" / "config.example.yml"

API_SERVICE = "http://127.0.0.1:8000"
CATCH_ALL_SERVICE = "http_status:404"

_GIT_TIMEOUT_SECONDS = 60


def _example() -> dict[str, Any]:
    loaded: Any = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_ingress_is_one_api_rule_followed_by_the_catch_all() -> None:
    ingress = _example()["ingress"]
    assert ingress == [
        {"hostname": "<API_HOST>", "service": API_SERVICE},
        {"service": CATCH_ALL_SERVICE},
    ]


def test_example_exposes_nothing_but_the_api_over_ipv4_loopback() -> None:
    # 주석까지 포함한 전체 텍스트를 본다. 주석에 적힌 예도 옮겨 적힐 수 있다.
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    for needle in ("tcp://", "ssh://", "5432", "localhost"):
        assert needle not in text, needle


def test_example_uses_placeholders() -> None:
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    assert "<API_HOST>" in text


def _check_ignore(path: str) -> int:
    git = shutil.which("git")
    assert git is not None, "git이 PATH에 없다. 이 검사는 git 없이 통과할 수 없다"
    completed = subprocess.run(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
        [git, "-C", str(REPO_ROOT), "check-ignore", "--quiet", "--no-index", path],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    # 0 = 무시됨, 1 = 무시되지 않음, 그 밖은 git 오류다.
    assert completed.returncode in (0, 1), completed.stderr
    return completed.returncode


def test_real_cloudflared_config_and_credentials_are_ignored() -> None:
    for path in (
        "infra/cloudflared/config.yml",
        "infra/cloudflared/0123abcd.json",
        "infra/cloudflared/cert.pem",
    ):
        assert _check_ignore(path) == 0, path


def test_the_example_config_is_not_ignored() -> None:
    assert EXAMPLE_CONFIG.is_file()
    assert _check_ignore("infra/cloudflared/config.example.yml") == 1
