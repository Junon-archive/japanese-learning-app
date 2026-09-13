"""브라우저 e2e가 demo를 단정할 때 쓰는 값. **숫자를 테스트에 복사하지 않는다.**

-   문장 데이터와 fixture 식별자는 커밋된 생성 파일에서 `scripts/build_demo_fixture.py`의 `read_fixture`로 읽는다.
-   진행 간격은 `frontend/src/demo/constants.ts`의 두 상수에서 읽는다(`03_UI_UX_SPEC.md`의 `Demo` > `진행 규칙`:
    "테스트는 숫자 대신 이 상수를 참조한다").
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_SCRIPT = REPO_ROOT / "scripts" / "build_demo_fixture.py"
FIXTURE_DATA = REPO_ROOT / "frontend" / "src" / "demo" / "fixture-data.ts"
CONSTANTS = REPO_ROOT / "frontend" / "src" / "demo" / "constants.ts"

DEMO_KEY = "nc.demo.v1"
FURIGANA_KEY = "nc.furigana.v1"


def _fixture_script() -> ModuleType:
    name = "build_demo_fixture"
    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(name, FIXTURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_fixture() -> tuple[str, list[dict[str, Any]]]:
    """(fixture 식별자, 문장 목록). 문장은 `DemoSentence` 모양의 dict다."""
    fixture_id, sentences = _fixture_script().read_fixture(FIXTURE_DATA)
    assert isinstance(fixture_id, str)
    assert isinstance(sentences, list)
    assert sentences, "demo fixture가 비었다(전제)"
    return fixture_id, sentences


def demo_constant(name: str) -> int:
    """`constants.ts`의 `export const <name> = <정수>`."""
    source = CONSTANTS.read_text(encoding="utf-8")
    match = re.search(rf"^export const {re.escape(name)} = (\d+)$", source, re.MULTILINE)
    assert match is not None, f"{name}이(가) {CONSTANTS}에 없다"
    return int(match.group(1))


def ruby_pairs(sentence: dict[str, Any]) -> list[tuple[str, str]]:
    """문장 segment의 ruby 중 읽기가 있는 (밑글자, 읽기). DOM의 `<ruby>` 순서와 같다."""
    return [
        (part["text"], part["reading"])
        for segment in sentence["presentation"]["render_segments"]
        for part in segment["ruby"]
        if part["reading"] is not None
    ]


def expression_of(sentence: dict[str, Any], learning_item_id: int) -> str:
    """그 표현이 그 문장에서 차지한 segment text를 이은 것(probe의 표현 표기)."""
    ids = {
        item["sentence_item_id"]
        for item in sentence["presentation"]["tappable_items"]
        if item["learning_item_id"] == learning_item_id
    }
    return "".join(
        segment["text"]
        for segment in sentence["presentation"]["render_segments"]
        if segment["sentence_item_id"] in ids
    )
