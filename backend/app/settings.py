"""환경변수 전용 설정 (secret / 인프라). 학습 정책값은 `app.config`가 담당한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    # local | development | production. development에서만 /docs가 열린다.
    app_env: str = "local"
    database_url: str | None = None
    # 명시 origin만 허용한다. 비어 있으면 허용 origin 0개다. wildcard 금지.
    cors_allow_origins: str = ""
    nc_config_path: Path | None = None

    @property
    def cors_origins(self) -> list[str]:
        """쉼표 구분 목록. 비어 있으면 허용 origin 0개.

        빈 항목을 조용히 버리지 않는다. 형식 검증은 `app.main`이 한다.
        """
        raw = self.cors_allow_origins.strip()
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
