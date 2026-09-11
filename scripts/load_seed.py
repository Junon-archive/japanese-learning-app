#!/usr/bin/env python
"""starter seed 적재 CLI.

    export DATABASE_URL=...
    uv run python scripts/load_seed.py            # repo 루트의 seed/
    uv run python scripts/load_seed.py --seed-dir path/to/seed

재적재는 지원하지 않는다. `origin = seed` 행이 이미 있으면 거부한다.
seed를 고쳤으면 `make db-reset ARGS=--yes && make seed`로 다시 만든다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 이 프로젝트는 설치되는 패키지가 아니다(Makefile의 run도 --app-dir backend를 쓴다).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.clock import utc_now  # noqa: E402
from app.db import new_session  # noqa: E402
from app.services.seed_loader import SeedError, load_seed  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

DEFAULT_SEED_DIR = REPO_ROOT / "seed"


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load the starter seed set.")
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=DEFAULT_SEED_DIR,
        help=f"items.yaml / sentences.yaml이 있는 디렉터리 (기본값 {DEFAULT_SEED_DIR}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        session = new_session()
    except RuntimeError as exc:
        return _fail(str(exc))

    with session:
        try:
            # 진입점이 시각을 한 번 읽고 값으로 넘긴다 (ADR-007).
            summary = load_seed(session, args.seed_dir, now=utc_now())
        except SeedError as exc:
            # 적재는 한 트랜잭션이다. 실패하면 DB에 아무것도 남기지 않는다.
            session.rollback()
            return _fail(str(exc))
        session.commit()

    sys.stdout.write(
        f"loaded seed from {args.seed_dir}: "
        f"{summary.items} items, {summary.sentences} sentences, "
        f"{summary.spans} spans, {summary.explanations} explanations\n"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
