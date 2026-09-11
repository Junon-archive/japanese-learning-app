#!/usr/bin/env python
"""로컬 개발용 PostgreSQL 기동 (ADR-002).

이 개발 머신에는 docker도 passwordless sudo도 없다. `pgserver`가 번들 PostgreSQL
16.2를 root 없이 `data/pgdata/`에 띄운다. stdout에는 SQLAlchemy 형식 DSN만 나온다.

    export DATABASE_URL="$(make db-up-local)"
    make db-reset ARGS=--yes
    make seed

`pgserver` import는 `scripts/`와 테스트 fixture에만 존재한다. `backend/app/`은
로컬 DB 기동을 알지 못한다 --- 알게 되는 순간 "애플리케이션 코드는 두 경로를
분기하지 않는다"가 깨진다(ADR-002).

이미 같은 pgdata로 서버가 떠 있으면 다시 띄우지 않고 그 DSN을 그대로 출력한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# pgserver의 get_uri()는 드라이버 없는 "postgresql://"를 준다. 그대로 SQLAlchemy에
# 넘기면 psycopg2를 찾다가 실패하므로 psycopg 3로 고정한다(tests/db_support.py와 동일).
from sqlalchemy.engine import make_url

DRIVER = "postgresql+psycopg"
REPO_ROOT = Path(__file__).resolve().parents[1]
PGDATA_DIR = REPO_ROOT / "data" / "pgdata"
DEFAULT_DATABASE = "nihongo"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the local pgserver and print its DSN.")
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"DSN에 넣을 데이터베이스 이름 (기본값 {DEFAULT_DATABASE}). "
        "이 DB는 `make db-reset`이 만든다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # 로컬/테스트 전용 의존성이다. app이 보는 경로로 끌어올리지 않는다.
    import pgserver

    PGDATA_DIR.mkdir(parents=True, exist_ok=True)
    # cleanup_mode=None: 이 프로세스가 끝나도 서버를 내리지 않는다. DSN만 찍고 빠지는
    # CLI이므로 "stop"이면 출력한 DSN이 곧바로 죽는다.
    server = pgserver.get_server(PGDATA_DIR, cleanup_mode=None)  # type: ignore[attr-defined]
    dsn = make_url(server.get_uri(database=args.database)).set(drivername=DRIVER)
    sys.stdout.write(dsn.render_as_string(hide_password=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
