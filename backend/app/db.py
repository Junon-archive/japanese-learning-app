"""동기 SQLAlchemy 엔진 (구현 지시서 §5)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings

_CONNECT_TIMEOUT_SECONDS = 3


@lru_cache(maxsize=4)
def _build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )


def get_engine() -> Engine | None:
    """DATABASE_URL이 설정되어 있지 않으면 None."""
    database_url = get_settings().database_url
    if not database_url:
        return None
    return _build_engine(database_url)


# bind는 요청 시점에 준다. DATABASE_URL이 없으면 엔진 자체가 없기 때문이다.
SessionLocal = sessionmaker(expire_on_commit=False)


def new_session() -> Session:
    """DATABASE_URL이 없으면 세션을 만들 수 없다."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return SessionLocal(bind=engine)
