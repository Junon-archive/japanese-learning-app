#!/usr/bin/env python
"""prompt_versions 등록 CLI (04_DB_SPEC.md의 `등록 절차`).

    export DATABASE_URL=...
    uv run python scripts/load_prompts.py --provider openai --model <모델명>
    uv run python scripts/load_prompts.py --provider openai --model <모델명> \
        --task EXPLAIN_ITEM

`prompt_versions`에 직접 INSERT하지 않는다. worker는 task 3종 전부에
`active = true` 행이 있어야 기동하므로(`app.jobs.worker.check_active_prompt_versions`)
배포에서 worker를 띄우는 경로가 이 스크립트다.

세 값의 출처가 다르다.

``` text
version   코드의 prompt registry (app.llm.prompts). 본문과 두 곳에 적으면 갈린다
provider  운영자가 --provider로 준다. 값의 도메인은 04_DB_SPEC.md가 정한다
model     운영자가 --model로 준다. 코드에도 config YAML에도 두지 않는다 (08_LLM_SPEC.md)
```

같은 version 문자열로 본문만 바꿔 재등록하는 것은 이 스크립트가 도울 수 없다. 본문이
바뀌면 `{n}`을 올려 registry에 새 version을 두고 그것을 등록한다(04_DB_SPEC.md).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

# 이 프로젝트는 설치되는 패키지가 아니다(Makefile의 run도 --app-dir backend를 쓴다).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.clock import utc_now  # noqa: E402
from app.db import new_session  # noqa: E402
from app.llm.prompts import PROMPT_TEMPLATES  # noqa: E402
from app.llm.provider import OPENAI  # noqa: E402
from app.models.enums import LlmTaskType  # noqa: E402
from app.models.jobs import PromptVersion  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 2

# 04_DB_SPEC.md의 `prompt_versions.provider`: 실행 **구현 이름**이며 도메인은
# `openai | stub`다. 모델명이 아니므로 여기 두어도 원칙 8에 걸리지 않는다. 자유
# 문자열로 받으면 오타 하나가 모든 콘텐츠의 provenance에 남는다(사후 구분 불가).
# `stub`은 test double이 만든 콘텐츠 표시이고 `LLM_PROVIDER`가 가질 수 있는 값이
# 아니다(08_LLM_SPEC.md, ADR-016).
STUB = "stub"
PROVIDERS = (OPENAI, STUB)


class PromptRegistrationError(RuntimeError):
    """등록할 수 없는 인자. DB를 건드리기 전에 판정한다."""


@dataclass(frozen=True)
class Registered:
    task_type: LlmTaskType
    version: str
    created: bool


def _fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return EXIT_FAILED


def resolve_version(task_type: LlmTaskType, explicit: str | None) -> str:
    """version은 코드의 registry에서 온다. `--version`은 그중 하나를 고르는 수단이다.

    registry에 없는 version을 등록하면 worker가 그 행을 읽고 본문을 찾지 못해
    (`UnknownPromptVersionError`) 그 task의 job이 전부 `dead_letter`가 된다. 그래서
    존재하지 않는 version은 DB에 닿기 전에 거부한다.
    """
    known = sorted(version for task, version in PROMPT_TEMPLATES if task is task_type)
    if explicit is not None:
        if explicit not in known:
            raise PromptRegistrationError(
                f"no prompt template in code for {task_type.value} version {explicit!r} "
                f"(known: {', '.join(known) or 'none'})"
            )
        return explicit
    if not known:
        raise PromptRegistrationError(f"no prompt template in code for {task_type.value}")
    if len(known) > 1:
        # 옛 version으로 rollback하는 경우다. 어느 쪽이 active여야 하는지는 코드가
        # 모른다 --- 최신을 고르면 rollback이 불가능해진다(04_DB_SPEC.md).
        raise PromptRegistrationError(
            f"{task_type.value} has several prompt versions in code "
            f"({', '.join(known)}); choose one with --task {task_type.value} --version"
        )
    return known[0]


def upsert_prompt_version(
    db: Session,
    *,
    task_type: LlmTaskType,
    version: str,
    provider: str,
    model: str,
    now: datetime,
) -> Registered:
    """`(task_type, version)`을 upsert하고 그 행만 active로 남긴다.

    순서가 계약이다. `uq_prompt_versions_active`는 `UNIQUE (task_type) WHERE active`인
    partial unique이므로, 같은 task_type의 기존 active를 **먼저** 내리지 않고 새 행을
    active로 넣으면 IntegrityError다. 그래서 새 행은 `active = false`로 들어가고, 다른
    행을 내린 뒤 마지막에 올린다. 호출자가 한 트랜잭션으로 감싸므로 "active가 없는"
    중간 상태는 밖에서 보이지 않는다.
    """
    row = db.scalar(
        sa.select(PromptVersion).where(
            PromptVersion.task_type == task_type, PromptVersion.version == version
        )
    )
    created = row is None
    if row is None:
        row = PromptVersion(
            task_type=task_type,
            version=version,
            provider=provider,
            model=model,
            active=False,
            # created_at에 server_default가 없다. 진입점이 값을 채운다 (ADR-007).
            created_at=now,
        )
        db.add(row)
    else:
        # 본문은 코드에 있고 이 행에 없다. 갱신 대상은 운영자가 정하는 둘뿐이다
        # (04_DB_SPEC.md의 등록 절차 1).
        row.provider = provider
        row.model = model
    db.flush()

    db.execute(
        sa.update(PromptVersion)
        .where(
            PromptVersion.task_type == task_type,
            PromptVersion.id != row.id,
            PromptVersion.active,
        )
        .values(active=False)
    )
    row.active = True
    db.flush()

    return Registered(task_type=task_type, version=version, created=created)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register prompt_versions rows and activate them.")
    parser.add_argument(
        "--provider",
        required=True,
        choices=PROVIDERS,
        help="실행 구현 이름. 모델을 고르는 값이 아니다 (08_LLM_SPEC.md).",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="요청에 쓸 모델 문자열. 기본값은 없다 --- 운영자가 정한다.",
    )
    parser.add_argument(
        "--task",
        choices=[task.value for task in LlmTaskType],
        help="기본값은 task 3종 전부.",
    )
    parser.add_argument(
        "--version",
        help="registry에 본문이 있는 version. 생략하면 그 task의 유일한 version.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.version is not None and args.task is None:
        return _fail("--version requires --task (version is per task_type)")
    if not args.model.strip():
        return _fail("--model must not be empty")

    tasks = [LlmTaskType(args.task)] if args.task else list(LlmTaskType)
    try:
        targets = [(task, resolve_version(task, args.version)) for task in tasks]
    except PromptRegistrationError as exc:
        return _fail(str(exc))

    try:
        session = new_session()
    except RuntimeError as exc:
        return _fail(str(exc))

    # 진입점이 시각을 한 번 읽고 값으로 넘긴다 (ADR-007).
    now = utc_now()
    with session:
        registered = [
            upsert_prompt_version(
                session,
                task_type=task,
                version=version,
                provider=args.provider,
                model=args.model,
                now=now,
            )
            for task, version in targets
        ]
        # 3종을 한 트랜잭션으로 커밋한다. 일부만 active인 DB를 남기지 않는다.
        session.commit()

    for entry in registered:
        action = "created" if entry.created else "updated"
        sys.stdout.write(
            f"{action} and activated {entry.task_type.value} {entry.version} "
            f"provider={args.provider} model={args.model}\n"
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
