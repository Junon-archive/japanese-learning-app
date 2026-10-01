#!/usr/bin/env python
"""기존 일본어 seed 행의 `seed_id` backfill (04_DB_SPEC.md의 `증분 적재`의
`기존 일본어 seed 행의 seed_id backfill`, ADR-023 결정 4).

    export DATABASE_URL=postgresql+psycopg://<user>@127.0.0.1:5432/<db>
    uv run python scripts/backfill_seed_id.py                            # dry-run (쓰기 없음)
    uv run python scripts/backfill_seed_id.py --apply --pg-bin <PG_BIN>  # 백업 뒤 쓰기

`scripts/backfill_ruby.py`와 같은 형태다.

``` text
1 대상 출력   password를 가린 DSN
2 대상 조회   learning_items: origin = seed, metadata_json.seed_order = N
              sentences:      source_type = seed, id 오름차순 N번째
              각각 seed/ja/items.yaml, seed/ja/sentences.yaml 배열의 N번째 항목과 대조한다
3 대조        item은 lemma와 reading이, 문장은 text 전체가 파일과 정확히 같아야 한다.
              하나라도 다르면 아무것도 쓰지 않고 exit 2
4 dry-run     --apply가 없으면 "dry-run: nothing written"을 출력하고 6으로 간다
5 --apply     쓸 행(seed_id가 NULL인 행)이 0이면 백업 없이 6으로 간다
              있으면 검증된 백업을 만든다. 실패하면 쓰기 없이 exit 2. 백업을 건너뛰는 옵션은 없다
6 쓰기        한 트랜잭션. UPDATE ... WHERE id = :id AND seed_id IS NULL. 갱신 행 수를 출력한다
7 종료 코드   대조 실패가 있으면 쓰기 없이 exit 2. 그 밖은 exit 0 (대상 0건 포함, 멱등)
```

-   **멱등 판정은 `seed_id IS NULL`이다.** 이미 채워진 행은 다시 쓰지 않는다.
-   **대조 후에만 쓴다.** 틀린 키를 붙이면 다음 증분 적재가 다른 item을 "이미 있다"고
    판단해 건너뛴다 --- 그래서 하나라도 어긋나면 아무것도 쓰지 않는다.
-   **API와 worker를 멈추지 않아도 된다.** `learning_items`/`sentences`의 `seed_id`
    컬럼만 쓴다.
-   `APP_ENV=production`을 거부하지 않는다(목적이 운영 DB다). 운영 대상 확인은 절차가 한다.
-   현재는 일본어 seed(`seed/ja/`)만 대상이다. 다른 언어가 생기면 `--seed-dir`로 넘긴다.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import db_backup  # noqa: E402
import pg_tools  # noqa: E402

from app.models.content import LearningItem, Sentence  # noqa: E402
from app.models.enums import LearningItemOrigin, SentenceSourceType  # noqa: E402
from app.settings import get_settings  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

DEFAULT_SEED_DIR = REPO_ROOT / "seed" / "ja"


@dataclass(frozen=True)
class ItemWrite:
    id: int
    seed_id: str


@dataclass(frozen=True)
class SentenceWrite:
    id: int
    seed_id: str


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def _out(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fill learning_items.seed_id / sentences.seed_id for existing seed rows by "
            "matching them against the seed files. Dry-run by default. --apply는 검증된 "
            "백업 뒤에 NULL 행만 채운다. 백업 생략 옵션은 없다."
        )
    )
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=DEFAULT_SEED_DIR,
        help=f"items.yaml / sentences.yaml이 있는 디렉터리 (기본값 {DEFAULT_SEED_DIR}).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="대조를 마친 뒤 seed_id를 쓴다. 쓸 행이 있으면 먼저 검증된 백업을 만든다(--pg-bin 필수).",
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


def _load_yaml_list(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: top level must be a list of entries")
    return [dict(entry) for entry in raw]


def _match_items(
    connection: sa.Connection, items_file: list[dict[str, Any]]
) -> tuple[list[ItemWrite], list[str]]:
    """`learning_items`를 `metadata_json.seed_order`로 파일과 대조한다.

    돌려주는 첫 값은 쓸 행(`seed_id IS NULL`인 것만), 둘째 값은 대조 실패 메시지 목록이다.
    실패 목록이 비어 있지 않으면 호출자가 아무것도 쓰지 않는다.
    """
    rows = connection.execute(
        sa.select(
            LearningItem.id,
            LearningItem.seed_id,
            LearningItem.lemma,
            LearningItem.reading,
            LearningItem.metadata_json,
        ).where(LearningItem.origin == LearningItemOrigin.SEED)
    ).all()

    by_order: dict[int, tuple[int, str | None, str, str | None]] = {}
    mismatches: list[str] = []
    for row_id, seed_id, lemma, reading, metadata in rows:
        order = metadata.get("seed_order") if isinstance(metadata, dict) else None
        if not isinstance(order, int):
            mismatches.append(f"learning_item id={row_id}: metadata_json has no integer seed_order")
            continue
        if order in by_order:
            mismatches.append(f"learning_item id={row_id}: duplicate seed_order={order}")
            continue
        by_order[order] = (row_id, seed_id, lemma, reading)

    writes: list[ItemWrite] = []
    for index, entry in enumerate(items_file):
        order = index + 1
        found = by_order.get(order)
        if found is None:
            mismatches.append(
                f"items.yaml[{index}] (seed_order={order}): no matching learning_item"
            )
            continue
        row_id, existing_seed_id, lemma, reading = found
        file_seed_id = str(entry.get("seed_id"))
        file_lemma = entry.get("lemma")
        file_reading = entry.get("reading")
        if lemma != file_lemma or reading != file_reading:
            mismatches.append(
                f"items.yaml[{index}] (seed_order={order}): "
                f"db lemma={lemma!r} reading={reading!r} != "
                f"file lemma={file_lemma!r} reading={file_reading!r}"
            )
            continue
        if existing_seed_id is None:
            writes.append(ItemWrite(id=row_id, seed_id=file_seed_id))
        elif existing_seed_id != file_seed_id:
            mismatches.append(
                f"items.yaml[{index}] (seed_order={order}): "
                f"db seed_id={existing_seed_id!r} != file seed_id={file_seed_id!r}"
            )

    extra_orders = set(by_order) - {index + 1 for index in range(len(items_file))}
    for order in sorted(extra_orders):
        row_id = by_order[order][0]
        mismatches.append(
            f"learning_item id={row_id}: seed_order={order} has no matching items.yaml entry "
            f"(file has {len(items_file)} entries)"
        )

    return writes, mismatches


def _match_sentences(
    connection: sa.Connection, sentences_file: list[dict[str, Any]]
) -> tuple[list[SentenceWrite], list[str]]:
    """`sentences`를 `id` 오름차순으로 파일과 대조한다 (`문장 순서 = sentences.id 순서`)."""
    rows = connection.execute(
        sa.select(Sentence.id, Sentence.seed_id, Sentence.text)
        .where(Sentence.source_type == SentenceSourceType.SEED)
        .order_by(Sentence.id)
    ).all()

    mismatches: list[str] = []
    if len(rows) != len(sentences_file):
        mismatches.append(
            f"sentences.yaml has {len(sentences_file)} entries but the DB has {len(rows)} "
            "origin=seed sentences; positional matching is not reliable"
        )
        return [], mismatches

    writes: list[SentenceWrite] = []
    for index, (entry, (row_id, existing_seed_id, text)) in enumerate(
        zip(sentences_file, rows, strict=True)
    ):
        file_seed_id = str(entry.get("seed_id"))
        file_text = entry.get("text")
        if text != file_text:
            mismatches.append(
                f"sentences.yaml[{index}] (sentence id={row_id}): "
                f"db text={text!r} != file text={file_text!r}"
            )
            continue
        if existing_seed_id is None:
            writes.append(SentenceWrite(id=row_id, seed_id=file_seed_id))
        elif existing_seed_id != file_seed_id:
            mismatches.append(
                f"sentences.yaml[{index}] (sentence id={row_id}): "
                f"db seed_id={existing_seed_id!r} != file seed_id={file_seed_id!r}"
            )

    return writes, mismatches


def _write_values(
    connection: sa.Connection,
    *,
    item_writes: list[ItemWrite],
    sentence_writes: list[SentenceWrite],
) -> tuple[int, int]:
    """한 트랜잭션. 조회와 같은 조건(`seed_id IS NULL`)을 다시 걸어 늦은 쪽이 덮어쓰지 않는다."""
    items_updated = 0
    sentences_updated = 0
    with connection.begin():
        for write in item_writes:
            result = connection.execute(
                sa.update(LearningItem)
                .where(LearningItem.id == write.id, LearningItem.seed_id.is_(None))
                .values(seed_id=write.seed_id)
            )
            items_updated += result.rowcount
        for sentence_write in sentence_writes:
            result = connection.execute(
                sa.update(Sentence)
                .where(Sentence.id == sentence_write.id, Sentence.seed_id.is_(None))
                .values(seed_id=sentence_write.seed_id)
            )
            sentences_updated += result.rowcount
    return items_updated, sentences_updated


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.apply and args.pg_bin is None:
        return _fail("--apply requires --pg-bin (a verified backup is taken before writing)")

    try:
        items_file = _load_yaml_list(args.seed_dir / "items.yaml")
        sentences_file = _load_yaml_list(args.seed_dir / "sentences.yaml")
    except (OSError, ValueError) as exc:
        return _fail(str(exc))

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

    engine = sa.create_engine(dsn, poolclass=NullPool)
    try:
        # 2·3. 대상 조회와 대조
        with engine.connect() as connection:
            item_writes, item_mismatches = _match_items(connection, items_file)
            sentence_writes, sentence_mismatches = _match_sentences(connection, sentences_file)

        mismatches = item_mismatches + sentence_mismatches
        if mismatches:
            for line in mismatches:
                _out(f"mismatch: {line}\n")
            _out(f"mismatches: {len(mismatches)}\n")
            return EXIT_FAILED

        _out(
            f"learning_items to backfill: {len(item_writes)}, "
            f"sentences to backfill: {len(sentence_writes)}\n"
        )

        # 4. dry-run
        if not args.apply:
            _out("dry-run: nothing written\n")
            return EXIT_OK

        # 5. 쓸 행이 없으면 백업도 없다
        if not item_writes and not sentence_writes:
            _out("nothing to write; no backup taken\n")
            return EXIT_OK
        try:
            db_backup.create_backup(
                dsn, pg_bin=args.pg_bin, backup_dir=args.backup_dir, keep=args.keep
            )
        except db_backup.BackupError as exc:
            return _fail(f"backup failed; nothing was written: {exc}")

        # 6. 쓰기
        with engine.connect() as connection:
            items_updated, sentences_updated = _write_values(
                connection, item_writes=item_writes, sentence_writes=sentence_writes
            )
        _out(
            f"updated {items_updated} of {len(item_writes)} learning_items, "
            f"{sentences_updated} of {len(sentence_writes)} sentences\n"
        )
    finally:
        engine.dispose()

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
