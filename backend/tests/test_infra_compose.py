from __future__ import annotations

import re
from typing import Any

import yaml

from app.settings import Settings

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


# --------------------------------------------------------------------------
# .env.example <-> compose 전달 누락
#
# `AUTH_SESSION_TTL_DAYS`가 compose에 없어서 운영자가 값을 바꿔도 컨테이너가
# 기본값으로 조용히 돌던 구멍을 다시 열지 못하게 한다.
# --------------------------------------------------------------------------

ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"

APP_SERVICES = ("backend", "worker")

# Settings의 각 필드에 대응하는 환경변수 이름.
APP_ENV_KEYS = frozenset(name.upper() for name in Settings.model_fields)


def _env_example_keys() -> set[str]:
    keys = set()
    for line in ENV_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0])
    return keys


def test_env_example_documents_every_settings_field() -> None:
    assert _env_example_keys() >= APP_ENV_KEYS


def test_app_services_receive_every_setting_the_app_reads() -> None:
    """앱이 읽는 변수는 전부 컨테이너까지 전달되어야 한다.

    빠지면 운영자가 .env를 고쳐도 컨테이너는 코드 기본값으로 돈다(경고도 없다).
    """
    services = _compose()["services"]
    for name in APP_SERVICES:
        environment = services[name].get("environment", {})
        missing = APP_ENV_KEYS - set(environment)
        assert not missing, (name, sorted(missing))
        for key in APP_ENV_KEYS:
            # 이름이 어긋나면 다른 변수의 값이 들어간다.
            assert environment[key] == f"${{{key}}}", (name, key, environment[key])


def test_app_services_do_not_receive_compose_only_secrets() -> None:
    """POSTGRES_* 는 postgres 컨테이너만 쓴다. 앱 컨테이너에 DB superuser
    password를 넣으면 앱 프로세스 환경에서 그대로 읽힌다."""
    services = _compose()["services"]
    for name in APP_SERVICES:
        leaked = [
            key for key in services[name].get("environment", {}) if key.startswith("POSTGRES")
        ]
        assert leaked == [], (name, leaked)
