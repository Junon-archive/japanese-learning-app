"""Provider seam (ADR-015의 `provider abstraction의 상한`, ADR-016).

네트워크를 쓰지 않고 DB도 쓰지 않는다. `make test-unit`에 들어간다.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

import app.llm.openai_provider  # noqa: F401  (import만으로 SDK가 올라오면 안 된다)
from app.llm.openai_provider import _token_count
from app.llm.provider import (
    LlmProvider,
    ProviderConfigError,
    ProviderRequest,
    ProviderResult,
    build_provider,
)
from tests.conftest import assert_no_provider_import, no_outbound_network

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

REQUEST = ProviderRequest(
    model="model-from-the-prompt-versions-row",
    instructions="static",
    context="dynamic",
    schema_name="sentence_batch",
    json_schema={"type": "object"},
)


class FakeProvider:
    """test double은 `app/`이 아니라 여기 있다 (ADR-015).

    production에서 쓰이지 않는 구현체를 앱 코드에 두지 않는다. Protocol은 주입
    지점의 타입 선언이지 단일 사용처를 위한 추상화가 아니다.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list[ProviderRequest] = []

    def generate_structured(self, request: ProviderRequest) -> ProviderResult:
        self.seen.append(request)
        return ProviderResult(text=self.text)


def test_the_protocol_is_implementable_outside_the_app() -> None:
    provider: LlmProvider = FakeProvider('{"sentences": []}')

    assert provider.generate_structured(REQUEST).text == '{"sentences": []}'


def test_missing_api_key_fails_fast() -> None:
    with pytest.raises(ProviderConfigError, match="API key"):
        build_provider("openai", api_key=None)

    with pytest.raises(ProviderConfigError, match="API key"):
        build_provider("openai", api_key="")


@pytest.mark.parametrize("name", ["", "stub", "anthropic", "OpenAI"])
def test_unknown_provider_names_are_refused(name: str) -> None:
    """`build_provider`는 아는 이름 하나만 만든다. registry도 plugin도 없다."""
    with pytest.raises(ProviderConfigError, match="unknown LLM provider"):
        build_provider(name, api_key="secret")


def test_building_a_provider_opens_no_socket_and_loads_no_sdk() -> None:
    """client 생성도 SDK import도 실제 호출 시점까지 미룬다.

    모듈 import만으로 SDK가 `sys.modules`에 올라오면
    `conftest.assert_no_provider_import()`가 아무것도 증명하지 못한다 --- 그
    단언이 보는 것이 정확히 `sys.modules`이기 때문이다.
    """
    assert_no_provider_import()

    with no_outbound_network():
        provider = build_provider("openai", api_key="secret")

    assert hasattr(provider, "generate_structured")
    assert "openai" not in sys.modules
    assert_no_provider_import()


def test_the_sdk_is_imported_inside_the_call_only() -> None:
    """`openai_provider` 모듈의 최상위에 SDK import가 없다."""
    source = (APP_ROOT / "llm" / "openai_provider.py").read_text(encoding="utf-8")
    top_level = [
        line for line in source.splitlines() if re.match(r"^(import|from)\s+openai\b", line)
    ]
    assert top_level == []
    assert re.search(r"^\s+from openai import ", source, re.MULTILINE) is not None


def test_no_model_name_is_hard_coded_anywhere_in_the_app() -> None:
    """모델명은 코드가 아니라 `prompt_versions.model`에서 온다 (원칙 8).

    provider abstraction이 아니라 **데이터**로 만족시키는 규칙이므로, 추상화가
    있는지가 아니라 문자열이 없는지를 본다.
    """
    pattern = re.compile(r"gpt-\d|claude-\d|gemini-\d|o\d-mini", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(APP_ROOT)}:{index}"
        for path in sorted(APP_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_a_result_without_usage_reports_unknown_tokens_not_zero() -> None:
    """0은 "호출했는데 토큰을 안 썼다"는 거짓 정보다. 모르는 것은 `None`이다.

    이 구분이 없으면 `daily_token_limit`은 값이 언제나 0이어서 영원히 발화하지 않는다
    (`14_CONFIGURATION.md`, `09_BACKGROUND_JOBS.md`의 `usage 기록과 일 경계`).
    """
    result = ProviderResult(text="{}")

    assert result.input_tokens is None
    assert result.output_tokens is None


@pytest.mark.parametrize(
    ("reported", "expected"),
    [(1234, 1234), (0, 0), (None, None), ("1234", None)],
)
def test_only_a_number_counts_as_a_token_count(reported: object, expected: int | None) -> None:
    """usage 블록의 유무는 provider 쪽 사정이다. 없거나 숫자가 아니면 "모른다"다.

    SDK를 import하지 않고 이 규칙만 본다 --- `openai`가 `sys.modules`에 올라오면
    `assert_no_provider_import()`가 아무것도 증명하지 못한다.
    """
    assert _token_count(reported) == expected


# --------------------------------------------------------------------------
# secret이 repr로 새지 않는다 (04_SECURITY_AND_DATA.md, 11_OBSERVABILITY.md)
# --------------------------------------------------------------------------

CANARY = "sk-proj-ZZZLEAKCANARYZZZ0123456789"


def test_the_provider_never_formats_its_key() -> None:
    """provider 객체는 worker 콜스택 전 구간의 프레임에 인자로 살아 있다.

    기본 dataclass `__repr__`이 키를 담고 있으면 `logger.warning("provider=%s", p)`
    한 줄이나 locals를 찍는 traceback 렌더러 하나로 키 전문이 컨테이너 로그에 영구
    기록된다. 그 경로를 닫는 것은 `field(repr=False)` 하나다.
    """
    with no_outbound_network():
        provider = build_provider("openai", api_key=CANARY)

    for rendered in (repr(provider), str(provider), f"{provider}", f"{provider!r}"):
        assert CANARY not in rendered, rendered
        assert "ZZZLEAKCANARY" not in rendered, rendered

    # 키를 지운 대가로 객체가 무엇인지 모르게 되지는 않았다.
    assert "OpenAiProvider" in repr(provider)


# credential을 뜻하는 필드 이름. `input_tokens`(= usage 집계)처럼 secret이 아닌
# 이름을 잡지 않도록 부분일치는 네 단어로 한정하고 나머지는 완전일치로 본다.
SECRET_SUBSTRINGS = ("api_key", "apikey", "secret", "password", "credential")
SECRET_EXACT = frozenset({"key", "token", "auth_token", "access_token", "bearer"})


def _is_secret_field(name: str) -> bool:
    lowered = name.lower()
    return lowered in SECRET_EXACT or any(part in lowered for part in SECRET_SUBSTRINGS)


def _is_dataclass_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr == "dataclass"
    return isinstance(target, ast.Name) and target.id == "dataclass"


def _repr_is_disabled(value: ast.expr | None) -> bool:
    """`field(repr=False)`로 선언됐는가."""
    if not isinstance(value, ast.Call):
        return False
    return any(
        keyword.arg == "repr"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in value.keywords
    )


def test_no_dataclass_in_the_app_puts_a_credential_in_its_repr() -> None:
    """`OpenAiProvider.api_key`와 같은 실수가 다음 dataclass에서 되풀이되지 않게 한다.

    개별 객체의 `repr`을 하나씩 확인하는 대신 선언을 본다 --- 새로 생기는 dataclass는
    테스트가 모르므로, 이름으로 secret임이 드러나는 필드는 전부 `repr=False`여야 한다.
    """
    offenders = [
        f"{path.relative_to(APP_ROOT)}:{statement.lineno} {node.name}.{statement.target.id}"
        for path in sorted(APP_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
        if any(_is_dataclass_decorator(decorator) for decorator in node.decorator_list)
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        if _is_secret_field(statement.target.id)
        if not _repr_is_disabled(statement.value)
    ]
    assert offenders == []
