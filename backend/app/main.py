"""FastAPI 애플리케이션."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.router import ROOT_DEPENDENCIES, assert_fail_closed, install_routes
from app.settings import get_settings

# OpenAPI/docs는 private API 표면을 그대로 드러낸다. 05_API_SPEC.md에서 인증 없이
# 호출 가능한 경로는 /api/health 하나뿐이므로 개발 환경에서만 연다.
DOCS_APP_ENV = "development"

# scheme://host[:port] 만 허용한다. path/trailing slash/query가 있거나 "null"
# 같은 opaque origin이면 CORS 허용 목록으로 쓸 수 없다
# (spec/04_SECURITY_AND_DATA.md: 명시된 frontend origin만 허용).
_ORIGIN_PATTERN = re.compile(r"https?://[A-Za-z0-9.\-]+(?::\d{1,5})?")


def _validated_cors_origins(origins: list[str]) -> list[str]:
    for origin in origins:
        if origin == "*":
            raise ValueError(
                "CORS_ALLOW_ORIGINS must list explicit origins; wildcard is not allowed"
            )
        if not _ORIGIN_PATTERN.fullmatch(origin):
            raise ValueError(f"CORS_ALLOW_ORIGINS contains an invalid origin: {origin!r}")
    return origins


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """부팅 시점에 라우팅 표면을 한 번 더 전수 검사한다.

    `install_routes()`가 이미 검사하지만, 그 뒤에 `app.include_router()`를 덧붙이면
    그 검사를 지나쳐버린다. 여기서 다시 보면 라우트를 **언제** 붙였든 무인증
    경로를 가진 프로세스는 뜨지 못한다.
    """
    assert_fail_closed(app)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env == DOCS_APP_ENV

    app = FastAPI(
        title="Nihongo Context API",
        version=health.APP_VERSION,
        lifespan=_lifespan,
        # 상태 변경 요청의 Origin 검증은 앱 전체 기본값이다. 나중에 붙는 router가
        # 무엇이든 이 dependency를 상속한다 (app/api/router.py).
        dependencies=ROOT_DEPENDENCIES,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    origins = _validated_cors_origins(settings.cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    # 라우터 조립과 fail-closed 전수 검사는 app/api/router.py가 전담한다.
    install_routes(app)
    return app


app = create_app()
