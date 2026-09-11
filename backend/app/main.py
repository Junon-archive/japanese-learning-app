"""FastAPI 애플리케이션."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
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


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env == DOCS_APP_ENV

    app = FastAPI(
        title="Nihongo Context API",
        version=health.APP_VERSION,
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

    app.include_router(health.router)
    return app


app = create_app()
