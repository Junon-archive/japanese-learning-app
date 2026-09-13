#!/usr/bin/env python
"""PostgreSQL 백업: dump -> 새 백업 검증 -> rotation (spec/04_SECURITY_AND_DATA.md의 Backup).

    export DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:5432/<db>   # password는 ~/.pgpass
    uv run python scripts/db_backup.py --pg-bin <PG_BIN>

`--pg-bin`은 필수이며 기본값도 PATH 탐색도 없다(ADR-020 결정 2). 운영 값은
`<REPO>/.venv/lib/python3.12/site-packages/pgserver/pginstall/bin`이다.

-   작업 전에 password를 가린 대상 DSN과 pg_dump 클라이언트 / 서버 버전을 출력한다.
    이 머신에는 운영 DB와 로컬 개발 DB가 함께 있다(ADR-020 결정 1).
-   password는 argv에 넣지 않는다(`scripts/pg_tools.py`).
-   파일은 `os.open(..., 0o600)`으로 **만드는 순간부터** 0600이다. pg_dump는 그 fd에
    쓴다. 만든 뒤 chmod로 줄이면 그 사이에 다른 사용자가 읽을 수 있는 창이 생긴다.
-   `*.partial`로 쓰고 새 백업 검증(pg_dump 성공, 비어 있지 않음, `pg_restore --list`가
    목차를 끝까지 읽음)이 끝난 뒤에만 완성된 이름으로 바꾼다.
-   rotation은 **새 백업 검증이 끝난 뒤에만** 한다. 검증이 실패하면 아무것도 지우지 않고
    non-zero로 끝난다. 대상은 이 명령의 이름 패턴(`backup-<UTC>.dump`)뿐이다.

서비스가 살아 있는 채로 dump해도 된다(pg_dump는 한 트랜잭션 스냅샷이다). API·worker를
멈추라는 요구는 restore 검증과 migration에만 있다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pg_tools  # noqa: E402

from app.clock import utc_now  # noqa: E402
from app.settings import get_settings  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

DEFAULT_BACKUP_DIR = REPO_ROOT / "data" / "backups"
# spec/04_SECURITY_AND_DATA.md의 `주기와 보관 개수`. 운영값이라 config YAML에 두지 않는다.
DEFAULT_KEEP = 7

# 이름의 시각은 UTC다. 같은 길이의 고정 형식이라 이름 순서가 곧 시간 순서다.
BACKUP_NAME_FORMAT = "backup-%Y%m%dT%H%M%SZ.dump"
BACKUP_NAME_PATTERN = re.compile(r"backup-\d{8}T\d{6}Z\.dump")
PARTIAL_SUFFIX = ".partial"


class BackupError(Exception):
    """새 백업을 완성하지 못했다. 이 예외가 나면 rotation은 일어나지 않았다."""


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    # pipe/cron 로그에서도 다음 단계 전에 보이게 한다.
    sys.stdout.flush()


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _verify(partial: Path, pg_restore: Path) -> None:
    """새 백업 검증 = 파일 온전성. 복원 데이터가 원본과 같다는 증명은 restore 검증이다."""
    if partial.stat().st_size == 0:
        raise BackupError(f"{partial.name} is empty")
    listing = pg_tools.run([str(pg_restore), "--list", str(partial)], extra_env={})
    if listing.returncode != 0:
        raise BackupError(f"pg_restore --list could not read {partial.name}: {listing.stderr}")


def rotate(backup_dir: Path, keep: int) -> list[Path]:
    """보관 개수를 넘는 가장 오래된 것부터 지운다. 이 명령의 이름 패턴 파일만 센다."""
    backups = sorted(
        path
        for path in backup_dir.iterdir()
        if path.is_file() and BACKUP_NAME_PATTERN.fullmatch(path.name)
    )
    expired = backups[: max(0, len(backups) - keep)]
    for path in expired:
        path.unlink()
        _out(f"rotated out: {path.name}\n")
    return expired


def create_backup(dsn: URL, *, pg_bin: Path, backup_dir: Path, keep: int) -> Path:
    """dump -> 새 백업 검증 -> rename -> rotation. 실패하면 `BackupError`이고 지운 것이 없다."""
    try:
        conninfo, extra_env = pg_tools.libpq_connection(dsn)
        pg_dump = pg_tools.tool(pg_bin, "pg_dump")
        pg_restore = pg_tools.tool(pg_bin, "pg_restore")
        client = pg_tools.client_version(pg_dump)
        server = pg_tools.server_version(dsn)
    except (OSError, ValueError, sa.exc.SQLAlchemyError) as exc:
        raise BackupError(str(exc)) from exc
    _out(f"pg_dump client: {client}\nserver version: {server}\n")

    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = backup_dir / utc_now().strftime(BACKUP_NAME_FORMAT)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    if final.exists():
        raise BackupError(f"{final.name} already exists")

    try:
        # O_EXCL: 남의 파일(심볼릭 링크 포함)을 이어 쓰지 않는다. mode는 생성 시점에 적용된다.
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise BackupError(f"cannot create {partial}: {exc}") from exc

    completed = False
    try:
        try:
            dump = pg_tools.run(
                [
                    str(pg_dump),
                    "--format=custom",
                    "--no-owner",
                    # password 프롬프트로 멈추지 않고 실패한다(cron에는 TTY가 없다).
                    "--no-password",
                    f"--dbname={conninfo}",
                ],
                extra_env=extra_env,
                stdout=fd,
            )
        finally:
            os.close(fd)
        if dump.returncode != 0:
            raise BackupError(f"pg_dump exited with {dump.returncode}: {dump.stderr}")
        _verify(partial, pg_restore)
        partial.rename(final)
        completed = True
    finally:
        if not completed:
            # 실패한 파일은 보관 개수에 세지 않는다. 비밀번호 hash가 든 조각을 남기지도 않는다.
            partial.unlink(missing_ok=True)

    _out(f"backup verified: {final}\n")
    rotate(backup_dir, keep)
    return final


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Back up DATABASE_URL with pg_dump, verify the new file, then rotate old backups. "
            "password는 argv로 넘기지 않는다(DSN의 password는 PGPASSWORD로, 없으면 ~/.pgpass)."
        )
    )
    parser.add_argument(
        "--pg-bin",
        type=Path,
        required=True,
        help="pg_dump / pg_restore가 있는 디렉터리. 기본값도 PATH 탐색도 없다.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help=f"백업 디렉터리 (기본값 {DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--keep",
        type=positive_int,
        default=DEFAULT_KEEP,
        help=f"보관 개수 (기본값 {DEFAULT_KEEP}). 새 백업 검증 뒤에만 넘는 것을 지운다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = get_settings().database_url
    if not database_url:
        return _fail("DATABASE_URL is not configured")
    dsn = make_url(database_url)
    if not dsn.database:
        return _fail("DATABASE_URL has no database name")

    try:
        _out(pg_tools.describe_target(dsn))
    except ValueError as exc:
        return _fail(str(exc))
    try:
        path = create_backup(dsn, pg_bin=args.pg_bin, backup_dir=args.backup_dir, keep=args.keep)
    except BackupError as exc:
        return _fail(f"backup failed; nothing was rotated: {exc}")
    _out(f"backup written: {path}\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
