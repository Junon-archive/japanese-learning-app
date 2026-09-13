from __future__ import annotations

import re
import tomllib
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


def test_postgres_cluster_lives_below_the_bind_root() -> None:
    """PGDATA는 bind 루트의 하위 디렉터리여야 한다.

    `data/postgres/`에는 저장소가 추적하는 `.gitkeep`이 있다. PGDATA가 bind 루트
    자체면 initdb가 "exists but is not empty"로 거부해 컨테이너가 무한 재시작한다.
    게다가 entrypoint가 실패 전에 bind 루트와 `.gitkeep`을 999:700으로 바꿔서
    호스트 사용자가 `ls`/`git status`도 못 하고 복구에 root가 필요해진다.
    하위 디렉터리를 주면 initdb는 빈 `pgdata/`에만 쓰고 bind 루트는 건드리지 않는다.
    """
    postgres = _compose()["services"]["postgres"]
    assert postgres["environment"].get("PGDATA") == "/var/lib/postgresql/data/pgdata"


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


# --------------------------------------------------------------------------
# provider 자격증명의 경계 (spec/04_SECURITY_AND_DATA.md)
#
# `Settings`에 없는 변수라서 위의 두 검사가 보지 못한다. 여기서 따로 못박는다.
# --------------------------------------------------------------------------

WORKER_ONLY_ENV_KEYS = ("LLM_PROVIDER", "LLM_API_KEY")


def test_only_the_worker_receives_the_provider_credentials() -> None:
    """API 컨테이너에 키를 넣으면 그 프로세스 환경에서 그대로 읽힌다.

    FastAPI는 provider client를 만들지 않으므로(불변식 #1) 키가 필요 없고, 주지 않는
    것이 그 경계를 배포 수준에서 한 번 더 강제한다.
    """
    services = _compose()["services"]
    worker_env = services["worker"]["environment"]
    for key in WORKER_ONLY_ENV_KEYS:
        assert worker_env[key] == f"${{{key}}}", (key, worker_env.get(key))
        assert key not in services["backend"]["environment"], key


def test_the_worker_still_receives_every_app_setting() -> None:
    """`<<: *app-env` 병합이 깨지면 worker가 DATABASE_URL 없이 뜬다."""
    worker_env = _compose()["services"]["worker"]["environment"]
    assert set(worker_env) >= APP_ENV_KEYS


def test_the_worker_image_starts_the_real_entrypoint() -> None:
    text = (REPO_ROOT / "infra" / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "scripts/run_worker.py" in text
    assert "not implemented" not in text
    # 진입점이 backend/ 밖에 있으므로 이미지에 함께 들어가야 한다.
    assert "COPY scripts ./scripts" in text


# --------------------------------------------------------------------------
# 학습 정책 override 파일 mount (ADR-020 결정 3)
#
# default.yaml의 두 한도가 null이라 mount가 빠지거나 한쪽 서비스에만 있으면 그 컨테이너는
# 한도가 꺼진 채 조용히 돈다. 두 한도가 여전히 null인지는 test_config.py의
# `test_null_llm_limits_load_as_none`이 지킨다.
# --------------------------------------------------------------------------


def _policy_mounts(service: str) -> list[dict[str, Any]]:
    volumes = _compose()["services"][service].get("volumes", [])
    return [
        volume
        for volume in volumes
        if isinstance(volume, dict) and "NC_CONFIG_PATH" in str(volume.get("source"))
    ]


def test_backend_and_worker_mount_the_same_policy_file_read_only() -> None:
    mounts = {name: _policy_mounts(name) for name in APP_SERVICES}
    for name, found in mounts.items():
        assert len(found) == 1, (name, found)
        mount = found[0]
        assert mount["type"] == "bind", name
        assert mount["read_only"] is True, name
        # 호스트와 컨테이너가 같은 절대경로여야 NC_CONFIG_PATH와 mount가 어긋나지 않는다.
        assert mount["source"] == mount["target"], name
    assert mounts["backend"] == mounts["worker"]


def test_policy_mount_does_not_create_a_missing_host_path() -> None:
    """파일이 없을 때 docker가 그 경로에 디렉터리를 만들면 안 된다."""
    for name in APP_SERVICES:
        (mount,) = _policy_mounts(name)
        assert mount["bind"]["create_host_path"] is False, name


def test_policy_mount_path_is_required() -> None:
    """값이 없거나 비어 있으면 compose가 아무것도 띄우지 않아야 한다(`:?`)."""
    for name in APP_SERVICES:
        (mount,) = _policy_mounts(name)
        assert mount["source"].startswith("${NC_CONFIG_PATH:?"), (name, mount["source"])
        assert mount["target"].startswith("${NC_CONFIG_PATH:?"), (name, mount["target"])


# --------------------------------------------------------------------------
# 후리가나 분석기의 이미지 배치 (ADR-021 결정 6, 불변식 15)
#
# `default-groups`에 furigana가 있으면 `--no-dev`로는 분석기가 빠지지 않는다. 두 Dockerfile의
# sync 명령과 group 위치를 함께 고정한다. 하나만 바뀌면 API 이미지에 사전 212M가 조용히 들어가거나
# worker가 분석기 없이 빌드된다(worker는 부팅에서 실패한다).
# --------------------------------------------------------------------------

PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
ANALYZER_PACKAGES = ("sudachipy", "sudachidict-core")


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))


def _uv_sync_lines(dockerfile_name: str) -> list[str]:
    text = (REPO_ROOT / "infra" / dockerfile_name).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if "uv sync" in line and "RUN" in line]


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9._-]+", requirement)
    assert match, requirement
    return match.group(0).lower().replace("_", "-")


def test_api_image_syncs_without_default_groups() -> None:
    assert _uv_sync_lines("Dockerfile.backend") == [
        "RUN uv sync --frozen --no-default-groups --no-build"
    ]


def test_worker_image_syncs_only_the_furigana_group() -> None:
    assert _uv_sync_lines("Dockerfile.worker") == [
        "RUN uv sync --frozen --no-default-groups --group furigana --no-build"
    ]


def test_analyzer_is_not_a_main_dependency() -> None:
    main = {_requirement_name(req) for req in _pyproject()["project"]["dependencies"]}
    for package in ANALYZER_PACKAGES:
        assert package not in main, package


def test_analyzer_lives_only_in_the_pinned_furigana_group() -> None:
    groups: dict[str, list[str]] = _pyproject()["dependency-groups"]
    assert sorted(groups["furigana"]) == ["sudachidict-core==20260723", "sudachipy==0.6.11"]
    for name, requirements in groups.items():
        if name == "furigana":
            continue
        names = {_requirement_name(req) for req in requirements if isinstance(req, str)}
        for package in ANALYZER_PACKAGES:
            assert package not in names, (name, package)


def test_host_default_groups_include_furigana() -> None:
    assert _pyproject()["tool"]["uv"]["default-groups"] == ["dev", "furigana"]
