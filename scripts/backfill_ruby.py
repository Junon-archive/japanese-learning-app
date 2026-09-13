#!/usr/bin/env python
"""기존 문장의 후리가나 backfill (04_DB_SPEC.md의 `MVP-02: additive migration과 후리가나 backfill`).

    export DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:5432/<db>
    uv run python scripts/backfill_ruby.py                                  # dry-run (쓰기 없음)
    uv run python scripts/backfill_ruby.py --apply --pg-bin <PG_BIN>        # 백업 뒤 쓰기

`scripts/db_migrate.py`와 같은 형태다.

``` text
1 대상 출력   password를 가린 DSN, 현재 algorithm_version
2 대상 조회   WHERE ruby_json IS NULL ORDER BY id
              tappable span과 explanation.reading(status = validated 중 id가 가장 작은 행)
3 계산        메모리에서만. 요약, 규칙별 적중, 불일치 목록을 출력한다
4 dry-run     --apply가 없으면 "dry-run: nothing written"을 출력하고 7로 간다
5 --apply     쓸 행(계산에 성공한 행)이 0이면 백업 없이 7로 간다
              있으면 검증된 백업을 만든다. 실패하면 쓰기 없이 exit 2. 백업을 건너뛰는 옵션은 없다
6 쓰기        한 트랜잭션. UPDATE ... WHERE id = :id AND ruby_json IS NULL. 갱신 행 수를 출력한다
7 종료 코드   계산 실패가 하나라도 있으면 exit 2 (dry-run, 쓸 행 0 포함). 그 밖은 exit 0
```

-   **멱등 판정은 `ruby_json IS NULL` 하나다.** 이미 계산된 행(버전이 낮아도)을 다시 계산하는 옵션은 없다.
-   **API와 worker를 멈추지 않아도 된다.** `sentences`와 콘텐츠 annotation만 읽고 `sentences.ruby_json`만
    쓴다. 쓰기의 `AND ruby_json IS NULL`이 그 사이 worker나 다른 backfill이 쓴 값을 덮어쓰지 않는다.
-   `APP_ENV=production`을 거부하지 않는다(목적이 운영 DB다). 운영 대상 확인은 절차가 한다.
-   분석기를 적재하지 못하면 DB에 닿기 전에 예외로 끝난다(fail-closed).
-   `computed_at`은 이 진입점이 한 번 읽은 시각이고 모든 행에 같다(ADR-007).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import db_backup  # noqa: E402
import pg_tools  # noqa: E402

from app.clock import utc_now  # noqa: E402
from app.furigana import (  # noqa: E402
    ALGORITHM_VERSION,
    RubyItem,
    RubySummary,
    compute_ruby,
    format_summary_lines,
    load_analyzer,
)
from app.models.content import (  # noqa: E402
    Sentence,
    SentenceItem,
    SentenceItemExplanation,
    SentenceItemSpan,
)
from app.models.enums import ExplanationStatus  # noqa: E402
from app.render import ItemSpan  # noqa: E402
from app.settings import get_settings  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2


@dataclass(frozen=True)
class Target:
    sentence_id: int
    japanese: str
    items: tuple[RubyItem, ...]


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute furigana for sentences whose ruby_json IS NULL. Dry-run by default. "
            "--apply는 검증된 백업 뒤에 NULL 행만 채운다. 백업 생략·재계산 옵션은 없다."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="계산 결과를 쓴다. 쓸 행이 있으면 먼저 검증된 백업을 만든다(--pg-bin 필수).",
    )
    parser.add_argument(
        "--pg-bin",
        type=Path,
        default=None,
        help="pg_dump / pg_restore가 있는 디렉터리. --apply에서 필수다. 기본값도 PATH 탐색도 없다.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=db_backup.DEFAULT_BACKUP_DIR,
        help=f"백업 디렉터리 (기본값 {db_backup.DEFAULT_BACKUP_DIR}).",
    )
    parser.add_argument(
        "--keep",
        type=db_backup.positive_int,
        default=db_backup.DEFAULT_KEEP,
        help=f"보관 개수 (기본값 {db_backup.DEFAULT_KEEP}).",
    )
    return parser.parse_args(argv)


def load_targets(connection: sa.Connection) -> list[Target]:
    """`ruby_json IS NULL`인 문장과 그 tappable item의 span·설명 읽기. id 오름차순이다.

    설명 읽기는 `validated` 중 id가 가장 작은 행이다(`EXPLAIN_ITEM` 재실행으로 둘일 수 있다).
    validated 설명이 없는 tappable item(아직 ready가 아닌 문장)도 span은 경계로 넘기고 읽기는
    None으로 둔다 --- 계층 1을 쓰지 않고 불일치 비교에서 빠진다(`uncomparable_items`).
    """
    targets = sa.select(Sentence.id).where(Sentence.ruby_json.is_(None)).subquery()
    sentences = connection.execute(
        sa.select(Sentence.id, Sentence.japanese)
        .where(Sentence.id.in_(sa.select(targets.c.id)))
        .order_by(Sentence.id)
    ).all()
    span_rows = connection.execute(
        sa.select(
            SentenceItem.sentence_id,
            SentenceItem.id,
            SentenceItemSpan.start_codepoint,
            SentenceItemSpan.end_codepoint,
            SentenceItemSpan.span_order,
        )
        .join(SentenceItemSpan, SentenceItemSpan.sentence_item_id == SentenceItem.id)
        .where(
            SentenceItem.sentence_id.in_(sa.select(targets.c.id)),
            SentenceItem.is_tappable.is_(True),
        )
        .order_by(SentenceItem.id, SentenceItemSpan.span_order)
    ).all()
    reading_rows = connection.execute(
        sa.select(SentenceItemExplanation.sentence_item_id, SentenceItemExplanation.reading)
        .join(SentenceItem, SentenceItem.id == SentenceItemExplanation.sentence_item_id)
        .where(
            SentenceItem.sentence_id.in_(sa.select(targets.c.id)),
            SentenceItem.is_tappable.is_(True),
            SentenceItemExplanation.status == ExplanationStatus.VALIDATED,
        )
        .order_by(SentenceItemExplanation.id)
    ).all()

    readings: dict[int, str] = {}
    for sentence_item_id, reading in reading_rows:
        readings.setdefault(int(sentence_item_id), str(reading))
    spans: dict[int, dict[int, list[ItemSpan]]] = {}
    for sentence_id, sentence_item_id, start, end, order in span_rows:
        by_item = spans.setdefault(int(sentence_id), {})
        by_item.setdefault(int(sentence_item_id), []).append(ItemSpan(start, end, order))

    return [
        Target(
            sentence_id=int(sentence_id),
            japanese=str(japanese),
            items=tuple(
                RubyItem(
                    sentence_item_id=item_id,
                    spans=tuple(item_spans),
                    explanation_reading=readings.get(item_id),
                )
                for item_id, item_spans in spans.get(int(sentence_id), {}).items()
            ),
        )
        for sentence_id, japanese in sentences
    ]


def write_values(connection: sa.Connection, values: Sequence[tuple[int, dict[str, Any]]]) -> int:
    """한 트랜잭션. 조회와 같은 조건(`ruby_json IS NULL`)을 다시 걸어 늦은 쪽이 덮어쓰지 않는다."""
    updated = 0
    with connection.begin():
        for sentence_id, value in values:
            result = connection.execute(
                sa.update(Sentence)
                .where(Sentence.id == sentence_id, Sentence.ruby_json.is_(None))
                .values(ruby_json=value)
            )
            updated += result.rowcount
    return updated


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.apply and args.pg_bin is None:
        return _fail("--apply requires --pg-bin (a verified backup is taken before writing)")
    # 분석기 부재는 배포 결함이다. 문장별 실패로 흡수하지 않는다.
    load_analyzer()

    database_url = get_settings().database_url
    if not database_url:
        return _fail("DATABASE_URL is not configured")
    dsn: URL = make_url(database_url)
    if not dsn.database:
        return _fail("DATABASE_URL has no database name")

    # 1. 대상 출력
    try:
        _out(pg_tools.describe_target(dsn))
    except ValueError as exc:
        return _fail(str(exc))
    _out(f"algorithm_version={ALGORITHM_VERSION}\n")

    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        # 2. 대상 조회
        with engine.connect() as connection:
            targets = load_targets(connection)
        _out(f"sentences with ruby_json IS NULL: {len(targets)}\n")

        # 3. 계산 (메모리에서만)
        now = utc_now()
        summary = RubySummary()
        values: list[tuple[int, dict[str, Any]]] = []
        for target in targets:
            try:
                computation = compute_ruby(target.japanese, target.items, now=now)
            except Exception as exc:
                summary.add_failure()
                _out(f"failed sentence={target.sentence_id} error={type(exc).__name__}\n")
                continue
            summary.add(str(target.sentence_id), computation)
            values.append((target.sentence_id, computation.ruby_json))
        _out("".join(f"{line}\n" for line in format_summary_lines(summary)))
        exit_code = EXIT_FAILED if summary.failed else EXIT_OK

        # 4. dry-run
        if not args.apply:
            _out("dry-run: nothing written\n")
            return exit_code

        # 5. 쓸 행이 없으면 백업도 없다
        if not values:
            _out("nothing to write; no backup taken\n")
            return exit_code
        try:
            db_backup.create_backup(
                dsn, pg_bin=args.pg_bin, backup_dir=args.backup_dir, keep=args.keep
            )
        except db_backup.BackupError as exc:
            return _fail(f"backup failed; nothing was written: {exc}")

        # 6. 쓰기
        with engine.connect() as connection:
            updated = write_values(connection, values)
        _out(f"updated {updated} of {len(values)} sentences\n")
    finally:
        engine.dispose()

    # 7. 종료 코드: 실패가 있으면 성공분을 쓴 뒤에도 exit 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
