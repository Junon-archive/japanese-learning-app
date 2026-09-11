from __future__ import annotations

import re
from typing import Any

import yaml

from .conftest import REPO_ROOT

COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"
DOCKERIGNORE_FILE = REPO_ROOT / ".dockerignore"
DOCKERFILES = (
    REPO_ROOT / "infra" / "Dockerfile.backend",
    REPO_ROOT / "infra" / "Dockerfile.worker",
)


def _compose() -> dict[str, Any]:
    loaded: Any = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_compose_defines_the_three_services() -> None:
    assert set(_compose()["services"]) == {"postgres", "backend", "worker"}


def test_postgres_image_is_pinned_to_16() -> None:
    assert _compose()["services"]["postgres"]["image"] == "postgres:16"


def test_every_published_port_is_bound_to_loopback() -> None:
    published = [
        port for service in _compose()["services"].values() for port in service.get("ports", [])
    ]
    assert published
    for port in published:
        assert port.startswith("127.0.0.1:"), port


def test_compose_has_no_plaintext_secret() -> None:
    for service in _compose()["services"].values():
        for name, value in service.get("environment", {}).items():
            if "PASSWORD" in name or "SECRET" in name or name == "DATABASE_URL":
                assert re.fullmatch(r"\$\{[A-Z_]+\}", str(value)), (name, value)


def test_postgres_volume_points_at_repo_data_dir() -> None:
    assert _compose()["services"]["postgres"]["volumes"] == [
        "../data/postgres:/var/lib/postgresql/data"
    ]


def test_dockerignore_excludes_secrets_and_data() -> None:
    # build context가 repo 루트이므로 .env와 DB/backup 파일이 image layer와
    # build cache에 들어가면 안 된다 (spec/04_SECURITY_AND_DATA.md).
    assert DOCKERIGNORE_FILE.is_file()
    patterns = {
        line.strip()
        for line in DOCKERIGNORE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for required in (
        ".env",
        ".env.*",
        "data/",
        ".git",
        ".venv",
        "**/node_modules",
        "backend/tests",
    ):
        assert required in patterns, required


def test_images_run_as_a_non_root_user() -> None:
    for dockerfile in DOCKERFILES:
        lines = [line.strip() for line in dockerfile.read_text(encoding="utf-8").splitlines()]
        user_lines = [line for line in lines if line.startswith("USER ")]
        assert user_lines, dockerfile.name
        assert user_lines[-1] != "USER root", dockerfile.name


def test_build_images_are_pinned() -> None:
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")
        assert ":latest" not in text, dockerfile.name


def test_application_source_is_not_owned_by_the_runtime_user() -> None:
    # 앱 소스와 정책 설정은 root 소유로 두고 런타임 사용자는 읽기만 한다.
    # 쓰기 가능하면 파일쓰기 취약점이 재빌드 전까지 살아남는 백도어가 된다.
    for dockerfile in DOCKERFILES:
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("COPY "):
                assert "--chown=appuser" not in stripped, (dockerfile.name, stripped)
