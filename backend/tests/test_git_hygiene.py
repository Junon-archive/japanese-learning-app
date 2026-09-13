"""Git에 들어가면 안 되는 것 (`13_ACCEPTANCE_CRITERIA.md`의 `secret frontend/Git 노출 없음`).

`.gitignore`는 **새 파일을 추가하지 않게** 할 뿐이다. `git add -f` 한 번이나, 무시 규칙이
생기기 전에 커밋된 파일은 그대로 추적된다. 그래서 무시 규칙이 아니라 **index**
(`git ls-files`, `git grep --cached`)를 본다. 작업 트리가 아니라 index인 이유: 커밋에
들어가는 것은 staged 내용이다.

## git이 없으면 skip이 아니라 실패다

이 저장소는 git 저장소이고 이 테스트가 도는 곳(개발 머신, CI의 checkout)에는 `.git`이
있다. 테스트가 돌지 않는 곳은 런타임 이미지인데, 그 이미지에는 `backend/tests`가 아예
들어가지 않는다(`.dockerignore`). 그러니 "git이 없다"는 환경의 정상 변형이 아니라 이
검사를 무력화하는 결함이고, skip으로 두면 초록으로 위장한다.

## 운영 정책 override 파일

여기서 검사하지 않는다. `14_CONFIGURATION.md`의 `production override`가 그 파일을
**저장소 작업 트리 밖**에 두도록 정했으므로 index에서 찾을 경로가 없다.

도메인 문자열 비노출은 여기서 보지 않는다. 실제 도메인을 테스트에 적는 순간 그 자체가
노출이다 --- 게이트에서 명령으로 확인한다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]

_GIT_TIMEOUT_SECONDS = 60

# API key 꼴의 토큰. `app/jobs/observability.py`의 redaction 패턴과 같은 모양이지만
# import하지 않는다 --- 구현 패턴을 좁히는 변경이 이 검사까지 함께 좁히면 안 된다.
KEY_SHAPE = r"sk-[A-Za-z0-9_-]{8,}"

# 키 모양이지만 **키가 아닌** 것. 파일과 문자열을 짝으로 적는다(파일 단위로 끄지 않는다 ---
# 그 파일에 진짜 키가 붙어도 잡혀야 한다). redaction 테스트가 "이 문자열이 로그에 안
# 나온다"를 보려고 쓰는 canary다.
#
# 문자열을 이어 붙여 적는 이유: 이 파일이 커밋되면 이 파일도 검사 대상이다. 한 덩어리로
# 적으면 이 목록이 스스로를 오탐으로 만든다.
_PREFIX = "sk-"
ALLOWED_KEY_SHAPED = frozenset(
    {
        ("backend/tests/test_jobs_worker.py", _PREFIX + "proj-ZZZLEAKCANARYZZZ0123456789"),
        ("backend/tests/test_jobs_worker.py", _PREFIX + "test-DO-NOT-LOG"),
        ("backend/tests/test_llm_provider.py", _PREFIX + "proj-ZZZLEAKCANARYZZZ0123456789"),
    }
)

# `.env.example`만 허용한다. 위치는 가리지 않는다(`.env`, `frontend/.env`, `.env.production` ...).
ENV_EXAMPLE = ".env.example"

# 백업 디렉터리에는 자리 표시 파일만 추적된다.
BACKUP_DIR = PurePosixPath("data/backups")
PLACEHOLDER = ".gitkeep"

# tunnel credential / origin cert / 실제 설정. 예시 파일(`config.example.yml`)은 허용이다.
# cloudflared는 `config.yml`과 `config.yaml`을 둘 다 읽으므로 둘 다 막는다.
CLOUDFLARED_DIR = PurePosixPath("infra/cloudflared")
CLOUDFLARED_REAL_CONFIGS = frozenset({"config.yml", "config.yaml"})
ORIGIN_CERT = "cert.pem"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None, "git이 PATH에 없다. 이 검사는 git 없이 통과할 수 없다(모듈 docstring)"
    return subprocess.run(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
        [git, "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def tracked_files() -> list[PurePosixPath]:
    completed = _git("ls-files", "-z")
    assert completed.returncode == 0, completed.stderr
    return [PurePosixPath(name) for name in completed.stdout.split("\0") if name]


def forbidden(path: PurePosixPath) -> str | None:
    """추적되면 안 되는 이유. 괜찮으면 None."""
    name = path.name
    if (name == ".env" or name.startswith(".env.")) and name != ENV_EXAMPLE:
        return "env 파일"
    if name.endswith(".dump"):
        return "DB dump"
    if path.is_relative_to(BACKUP_DIR) and path != BACKUP_DIR / PLACEHOLDER:
        return "backup 산출물"
    if name == ORIGIN_CERT:
        return "cloudflared origin cert"
    if path.parent == CLOUDFLARED_DIR and name.endswith(".json"):
        return "cloudflared tunnel credential"
    if path.parent == CLOUDFLARED_DIR and name in CLOUDFLARED_REAL_CONFIGS:
        return "cloudflared 실제 설정"
    return None


def test_the_repository_is_a_git_work_tree() -> None:
    """아래 검사들의 전제. 저장소 밖에서 돌면 `ls-files`가 빈 목록으로 통과할 수 있다."""
    completed = _git("rev-parse", "--show-toplevel")
    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()).resolve() == REPO_ROOT
    assert tracked_files(), "추적 파일이 하나도 없다"


def test_the_rules_recognize_what_they_are_meant_to_block() -> None:
    """규칙 자체의 표본. 이것이 없으면 조건을 잘못 적은 규칙이 빈 결과로 통과한다."""
    blocked = [
        ".env",
        "frontend/.env",
        ".env.production",
        "backup.dump",
        "data/backups/nihongo-20260101.dump",
        "data/backups/nihongo.sql.gz",
        "infra/cloudflared/0123abcd.json",
        "infra/cloudflared/cert.pem",
        "infra/cloudflared/config.yml",
        "infra/cloudflared/config.yaml",
    ]
    allowed = [
        ".env.example",
        "frontend/.env.example",
        "data/backups/.gitkeep",
        "infra/cloudflared/.gitkeep",
        "infra/cloudflared/config.example.yml",
        "backend/tests/test_env_isolation.py",
        "frontend/src/env.ts",
    ]
    assert [p for p in blocked if forbidden(PurePosixPath(p)) is None] == []
    assert [p for p in allowed if forbidden(PurePosixPath(p)) is not None] == []


def test_no_secret_or_data_file_is_tracked() -> None:
    offenders = sorted(
        f"{path} ({reason})" for path in tracked_files() if (reason := forbidden(path)) is not None
    )
    assert offenders == [], f"Git이 추적하면 안 되는 파일: {offenders}"


def key_shaped_in_index() -> set[tuple[str, str]]:
    """index의 텍스트 파일에 있는 `(경로, 키 모양 문자열)` 전부."""
    completed = _git("grep", "--cached", "-I", "--null", "-o", "-E", "-e", KEY_SHAPE)
    # git grep: 0 = 찾음, 1 = 없음, 그 밖 = 오류. 오류를 "없음"으로 읽으면 안 된다.
    assert completed.returncode in (0, 1), completed.stderr
    found: set[tuple[str, str]] = set()
    for line in completed.stdout.splitlines():
        path, _, token = line.partition("\0")
        assert re.fullmatch(KEY_SHAPE, token), f"git grep 출력 형식이 예상과 다르다: {path}"
        found.add((path, token))
    return found


def _masked(token: str) -> str:
    """실패 메시지에 키를 싣지 않는다. CI 로그가 그 자체로 유출 경로가 된다."""
    return f"{token[: len(_PREFIX)]}...({len(token)} chars)"


def test_no_key_shaped_string_is_staged() -> None:
    """index의 텍스트 파일 전체에서 `sk-` 키 모양을 찾는다. canary 목록 밖은 실패다."""
    offenders = sorted(
        f"{path}: {_masked(token)}" for path, token in key_shaped_in_index() - ALLOWED_KEY_SHAPED
    )
    assert offenders == [], "키 모양 문자열이 커밋 대상에 있다"


def test_the_allowed_key_shaped_strings_still_exist() -> None:
    """예외 목록이 썩지 않게 한다. canary가 사라졌는데 예외만 남으면 그 자리가 구멍이 된다."""
    stale = sorted(ALLOWED_KEY_SHAPED - key_shaped_in_index())
    assert stale == [], "쓰이지 않는 예외가 남아 있다"
