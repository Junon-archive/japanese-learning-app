#!/usr/bin/env python
"""사용자 생성 CLI.

public signup이 없으므로 계정은 이 스크립트로만 만든다
(spec/04_SECURITY_AND_DATA.md의 Authentication).

    uv run python scripts/create_user.py --login-id junon
    printf '%s' "$PASSWORD" | uv run python scripts/create_user.py --login-id junon --password-stdin

password는 argv로 받지 않는다. argv는 `ps`, 셸 히스토리, 프로세스 어카운팅에
그대로 남는다. 같은 이유로 환경변수 경로도 두지 않는다(자식 프로세스와 /proc에
노출된다).

password는 **password manager가 생성한 난수 또는 diceware 4단어 이상**으로 만든다.
기계가 강제하는 것은 길이 하한 하나이고(아래 PASSWORD_MIN_CODE_POINTS) 나머지는
운영 규칙이다 (spec/04_SECURITY_AND_DATA.md의 `Password 요구사항`, ADR-006).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# 이 프로젝트는 설치되는 패키지가 아니다(Makefile의 run도 --app-dir backend를 쓴다).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.config import get_config
from app.db import new_session
from app.models.enums import StartingLevel
from app.models.user import User
from app.services.auth import hash_password, normalize_login_id

EXIT_OK = 0
EXIT_FAILED = 2

# spec/04_SECURITY_AND_DATA.md의 `Password 요구사항 (MVP 확정)` / ADR-006.
# 온라인 무차별 대입 방어의 1차 방어선이다. code point 기준이며 **계정을 만드는
# 이 경로에서만** 검증한다. `POST /api/auth/login`은 검증하지 않는다 --- 하한 미만
# password는 DB에 존재할 수 없고, login에서 길이를 먼저 보면 실패 응답 시간이 갈려
# 추측 대상에 힌트를 준다.
#
# 설정값으로 만들지 않는다. 환경변수나 정책 YAML에 두면 "보안 하한을 낮추는
# 스위치"가 생긴다(ADR-004와 같은 판단). 바꾸려면 명세를 먼저 고친다.
PASSWORD_MIN_CODE_POINTS = 16


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _read_password(*, from_stdin: bool) -> str | None:
    if from_stdin:
        # docker login 관례. 한 줄만 읽고 개행을 떼어낸다.
        return sys.stdin.readline().rstrip("\n")
    if not sys.stdin.isatty():
        return None
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password (again): "):
        return None
    return password


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    config = get_config()
    parser = argparse.ArgumentParser(
        description=(
            "Create a Nihongo Context user. "
            f"password는 최소 {PASSWORD_MIN_CODE_POINTS} code point이며, "
            "password manager가 생성한 난수 또는 diceware 4단어 이상을 쓴다."
        )
    )
    parser.add_argument("--login-id", required=True)
    parser.add_argument(
        "--timezone",
        default=config.user.user_timezone,
        help="기본값은 config의 user.user_timezone.",
    )
    parser.add_argument(
        "--starting-level",
        default=StartingLevel.BEGINNER.value,
        choices=[level.value for level in StartingLevel],
        help="기본값은 beginner (06_LEARNING_ENGINE.md의 Cold Start).",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="stdin 한 줄에서 password를 읽는다. 비대화형 실행용.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    login_id = normalize_login_id(args.login_id)
    if not login_id:
        return _fail("--login-id must not be empty")

    password = _read_password(from_stdin=args.password_stdin)
    if password is None:
        return _fail("password input failed (mismatch, or no TTY without --password-stdin)")
    if len(password) < PASSWORD_MIN_CODE_POINTS:
        # 복잡도 혼용 규칙·금지어 목록·유출 조회·최대 길이는 두지 않는다
        # (명세가 명시적으로 금지한다). 기계 검증은 이 하한 하나다.
        return _fail(
            f"password must be at least {PASSWORD_MIN_CODE_POINTS} code points "
            "(use a password manager or four or more diceware words)"
        )

    try:
        session = new_session()
    except RuntimeError as exc:
        return _fail(str(exc))

    with session:
        if session.scalar(select(User.id).where(User.login_id == login_id)) is not None:
            return _fail(f"login_id already exists: {login_id}")
        user = User(
            login_id=login_id,
            password_hash=hash_password(password),
            timezone=args.timezone,
            starting_level=StartingLevel(args.starting_level),
        )
        session.add(user)
        session.commit()
        sys.stdout.write(f"created user {user.id} ({login_id})\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
