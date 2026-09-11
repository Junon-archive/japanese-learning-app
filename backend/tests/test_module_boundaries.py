"""ADR-007의 정적 guard G1~G10.

`backend/app/` 전체를 AST로 훑어 모듈 경계와 시각 주입 규약을 강제한다. 주석은
지켜지지 않는다 --- Wave 1의 `app/api/router.py`가 보여준 대로 **구조로 강제하고
테스트로 고정한 것**만 지켜진다. 여기가 그 "테스트로 고정"에 해당한다.

검사 범위는 `backend/app/`이다. `scripts/`는 프로세스 진입점이라 `app/jobs/`와
같은 위치에 있고(시각을 읽어 값으로 넘긴다), `backend/tests/`는 검사 대상이
아니다.

예외는 전부 이 파일 상단의 **상수**다(`app.api.router.APPROVED_UNVERIFIABLE_ROUTES`와
같은 방식). 늘리려면 ADR-007을 먼저 고친다.

한계(ADR-007에 적힌 대로): G5/G6은 식별자 기반이라 `setattr(state, name, value)`
같은 동적 대입을 잡지 못한다. 그 자리는 Scenario 테스트가 메운다.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import app.models  # noqa: F401  (registry에 전 모델을 올린다)
from app.models.base import Base

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# --------------------------------------------------------------------------
# allowlist (ADR-007). 늘리려면 ADR을 먼저 고친다.
# --------------------------------------------------------------------------

# G7: `app/api/`에서 commit/rollback이 허용되는 (모듈, 함수).
# login/logout은 cookie를 내주기 전에 저장을 확정해야 하고(저장 실패를 성공처럼
# 응답하지 않는다), `get_current_user`의 `last_used_at` commit은 handler 본문
# **전에** 끝나므로 학습 트랜잭션과 섞이지 않는다.
COMMIT_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("api/auth.py", "login"),
        ("api/auth.py", "logout"),
        ("api/deps.py", "get_current_user"),
    }
)

# G9: `clock.utc_now()`를 부를 수 있는 (모듈, 함수). 요청 경로의 진입점 하나뿐이다.
# `app/jobs/`는 worker 진입점이라 별도로 허용한다(아래 CLOCK_READ_PACKAGES).
CLOCK_READ_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({("api/deps.py", "get_now")})
CLOCK_READ_PACKAGES: frozenset[str] = frozenset({"jobs"})

# G8: 시계를 직접 읽어도 되는 모듈. 하나뿐이고 늘리지 않는다.
CLOCK_MODULE = "clock.py"

# G5: 컬럼 쓰기 소유권. 값은 **컬럼명**이고 키는 소유자 경로다.
SRS_OWNED_COLUMNS: frozenset[str] = frozenset(
    {
        "stability",
        "difficulty",
        "state",
        "step",
        "last_review_at",
        "next_review_at",
        "reps",
        "lapses",
        "deferred_until",
        "fsrs_params_version",
    }
)
MASTERY_OWNED_COLUMNS: frozenset[str] = frozenset(
    {
        "comprehension_mastery",
        "evidence_count",
        "mastery_algorithm_version",
        "last_updated_at",
    }
)
MASTERY_OWNER = "learning/mastery.py"

# G6: 이 식별자는 컬럼 선언 한 곳에만 존재한다. MVP는 listening을 읽지도 쓰지도 않는다.
LISTENING_MASTERY = "listening_mastery"
LISTENING_MASTERY_OWNER = "models/learning.py"

# G3/G4: 외부 패키지를 부를 수 있는 자리.
FSRS_PACKAGE = "fsrs"
PROVIDER_PACKAGES: frozenset[str] = frozenset({"httpx", "openai", "anthropic", "requests"})

# G8이 금지하는 시각 읽기. dotted name의 **뒤 두 마디**로 판정하므로
# `datetime.now()` / `dt.datetime.now()` / `from datetime import datetime` 전부 걸린다.
BANNED_CLOCK_READS: frozenset[str] = frozenset(
    {
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "date.today",
        "time.time",
        "time.time_ns",
    }
)

# G10: SQL 시계. `server_default=sa.text("now()")`와 `sa.func.now()` 둘 다 막는다.
SQL_CLOCK_PATTERN = re.compile(r"\bnow\s*\(\s*\)|\bcurrent_timestamp\b", re.IGNORECASE)
SQL_CLOCK_CALL_SUFFIXES: frozenset[str] = frozenset({"func.now", "func.current_timestamp"})


# --------------------------------------------------------------------------
# AST 유틸
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Module:
    """`backend/app/` 안의 파이썬 모듈 하나."""

    path: str  # app/ 기준 상대 경로 (posix). 예: "api/deps.py"
    source: str
    tree: ast.Module

    def in_package(self, package: str) -> bool:
        return self.path.startswith(f"{package}/")


@lru_cache(maxsize=1)
def _modules() -> tuple[Module, ...]:
    modules = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        modules.append(
            Module(
                path=path.relative_to(APP_ROOT).as_posix(),
                source=source,
                tree=ast.parse(source, filename=str(path)),
            )
        )
    assert modules, f"no modules found under {APP_ROOT}"
    return tuple(modules)


@lru_cache(maxsize=1)
def _model_class_names() -> frozenset[str]:
    """SQLAlchemy 매퍼에 등록된 모델 클래스 이름 전부.

    하드코딩하지 않는다. 새 모델이 생기면 G5가 자동으로 그 생성자도 본다.
    """
    return frozenset(mapper.class_.__name__ for mapper in Base.registry.mappers)


def _dotted(node: ast.expr) -> str:
    """`a.b.c` 형태를 문자열로. 그 밖의 식(호출 결과 등)은 빈 문자열."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _tail(dotted: str, count: int) -> str:
    return ".".join(dotted.split(".")[-count:])


def _imports(module: Module) -> Iterator[tuple[str, int]]:
    """import된 이름 전부. `from a import b`는 `a`와 `a.b`를 **둘 다** 낸다."""
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # 이 repo는 relative import을 쓰지 않는다.
            base = node.module or ""
            yield base, node.lineno
            for alias in node.names:
                yield f"{base}.{alias.name}" if base else alias.name, node.lineno


def _imports_package(imported: str, package: str) -> bool:
    return imported == package or imported.startswith(f"{package}.")


def _calls(node: ast.AST, function: str | None = None) -> Iterator[tuple[ast.Call, str | None]]:
    """모든 호출을 **감싸는 함수 이름**과 함께 낸다(중첩 함수는 안쪽 이름)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _calls(child, child.name)
            continue
        if isinstance(child, ast.Call):
            yield child, function
        yield from _calls(child, function)


def _docstring_ids(tree: ast.Module) -> frozenset[int]:
    """docstring인 문자열 노드의 id. 규칙을 **설명하는** 문장이 규칙 위반이 되지 않게 한다."""
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return frozenset(ids)


def _string_constants(module: Module) -> Iterator[tuple[str, int]]:
    docstrings = _docstring_ids(module.tree)
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            yield node.value, node.lineno


def _assigned_attributes(module: Module) -> Iterator[tuple[str, int]]:
    """`x.attr = ...` 형태의 속성 대입 전부.

    `ast.Store` 문맥의 `Attribute`만 본다. 그래서 `Assign` / `AugAssign` /
    `AnnAssign` / `for` 타깃 / `with ... as x.attr`이 한 번에 걸리고, **읽기는
    걸리지 않는다**(review ordering은 `next_review_at`을 조회해야 한다).
    """
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            yield node.attr, node.lineno


def _keyword_writes(module: Module) -> Iterator[tuple[str, int]]:
    """모델 생성자와 `.values()` / `.update()`에 넘어간 컬럼명.

    세 형태를 전부 본다:
        ReviewState(stability=x)          생성자 키워드
        .values(stability=x)              SQLAlchemy Core 키워드
        .update({"stability": x})         dict 리터럴 키
    """
    targets = _model_class_names() | {"values", "update"}
    for call, _ in _calls(module.tree):
        callee = _dotted(call.func)
        if not callee or _tail(callee, 1) not in targets:
            continue
        for keyword in call.keywords:
            if keyword.arg is not None:
                yield keyword.arg, call.lineno
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
            if not isinstance(argument, ast.Dict):
                continue
            for key in argument.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield key.value, call.lineno


def _column_writes(module: Module) -> Iterator[tuple[str, int]]:
    yield from _assigned_attributes(module)
    yield from _keyword_writes(module)


def _report(violations: list[str]) -> str:
    return "\n".join(violations)


# --------------------------------------------------------------------------
# G1 / G2 --- 계층 import
# --------------------------------------------------------------------------


def test_g1_srs_and_learning_do_not_import_each_other() -> None:
    """정책 계층은 평평하다. mastery 갱신이 FSRS를 부르는 경로 자체를 없앤다."""
    violations = []
    for module in _modules():
        if module.in_package("srs"):
            forbidden = "app.learning"
        elif module.in_package("learning"):
            forbidden = "app.srs"
        else:
            continue
        for imported, lineno in _imports(module):
            if _imports_package(imported, forbidden):
                violations.append(f"{module.path}:{lineno} imports {imported}")
    assert violations == [], _report(violations)


def test_g2_api_does_not_import_policy_modules() -> None:
    """`api/`는 `services/`를 통해서만 정책에 닿는다 (Wave 1의 api/auth ↔ services/auth와 같은 경계)."""
    violations = []
    for module in _modules():
        if not module.in_package("api"):
            continue
        for imported, lineno in _imports(module):
            for forbidden in ("app.learning", "app.srs"):
                if _imports_package(imported, forbidden):
                    violations.append(f"{module.path}:{lineno} imports {imported}")
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G3 / G4 --- 외부 의존
# --------------------------------------------------------------------------


def test_g3_fsrs_is_imported_only_inside_srs() -> None:
    """FSRS 라이브러리는 `app/srs/` 뒤에 갇힌다."""
    violations = [
        f"{module.path}:{lineno} imports {imported}"
        for module in _modules()
        if not module.in_package("srs")
        for imported, lineno in _imports(module)
        if _imports_package(imported, FSRS_PACKAGE)
    ]
    assert violations == [], _report(violations)


def test_g4_llm_is_imported_only_by_llm_and_jobs() -> None:
    """불변식 #1: request handler는 provider를 부르지 않는다.

    `app.llm`이 `api/`나 `services/`에서 import 가능한 한, 동기 호출은 한 줄이면 된다.
    """
    violations = [
        f"{module.path}:{lineno} imports {imported}"
        for module in _modules()
        if not (module.in_package("llm") or module.in_package("jobs"))
        for imported, lineno in _imports(module)
        if _imports_package(imported, "app.llm")
    ]
    assert violations == [], _report(violations)


def test_g4_http_clients_are_imported_only_inside_llm() -> None:
    """provider SDK와 HTTP client도 `app/llm/` 밖에서는 import되지 않는다."""
    violations = [
        f"{module.path}:{lineno} imports {imported}"
        for module in _modules()
        if not module.in_package("llm")
        for imported, lineno in _imports(module)
        for package in PROVIDER_PACKAGES
        if _imports_package(imported, package)
    ]
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G5 --- 컬럼 쓰기 소유권
# --------------------------------------------------------------------------


def test_g5_fsrs_columns_are_written_only_by_srs() -> None:
    """불변식 #3의 나머지 절반.

    G1(import 금지)만으로는 부족하다. `learning/`과 `srs/`가 서로를 몰라도 **양쪽 다
    `models`를 보므로** `learning/`이 `review_states.stability`에 대입하는 물리적
    경로는 남는다. 쓰기 소유권을 함께 걸어야 그 경로가 사라진다.

    읽기는 막지 않는다. review ordering은 `next_review_at`을 조회해야 한다.
    """
    violations = [
        f"{module.path}:{lineno} writes {name}"
        for module in _modules()
        if not module.in_package("srs")
        for name, lineno in _column_writes(module)
        if name in SRS_OWNED_COLUMNS
    ]
    assert violations == [], _report(violations)


def test_g5_mastery_columns_are_written_only_by_learning_mastery() -> None:
    violations = [
        f"{module.path}:{lineno} writes {name}"
        for module in _modules()
        if module.path != MASTERY_OWNER
        for name, lineno in _column_writes(module)
        if name in MASTERY_OWNED_COLUMNS
    ]
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G6 --- listening_mastery
# --------------------------------------------------------------------------


def test_g6_listening_mastery_appears_only_in_the_column_declaration() -> None:
    """MVP는 listening을 수집하지 않는다. 컬럼은 자리만 잡고 아무도 읽거나 쓰지 않는다."""
    violations = []
    for module in _modules():
        if module.path == LISTENING_MASTERY_OWNER:
            continue
        for node in ast.walk(module.tree):
            lineno = getattr(node, "lineno", 0)
            if isinstance(node, ast.Name) and node.id == LISTENING_MASTERY:
                violations.append(f"{module.path}:{lineno} names {LISTENING_MASTERY}")
            elif isinstance(node, ast.Attribute) and node.attr == LISTENING_MASTERY:
                violations.append(f"{module.path}:{lineno} accesses {LISTENING_MASTERY}")
            elif isinstance(node, ast.keyword) and node.arg == LISTENING_MASTERY:
                violations.append(f"{module.path}:{lineno} passes {LISTENING_MASTERY}")
        for value, lineno in _string_constants(module):
            if value == LISTENING_MASTERY:
                violations.append(f"{module.path}:{lineno} refers to {LISTENING_MASTERY}")
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G7 --- 트랜잭션 경계
# --------------------------------------------------------------------------


def test_g7_policy_modules_never_commit() -> None:
    """정책은 세션에 붙은 인스턴스를 바꿀 수 있지만 트랜잭션을 확정하지 않는다.

    요청 1개 = 세션 1개 = service 함수 안에서 commit 1회다.
    """
    violations = [
        f"{module.path}:{call.lineno} calls {_dotted(call.func)}"
        for module in _modules()
        if module.in_package("learning") or module.in_package("srs")
        for call, _ in _calls(module.tree)
        if _tail(_dotted(call.func), 1) in {"commit", "rollback"}
    ]
    assert violations == [], _report(violations)


def test_g7_api_commits_only_in_allowlisted_functions() -> None:
    """`api/study.py`는 commit하지 않는다. 트랜잭션은 `services/`가 닫는다."""
    violations = [
        f"{module.path}:{call.lineno} in {function} calls {_dotted(call.func)}"
        for module in _modules()
        if module.in_package("api")
        for call, function in _calls(module.tree)
        if _tail(_dotted(call.func), 1) in {"commit", "rollback"}
        and (module.path, function or "<module>") not in COMMIT_ALLOWLIST
    ]
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G8 / G9 --- 시각 주입
# --------------------------------------------------------------------------


def test_g8_the_clock_is_read_only_in_app_clock() -> None:
    """`app/clock.py` 말고는 아무도 시계를 직접 읽지 않는다. allowlist는 없다.

    예외를 하나 허용하는 순간 "요청 하나가 시각 하나를 본다"가 무너지고, 어긋남이
    **조용히** 통과한다.
    """
    violations = []
    for module in _modules():
        if module.path == CLOCK_MODULE:
            continue
        for node in ast.walk(module.tree):
            lineno = getattr(node, "lineno", 0)
            if isinstance(node, ast.Attribute):
                dotted = _dotted(node)
                if node.attr == "utcnow" or _tail(dotted, 2) in BANNED_CLOCK_READS:
                    violations.append(f"{module.path}:{lineno} reads {dotted or node.attr}")
        for imported, lineno in _imports(module):
            # `from time import time` 뒤에는 `time()`이 되어 attribute 검사를 빠져나간다.
            if imported in {"time.time", "time.time_ns"}:
                violations.append(f"{module.path}:{lineno} imports {imported}")
    assert violations == [], _report(violations)


def test_g9_utc_now_is_called_only_at_request_and_job_entrypoints() -> None:
    """시각은 진입점에서 한 번 읽고 그 아래로는 값으로 흐른다."""
    violations = []
    for module in _modules():
        if module.path.split("/")[0] in CLOCK_READ_PACKAGES:
            continue
        for call, function in _calls(module.tree):
            if _tail(_dotted(call.func), 1) != "utc_now":
                continue
            if (module.path, function or "<module>") in CLOCK_READ_ALLOWLIST:
                continue
            violations.append(f"{module.path}:{call.lineno} calls utc_now() in {function}")
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# G10 --- DB 시계
# --------------------------------------------------------------------------


def test_g10_no_sql_clock_anywhere_in_the_app() -> None:
    """`created_at`을 포함해 모든 시각을 애플리케이션이 채운다 (ADR-007).

    `server_default now()`를 안전망으로 남기면 값을 빠뜨린 INSERT가 조용히 DB
    wall clock으로 채워진다. 그것이 정확히 막으려는 실패다. 규칙이 하나이므로
    이 검사 하나로 전수 검증된다.
    """
    violations = []
    for module in _modules():
        for value, lineno in _string_constants(module):
            if SQL_CLOCK_PATTERN.search(value):
                violations.append(f"{module.path}:{lineno} contains SQL clock {value!r}")
        for call, _ in _calls(module.tree):
            dotted = _dotted(call.func)
            if _tail(dotted, 2) in SQL_CLOCK_CALL_SUFFIXES:
                violations.append(f"{module.path}:{call.lineno} calls {dotted}")
    assert violations == [], _report(violations)


# --------------------------------------------------------------------------
# guard 자체가 살아 있는지
# --------------------------------------------------------------------------


def test_the_guard_actually_sees_the_app() -> None:
    """빈 목록을 훑고 "위반 없음"이라 답하는 guard를 막는다."""
    paths = {module.path for module in _modules()}
    assert {"clock.py", "api/deps.py", "models/base.py"} <= paths
    assert len(_model_class_names()) >= 10
