"""`LlmProvider`의 유일한 구현체 (ADR-015).

**openai SDK는 함수 안에서만 import한다.** 모듈 import만으로 SDK가
`sys.modules`에 올라오면 `conftest.assert_no_provider_import()`가 "request 경로가
provider를 끌어들이지 않았다"를 더 이상 증명하지 못한다 --- 그 단언이 보는 것이
정확히 `sys.modules`이기 때문이다.

모델명은 이 파일에 없다. `request.model`이 `prompt_versions.model`에서 온다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.provider import ProviderCallError, ProviderRequest, ProviderResult


@dataclass(frozen=True)
class OpenAiProvider:
    """호출 1회 = client 1회. connection 재사용 최적화는 하지 않는다.

    worker는 job 하나당 provider를 한 번 부르고, job은 초 단위로 드물다. 재사용을
    위해 client를 붙들면 그 수명 관리가 새로 생긴다.
    """

    # `repr=False`가 이 필드의 유일한 방어다. 이 객체는 `run_worker` -> `run_once` ->
    # `run_job` -> handler까지 **인자로** 흐르므로 worker 콜스택 전 구간의 프레임에
    # 살아 있다. 기본 `__repr__`이 키를 담고 있으면 누가 디버깅 중에 provider를
    # 포맷하거나(`logger.warning("provider=%s", provider)`) locals를 찍는 traceback
    # 렌더러가 의존성에 들어오는 순간, 키 전문이 컨테이너 로그에 영구 기록된다 ---
    # 로그는 메모리와 달리 남고 수집된다(04_SECURITY_AND_DATA.md).
    api_key: str = field(repr=False)

    def generate_structured(self, request: ProviderRequest) -> ProviderResult:
        from openai import OpenAI, OpenAIError

        client = OpenAI(api_key=self.api_key)
        try:
            response = client.responses.create(
                model=request.model,
                instructions=request.instructions,
                input=request.context,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "schema": request.json_schema,
                        "strict": True,
                    }
                },
            )
        except OpenAIError as error:
            raise ProviderCallError(f"provider call failed: {error}") from error

        text = response.output_text
        if not text:
            # structured output이 켜져 있어도 refusal이나 length 종료로 본문이 빌 수
            # 있다. 빈 문자열을 그대로 흘리면 파싱 단계가 schema_parse_failed로
            # 뭉뚱그린다.
            raise ProviderCallError("provider returned an empty response body")
        usage = getattr(response, "usage", None)
        return ProviderResult(
            text=text,
            input_tokens=_token_count(getattr(usage, "input_tokens", None)),
            output_tokens=_token_count(getattr(usage, "output_tokens", None)),
        )


def _token_count(value: object) -> int | None:
    """usage를 주지 않은 응답을 0으로 바꾸지 않는다. 모르면 `None`이다.

    `getattr`로 읽는 이유는 usage 블록의 유무가 provider 쪽 사정이기 때문이다. 필드가
    없거나 숫자가 아니면 "모른다"이고, 그 구분을 `ProviderResult`가 그대로 들고
    올라간다(0으로 뭉개면 `daily_token_limit`이 조용히 무력해진다).
    """
    return value if isinstance(value, int) else None
