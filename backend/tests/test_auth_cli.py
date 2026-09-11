"""scripts/create_user.py 테스트.

계정을 만드는 유일한 경로다(public signup 없음). 스크립트는 `backend/` 밖에 있어
평소 import 경로에 없으므로 파일 경로로 직접 적재한다.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.user import User
from app.services.auth import verify_password

CREATE_USER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "create_user.py"
PASSWORD = "correct horse battery staple"


def _load_create_user() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_user", CREATE_USER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """CLI가 테스트와 같은 커넥션을 쓰게 한다.

    CLI는 자기 session을 열고 닫으므로 fixture session을 그대로 넘기면 `with`를
    빠져나오며 테스트 session이 닫힌다. 커넥션만 공유한다.
    """
    module = _load_create_user()
    connection = db_session.connection()
    monkeypatch.setattr(
        module,
        "new_session",
        lambda: Session(bind=connection, join_transaction_mode="create_savepoint"),
    )
    return module


def _feed_password(monkeypatch: pytest.MonkeyPatch, password: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{password}\n"))


@pytest.mark.integration
def test_create_user_normalizes_and_hashes(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_password(monkeypatch, PASSWORD)

    exit_code = cli.main(["--login-id", "  JuNon  ", "--password-stdin"])

    assert exit_code == 0
    user = db_session.scalars(sa.select(User).where(User.login_id == "junon")).one()
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, PASSWORD) is True
    # 기본값은 스크립트 리터럴이 아니라 config에서 온다.
    assert user.timezone == get_config().user.user_timezone
    assert user.starting_level == "beginner"


@pytest.mark.integration
def test_create_user_rejects_a_duplicate_login_id(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_password(monkeypatch, PASSWORD)
    assert cli.main(["--login-id", "junon", "--password-stdin"]) == 0

    _feed_password(monkeypatch, PASSWORD)
    # upsert나 덮어쓰기를 하지 않는다. 명확히 실패한다.
    assert cli.main(["--login-id", "JUNON", "--password-stdin"]) == 2

    assert len(db_session.scalars(sa.select(User)).all()) == 1


@pytest.mark.integration
def test_create_user_rejects_an_empty_password(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_password(monkeypatch, "")

    assert cli.main(["--login-id", "junon", "--password-stdin"]) == 2
    assert db_session.scalars(sa.select(User)).all() == []


@pytest.mark.integration
def test_create_user_accepts_explicit_timezone_and_level(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_password(monkeypatch, PASSWORD)

    exit_code = cli.main(
        [
            "--login-id",
            "junon",
            "--timezone",
            "UTC",
            "--starting-level",
            "advanced",
            "--password-stdin",
        ]
    )

    assert exit_code == 0
    user = db_session.scalars(sa.select(User)).one()
    assert (user.timezone, user.starting_level) == ("UTC", "advanced")


def test_create_user_never_takes_a_password_argument() -> None:
    # argv는 ps, 셸 히스토리, 프로세스 어카운팅에 남는다.
    source = CREATE_USER_PATH.read_text(encoding="utf-8")
    assert '"--password"' not in source
    assert "getenv" not in source
    assert "environ" not in source


# --------------------------------------------------------------------------
# password 하한 (spec/04_SECURITY_AND_DATA.md `Password 요구사항`, ADR-006)
#
# 계정을 만드는 이 경로가 유일한 검증 지점이다. `POST /api/auth/login`은 이 정책을
# 검증하지 않는다 --- 그쪽에서 길이를 먼저 보면 실패 응답 시간이 갈린다.
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_create_user_rejects_a_password_below_the_minimum(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    too_short = "a" * (cli.PASSWORD_MIN_CODE_POINTS - 1)
    _feed_password(monkeypatch, too_short)

    assert cli.main(["--login-id", "junon", "--password-stdin"]) == 2
    assert db_session.scalars(sa.select(User)).all() == []


@pytest.mark.integration
def test_create_user_accepts_a_password_at_the_minimum(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    exactly_minimum = "a" * cli.PASSWORD_MIN_CODE_POINTS
    _feed_password(monkeypatch, exactly_minimum)

    assert cli.main(["--login-id", "junon", "--password-stdin"]) == 0
    user = db_session.scalars(sa.select(User)).one()
    assert verify_password(user.password_hash, exactly_minimum) is True


@pytest.mark.integration
def test_password_minimum_counts_code_points_not_bytes(
    cli: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """하한은 code point 기준이다. UTF-8 바이트로 세면 통과 기준이 달라진다."""
    astral = "🌱" * (cli.PASSWORD_MIN_CODE_POINTS - 1)  # code point 15개, 60 bytes
    _feed_password(monkeypatch, astral)

    assert cli.main(["--login-id", "junon", "--password-stdin"]) == 2
    assert db_session.scalars(sa.select(User)).all() == []
