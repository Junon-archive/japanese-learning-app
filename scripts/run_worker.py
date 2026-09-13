#!/usr/bin/env python
"""worker 프로세스 진입점.

    export DATABASE_URL=...
    export LLM_PROVIDER=openai
    export LLM_API_KEY=...
    uv run python scripts/run_worker.py

**환경변수를 읽는 유일한 지점이다**(`spec/04_SECURITY_AND_DATA.md`의
`LLM provider 자격증명`, ADR-016의 `개정`). 여기서 `build_provider()`를 한 번 불러
만든 client를 worker loop에 인자로 넘긴다. `app/llm/`도 `app/jobs/`도 환경을 읽지
않으므로 테스트는 같은 인자에 test double을 넣는다.

fail-closed 부팅 검사는 셋이고 **예외를 잡지 않는다.** 조용히 다른 값으로
승격시키면 운영자가 모르는 사이에 유료 호출 경로가 열리거나, 반대로 아무것도 하지
않는 worker가 몇 주 동안 살아 있게 된다.

``` text
LLM_PROVIDER 미설정 / 허용값(openai) 아님        -> ProviderConfigError
LLM_PROVIDER = openai 인데 LLM_API_KEY 없음      -> ProviderConfigError
task 3종 중 active prompt_versions 행이 없는 것  -> WorkerStartupError
후리가나 분석기·사전을 적재하지 못함            -> ImportError 등 (ADR-021 결정 4)
```

분석기 부재를 문장별 `ruby_json = NULL`로 흡수하지 않는다. 그것은 배포 결함이고, 흡수하면 worker가
후리가나 없는 문장만 쌓아도 아무도 모른다. 문장 하나의 계산 실패는 `jobs/persistence.py`가 NULL로
두고 `ruby.failed`를 남긴다.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 이 프로젝트는 설치되는 패키지가 아니다(Makefile의 run도 --app-dir backend를 쓴다).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_config  # noqa: E402
from app.db import new_session  # noqa: E402
from app.furigana import load_analyzer  # noqa: E402

# worker loop는 runner를 **인자로** 받는다(provider와 같은 주입 지점). 그래서 그 모듈을
# 아는 것은 이 진입점 하나이고, `app/jobs/worker.py`는 runner를 import하지 않는다.
from app.jobs.runner import run_job  # noqa: E402
from app.jobs.worker import (  # noqa: E402
    ShutdownSignal,
    install_signal_handlers,
    run_worker,
    warn_if_cost_guard_disabled,
)
from app.llm.provider import build_provider  # noqa: E402

# `logging.LogRecord`가 기본으로 갖는 속성 이름. 여기 없는 것이 `extra=`로 붙은 값이다.
# 이름을 손으로 나열하지 않는다 --- 파이썬 버전이 속성을 추가하면(3.12의 `taskName`)
# 그것이 지표처럼 출력된다.
_STANDARD_LOG_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | frozenset({"message", "asctime", "taskName"})


class KeyValueFormatter(logging.Formatter):
    """`extra=`로 붙은 구조화 field를 `key=value`로 덧붙인다.

    기본 formatter는 그것들을 **버린다.** 그러면 `job.claimed` 같은 event 이름만 남고
    11_OBSERVABILITY.md가 요구하는 숫자(job/token/pool 크기)가 어디에도 나타나지
    않는다. JSON 로깅 스택을 들이는 것은 MVP 범위가 아니므로 여기까지만 한다.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = " ".join(
            f"{name}={value}"
            for name, value in record.__dict__.items()
            if name not in _STANDARD_LOG_FIELDS
        )
        return f"{base} {extras}" if extras else base


def configure_logging() -> None:
    """로깅 설정은 **프로세스 진입점**이 한다. 라이브러리 코드는 handler를 붙이지 않는다.

    INFO까지 올리는 이유: worker가 남기는 지표가 대부분 INFO이고, 기본값(WARNING)으로
    두면 job이 성공하는 동안 로그가 한 줄도 나오지 않는다.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main() -> int:
    provider_name = os.environ.get("LLM_PROVIDER", "")
    api_key = os.environ.get("LLM_API_KEY") or None
    # 값이 없거나 openai가 아니거나 키가 없으면 여기서 예외로 끝난다. 기본값은 없다.
    provider = build_provider(provider_name, api_key=api_key)
    # 사전을 부팅에서 한 번 적재한다. 실패하면 예외 그대로 끝난다(fail-closed).
    load_analyzer()

    cfg = get_config()
    warn_if_cost_guard_disabled(cfg, api_key_configured=api_key is not None)

    shutdown = ShutdownSignal()
    install_signal_handlers(shutdown)

    run_worker(
        session_factory=new_session,
        provider=provider,
        run_job=run_job,
        cfg=cfg,
        shutdown=shutdown,
    )
    return 0


if __name__ == "__main__":
    # `main()` 안에서 부르지 않는다. 그러면 이 파일을 적재해 `main()`을 부르는 테스트가
    # root handler를 갈아치우고(`force=True`) pytest의 로그 캡처를 닫아버린다.
    configure_logging()
    raise SystemExit(main())
