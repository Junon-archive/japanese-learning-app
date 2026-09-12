"""FastAPI 애플리케이션."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health
from app.api.router import ROOT_DEPENDENCIES, assert_fail_closed, install_routes
from app.settings import get_settings

# OpenAPI/docs는 private API 표면을 그대로 드러낸다. 05_API_SPEC.md에서 인증 없이
# 호출 가능한 경로는 /api/health 하나뿐이므로 개발 환경에서만 연다.
DOCS_APP_ENV = "development"

# 422 본문에서 지우는 pydantic 오류 키.
#
# `input`은 **거부된 값 그 자체**다. FastAPI 기본 handler는 그것을 그대로 반향하고,
# pydantic은 필드 하나가 어긋나면 body 전체를 `input`으로 싣는다
# (`{"type":"missing","loc":["body","login_id"],"input":{...제출한 body 전부...}}`).
# 즉 client가 `loginId`처럼 이름 하나만 틀려도, 또는 body를 배열로 감싸도, 평문
# password가 응답 본문에 실려 나간다. 그 본문은 터널/프록시 로그와 브라우저 HAR에
# 남는다. `ctx`도 값에서 파생된 내용을 담을 수 있어 같이 지운다.
#
# `loc`/`type`/`msg`는 남긴다. **무엇이** 잘못됐는지는 진단에 필요하고, 그 셋은
# 스키마 선언에서 나온 정보라 client가 보낸 값을 포함하지 않는다.
_ECHOED_ERROR_KEYS = frozenset({"input", "ctx"})

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


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """제출된 값을 지운 422. 상태 코드와 `{"detail": [...]}` 모양은 기본 동작 그대로다.

    app 레벨 handler라 **모든 endpoint**에 걸린다. endpoint마다 붙이는 방식이면
    하나를 빠뜨린 곳이 그대로 유출 경로다.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    sanitized: list[dict[str, Any]] = [
        {key: value for key, value in error.items() if key not in _ECHOED_ERROR_KEYS}
        for error in errors
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": sanitized}),
    )


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

    app.add_exception_handler(RequestValidationError, _validation_error_handler)

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
