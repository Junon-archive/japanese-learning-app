"""`LlmProvider` test double (ADR-016의 `개정`).

실제 키 없이 worker loop / claim / lease / validation / 저장을 **실제 코드로**
돌리는 수단이다. `LLM_PROVIDER = stub` 같은 환경변수 값은 존재하지 않는다 --- `stub`은
provenance 값(`factories.make_prompt_version`의 `provider="stub"`)이고, mock을 고르는
경로는 앱 코드에 없다. 이 객체가 들어가는 자리는 worker 진입점이 `build_provider()`의
결과를 넣는 그 인자다(`app/jobs/worker.py`의 `provider`).

`app/`에 두지 않는 이유는 ADR-015의 "production에서 쓰이지 않는 구현체를 앱 코드에
두지 않는다"다.

## `tests/llm_fixtures.py`와의 경계

이 파일은 **주입 지점과 호출 기록**만 담당한다. 응답 **본문**을 조립하는 것은
`tests/llm_fixtures.py`이고 그쪽 builder를 여기로 옮기지 않는다 --- 둘 다 본문을 만들
수 있게 되면 "이 응답이 deterministic validation을 통과하는가"의 기준이 두 곳으로
갈리고, 한쪽만 고친 fixture가 조용히 검증을 우회한다. 이 파일은 `json` / 스키마를
import하지 않는 것으로 그 경계를 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.provider import ProviderCallError, ProviderRequest, ProviderResult


@dataclass
class RecordingProvider:
    """받은 요청을 기록하고 미리 준비한 응답을 순서대로 돌려준다.

    `calls`가 비어 있다는 단언이 이 double의 주 용도다 --- cost ceiling에 걸린
    worker가 provider를 부르지 않았음을 "호출 0회"로 확인한다.
    """

    responses: list[str] = field(default_factory=list)
    error: Exception | None = None
    calls: list[ProviderRequest] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate_structured(self, request: ProviderRequest) -> ProviderResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise ProviderCallError("stub provider has no response left")
        return ProviderResult(text=self.responses.pop(0))
