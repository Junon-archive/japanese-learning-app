#!/usr/bin/env python
"""starter seed 적재 CLI.

    export DATABASE_URL=...
    uv run python scripts/load_seed.py                      # repo 루트의 seed/ja/
    uv run python scripts/load_seed.py --seed-dir path/to/seed
    uv run python scripts/load_seed.py --language en --incremental   # seed/en/, 증분 적재

기본(비-incremental) 모드는 재적재를 지원하지 않는다. `origin = seed` 행이 이미
있으면 거부한다. seed를 고쳤으면 `make db-reset ARGS=--yes && make seed`로 다시
만든다. 이건 빈 DB 전용이다.

`--incremental`은 파일의 `seed_id` 중 DB에 없는 것만 넣고 이미 있는 것은 건너뛴다
(`04_DB_SPEC.md`의 `증분 적재`). 운영 DB에 언어를 추가할 때 쓴다.

문장마다 후리가나를 계산한다(ADR-021, 일본어 전용 ADR-024 결정 6). 분석기를 적재하지
못하면 DB에 닿기 전에 예외로 끝난다(fail-closed). 문장 하나의 계산 실패는 그 문장만
`ruby_json = NULL`로 두고 요약의 `failed`로 센다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 이 프로젝트는 설치되는 패키지가 아니다(Makefile의 run도 --app-dir backend를 쓴다).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.clock import utc_now  # noqa: E402
from app.config import get_config  # noqa: E402
from app.db import new_session  # noqa: E402
from app.furigana import format_summary_lines, load_analyzer  # noqa: E402
from app.models.enums import Language  # noqa: E402
from app.services.seed_loader import SeedError, load_seed  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

SEED_ROOT = REPO_ROOT / "seed"


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load the starter seed set.")
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=None,
        help="items.yaml / sentences.yaml이 있는 디렉터리 (기본값 seed/<language>/).",
    )
    parser.add_argument(
        "--language",
        choices=[member.value for member in Language],
        default=Language.JA.value,
        help="적재할 언어 (기본값 ja). --seed-dir을 주지 않으면 seed/<language>/를 쓴다.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="이미 있는 seed_id는 건너뛰고 새 seed_id만 추가한다. 기본은 빈 DB 전용 전체 적재다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    language = Language(args.language)
    seed_dir = args.seed_dir if args.seed_dir is not None else SEED_ROOT / language.value
    # 문장 길이 상한과 문장당 target 상한은 정책값이다(14_CONFIGURATION.md). 설정을
    # 읽지 못하면 DB에 닿기 전에 끝난다.
    cfg = get_config()

    # 일본어만 분석기가 필요하다(ADR-024 결정 6). 분석기 부재는 배포 결함이고 문장별
    # NULL로 흡수하지 않고 여기서 그대로 던진다.
    if language is Language.JA:
        load_analyzer()

    try:
        session = new_session()
    except RuntimeError as exc:
        return _fail(str(exc))

    with session:
        try:
            # 진입점이 시각을 한 번 읽고 값으로 넘긴다 (ADR-007).
            summary = load_seed(
                session,
                seed_dir,
                now=utc_now(),
                cfg=cfg,
                language=language,
                incremental=args.incremental,
            )
        except SeedError as exc:
            # 적재는 한 트랜잭션이다. 실패하면 DB에 아무것도 남기지 않는다.
            session.rollback()
            return _fail(str(exc))
        session.commit()

    sys.stdout.write(
        f"loaded seed from {seed_dir} (language={language.value}, incremental={args.incremental}): "
        f"items {summary.items_inserted} inserted / {summary.items_skipped} skipped "
        f"of {summary.items} in file, "
        f"sentences {summary.sentences_inserted} inserted / {summary.sentences_skipped} skipped "
        f"of {summary.sentences} in file, "
        f"{summary.spans} spans, {summary.explanations} explanations\n"
    )
    sys.stdout.write("".join(f"{line}\n" for line in format_summary_lines(summary.ruby)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
