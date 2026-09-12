"""scripts/load_prompts.py --- `prompt_versions` 등록 (04_DB_SPEC.md의 `등록 절차`).

이 스크립트의 존재 이유는 하나다. worker는 task 3종 전부에 `active = true` 행이
있어야 기동한다(`app.jobs.worker.check_active_prompt_versions`). 그래서 마지막
테스트는 "행이 생겼다"에서 멈추지 않고 **그 검사가 실제로 통과하는지**까지 본다.

DB를 쓰는 테스트는 `committed_db`다. 스크립트가 `new_session()`으로 자기 세션을 열고
스스로 커밋하므로 `db_session`의 트랜잭션 격리 안에서는 그 커밋을 볼 수 없다.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.jobs.worker import WorkerStartupError, check_active_prompt_versions
from app.llm.prompts import PROMPT_TEMPLATES
from app.models.enums import LlmTaskType
from app.models.jobs import PromptVersion
from app.settings import get_settings
from tests import factories

LOAD_PROMPTS_PATH = Path(__file__).resolve().parents[2] / "scripts" / "load_prompts.py"

EXIT_OK = 0
EXIT_FAILED = 2

# 운영자가 정하는 값이라는 것을 드러내려고 실제 모델명을 쓰지 않는다.
MODEL = "operator-chosen-model"
PROVIDER = "openai"

# registry의 key가 (task_type, version)이다. 그 pair 목록이 곧 이 매핑이다.
REGISTRY_VERSIONS = dict(PROMPT_TEMPLATES.keys())
ALL_REGISTRY_VERSIONS = {version for _, version in PROMPT_TEMPLATES}


@pytest.fixture
def load_prompts(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """scripts/는 패키지가 아니므로 파일 경로로 적재한다 (test_db_reset.py와 같은 방식).

    `sys.modules`에 먼저 꽂는 이유: dataclass가 `from __future__ import annotations`
    아래에서 자기 모듈을 다시 찾는다. 등록하지 않으면 class 정의에서 AttributeError다.
    """
    spec = importlib.util.spec_from_file_location("load_prompts", LOAD_PROMPTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli_db(
    committed_db: sessionmaker[Session], database_url: URL, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sessionmaker[Session]]:
    """스크립트가 `new_session()`으로 열 DB를 가리키게 한다. 정리는 committed_db가 한다."""
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    try:
        yield committed_db
    finally:
        # 엔진이 커넥션을 연 채 GC되면 psycopg의 ResourceWarning이 error가 된다.
        engine = get_engine()
        if engine is not None:
            engine.dispose()


def _rows(sessions: sessionmaker[Session]) -> list[PromptVersion]:
    with sessions() as session:
        return list(
            session.scalars(
                sa.select(PromptVersion).order_by(PromptVersion.task_type, PromptVersion.version)
            ).all()
        )


def _run(module: ModuleType, *extra: str) -> int:
    result = module.main(["--provider", PROVIDER, "--model", MODEL, *extra])
    return int(result)


# --------------------------------------------------------------------------
# 등록
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_registers_an_active_row_for_all_three_task_types(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    assert _run(load_prompts) == EXIT_OK

    rows = _rows(cli_db)
    assert {row.task_type for row in rows} == set(LlmTaskType)
    assert all(row.active for row in rows)


@pytest.mark.integration
def test_version_comes_from_the_code_registry(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """version을 스크립트가 만들면 registry와 갈린다. 갈리면 job이 dead_letter다."""
    assert _run(load_prompts) == EXIT_OK

    assert {row.task_type: row.version for row in _rows(cli_db)} == REGISTRY_VERSIONS


def test_no_version_string_is_written_in_the_script() -> None:
    """`sentence_gen_v1` 같은 문자열이 스크립트에 있으면 registry와 두 곳이 된다."""
    source = LOAD_PROMPTS_PATH.read_text(encoding="utf-8")

    for version in ALL_REGISTRY_VERSIONS:
        assert version not in source, version


@pytest.mark.integration
def test_provider_and_model_come_from_the_arguments(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """모델명을 코드나 config에 고정하지 않는다 (08_LLM_SPEC.md의 원칙 8)."""
    assert _run(load_prompts) == EXIT_OK

    rows = _rows(cli_db)
    assert {(row.provider, row.model) for row in rows} == {(PROVIDER, MODEL)}


def test_model_has_no_default(load_prompts: ModuleType) -> None:
    """`--model`이 없으면 argparse가 거부한다. 조용히 어떤 모델로도 등록되지 않는다."""
    with pytest.raises(SystemExit):
        load_prompts.main(["--provider", PROVIDER])


def test_an_empty_model_is_refused(
    load_prompts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert load_prompts.main(["--provider", PROVIDER, "--model", "  "]) == EXIT_FAILED
    assert "--model" in capsys.readouterr().err


@pytest.mark.integration
def test_only_the_requested_task_is_registered(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    assert _run(load_prompts, "--task", LlmTaskType.EXPLAIN_ITEM.value) == EXIT_OK

    rows = _rows(cli_db)
    assert [row.task_type for row in rows] == [LlmTaskType.EXPLAIN_ITEM]


# --------------------------------------------------------------------------
# idempotency와 active 유일성
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_running_twice_does_not_add_rows_or_duplicate_active(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """재실행이 안전해야 배포 스크립트에서 무조건 부를 수 있다."""
    assert _run(load_prompts) == EXIT_OK
    first = [(row.id, row.task_type, row.version) for row in _rows(cli_db)]

    assert _run(load_prompts) == EXIT_OK

    rows = _rows(cli_db)
    assert [(row.id, row.task_type, row.version) for row in rows] == first
    assert [row.active for row in rows] == [True, True, True]


@pytest.mark.integration
def test_a_second_run_updates_provider_and_model_in_place(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """모델 교체는 새 행이 아니라 같은 (task_type, version) 행의 갱신이다."""
    assert _run(load_prompts) == EXIT_OK
    before = {row.task_type: row.id for row in _rows(cli_db)}

    assert load_prompts.main(["--provider", "stub", "--model", "another-model"]) == EXIT_OK

    rows = _rows(cli_db)
    assert {row.task_type: row.id for row in rows} == before
    assert {(row.provider, row.model) for row in rows} == {("stub", "another-model")}


@pytest.mark.integration
def test_activating_a_new_version_deactivates_the_previous_one(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """기존 active를 먼저 내리지 않으면 `uq_prompt_versions_active`가 터진다.

    partial unique(`UNIQUE (task_type) WHERE active`)는 즉시 검사되므로, 순서가
    뒤집히면 이 테스트가 IntegrityError로 실패한다.
    """
    task = LlmTaskType.GENERATE_SENTENCE_BATCH
    with cli_db() as setup:
        previous = factories.make_prompt_version(
            setup, task_type=task, version="sentence_gen_v0", active=True
        )
        setup.commit()
        previous_id = previous.id

    assert _run(load_prompts) == EXIT_OK

    rows = [row for row in _rows(cli_db) if row.task_type is task]
    # 옛 행은 남는다. 지우면 rollback도 provenance 추적도 불가능해진다.
    assert len(rows) == 2
    assert {row.id: row.active for row in rows}[previous_id] is False
    assert [row.version for row in rows if row.active] == [REGISTRY_VERSIONS[task]]


def test_an_unknown_version_is_refused_before_touching_the_database(
    load_prompts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """DATABASE_URL이 없는데도 판정이 난다 = DB에 닿기 전에 거부했다는 뜻이다."""
    exit_code = load_prompts.main(
        [
            "--provider",
            PROVIDER,
            "--model",
            MODEL,
            "--task",
            LlmTaskType.EXPLAIN_ITEM.value,
            "--version",
            "explain_item_v999",
        ]
    )

    assert exit_code == EXIT_FAILED
    assert "no prompt template in code" in capsys.readouterr().err


def test_version_without_task_is_refused(
    load_prompts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """version은 task_type마다 다르다. 3종에 같은 문자열을 붙일 수 없다."""
    exit_code = load_prompts.main(
        ["--provider", PROVIDER, "--model", MODEL, "--version", "explain_item_v1"]
    )

    assert exit_code == EXIT_FAILED
    assert "--task" in capsys.readouterr().err


def test_an_ambiguous_registry_requires_an_explicit_version(
    load_prompts: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """코드에 한 task의 version이 둘 이상이면 스크립트가 고르지 않는다.

    최신을 자동으로 고르면 옛 version으로 되돌릴 수단이 사라진다 (04_DB_SPEC.md).
    registry는 dict 하나이므로 전제를 만드는 데 항목 하나를 더하면 된다.
    """
    task = LlmTaskType.EXPLAIN_ITEM
    monkeypatch.setitem(
        PROMPT_TEMPLATES, (task, "explain_item_v2"), PROMPT_TEMPLATES[task, REGISTRY_VERSIONS[task]]
    )

    with pytest.raises(load_prompts.PromptRegistrationError, match="several prompt versions"):
        load_prompts.resolve_version(task, None)

    # 명시하면 등록할 수 있다. 위 거부가 "전부 거부"로 굳으면 rollback이 불가능해진다.
    assert load_prompts.resolve_version(task, "explain_item_v2") == "explain_item_v2"


# --------------------------------------------------------------------------
# 안전장치
# --------------------------------------------------------------------------


def test_a_missing_database_url_fails_clearly(
    load_prompts: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()

    assert _run(load_prompts) == EXIT_FAILED
    assert "DATABASE_URL" in capsys.readouterr().err


def test_an_unknown_provider_is_refused(load_prompts: ModuleType) -> None:
    """provider는 실행 구현 이름이고 도메인은 04_DB_SPEC.md가 정한다. 오타는 provenance에 남는다."""
    with pytest.raises(SystemExit):
        load_prompts.main(["--provider", "opanai", "--model", MODEL])


# --------------------------------------------------------------------------
# 존재 이유: worker가 뜬다
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_the_worker_startup_check_fails_before_and_passes_after(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    with cli_db() as session, pytest.raises(WorkerStartupError):
        check_active_prompt_versions(session)

    assert _run(load_prompts) == EXIT_OK

    with cli_db() as session:
        check_active_prompt_versions(session)


@pytest.mark.integration
def test_a_partial_registration_still_fails_the_worker_startup_check(
    load_prompts: ModuleType, cli_db: sessionmaker[Session]
) -> None:
    """위 테스트가 "어차피 통과하는" 검사 위에 서 있지 않다는 것."""
    assert _run(load_prompts, "--task", LlmTaskType.EXPLAIN_ITEM.value) == EXIT_OK

    with cli_db() as session, pytest.raises(WorkerStartupError, match="GENERATE_SENTENCE_BATCH"):
        check_active_prompt_versions(session)
