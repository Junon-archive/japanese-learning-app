"""LLM provider seam (ADR-015의 `provider abstraction의 상한`).

상한은 **Protocol 1개 + 메서드 1개 + `build_provider()` 1개 + 구현체 1개**다.
registry / plugin / capability negotiation / model router를 만들지 않는다.

- **모델명과 provider명이 이 파일에 없다.** 둘 다 `prompt_versions` 행에서 오고
  호출자가 문자열로 넘긴다(`08_LLM_SPEC.md`의 `Provider 선택과 model 출처`).
  `build_provider`는 그 문자열을 client로 바꾸는 유일한 지점이다.
- **`StubProvider`를 여기 두지 않는다**(ADR-015). production에서 쓰이지 않는
  구현체는 앱 코드가 아니라 `backend/tests/`의 test double이다. Protocol은 그
  주입 지점의 타입 선언이다.
- provider는 retry하지 않고 비용도 집계하지 않는다. 둘 다 job queue 소관이다.

DB를 모른다(G11(a)).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# 이 이름 하나만 `build_provider`가 안다. 모델명이 아니라 **구현체 이름**이며
# `prompt_versions.provider`와 `provenance_json.provider`가 같은 값을 쓴다.
OPENAI = "openai"


class LlmError(Exception):
    """`app/llm/`이 내는 모든 오류의 뿌리."""


class ProviderConfigError(LlmError):
    """provider를 만들 수 없다.

    재시도해도 결과가 같으므로 job queue는 이것을 `dead_letter`로 다룬다
    (`09_BACKGROUND_JOBS.md`의 `failed와 dead_letter의 경계`).
    """


class ProviderCallError(LlmError):
    """provider 호출이 실패했다. 재시도하면 달라질 수 있다."""


@dataclass(frozen=True)
class ProviderRequest:
    """한 번의 structured output 호출.

    `instructions`(정적)와 `context`(동적)를 나눠 두는 이유는
    `06_LLM_ENGINEERING_PRINCIPLES.md` 7번의 배치 규칙이다. caching 최적화 자체는
    MVP 의무가 아니므로 여기서 하는 일은 자리를 나누는 것까지다.
    """

    model: str
    instructions: str
    context: str
    schema_name: str
    json_schema: dict[str, Any]


@dataclass(frozen=True)
class ProviderResult:
    """응답 본문 문자열과 그 호출의 token 사용량.

    파싱과 검증은 provider 밖(`tasks` / `validation`)이 한다.

    token 수는 **`None`일 수 있다.** provider가 usage를 주지 않는 호출이 있고
    (`11_OBSERVABILITY.md`의 `estimated cost if available`과 같은 성질), 그때 0을 적으면
    "호출했는데 토큰을 안 썼다"는 거짓 정보가 된다. 모르는 것은 `None`이고, 그 값을
    어떻게 다룰지는 비용을 집계하는 쪽(`app/jobs/queue.py`)이 정한다 --- provider는
    비용을 집계하지 않는다(ADR-015).
    """

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LlmProvider(Protocol):
    def generate_structured(self, request: ProviderRequest) -> ProviderResult: ...


def build_provider(name: str, *, api_key: str | None) -> LlmProvider:
    """구현체 이름과 secret을 받아 client를 만든다. 모르는 이름은 거절한다.

    `api_key`는 **인자로 받는다.** worker 진입점이 환경변수를 읽어 값으로 넘기고
    (`04_SECURITY_AND_DATA.md`의 `LLM provider 자격증명`), 이 계층은 환경을 읽지
    않는다 --- 그래야 테스트가 값을 주입할 수 있고 API 프로세스가 이 경로를 부를
    이유가 영영 없다.

    openai SDK는 여기서도 import하지 않는다. `app.llm.provider`를 import하는 것만
    으로 SDK가 `sys.modules`에 올라오면 `conftest.assert_no_provider_import()`가
    아무것도 못 잡는다.
    """
    if name != OPENAI:
        raise ProviderConfigError(f"unknown LLM provider {name!r}; supported: {OPENAI!r}")
    if not api_key:
        raise ProviderConfigError(f"provider {name!r} requires an API key")

    from app.llm.openai_provider import OpenAiProvider

    return OpenAiProvider(api_key=api_key)
