"""환경변수 전용 설정 (secret / 인프라). 학습 정책값은 `app.config`가 담당한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    # local | development | production. development에서만 /docs가 열린다.
    app_env: str = "local"
    database_url: str | None = None
    # 명시 origin만 허용한다. 비어 있으면 허용 origin 0개다. wildcard 금지.
    cors_allow_origins: str = ""
    nc_config_path: Path | None = None
    # auth session 수명(일). 학습 정책이 아니라 배포·보안 설정이므로 config YAML이
    # 아니라 환경변수다 (ADR-004). 만료 판정 자체는 auth_sessions.expires_at이 한다.
    auth_session_ttl_days: int = Field(default=30, gt=0)

    @field_validator("nc_config_path", mode="before")
    @classmethod
    def _empty_path_means_unset(cls, value: object) -> object:
        """빈 문자열은 "설정 안 함"이다.

        docker compose는 값이 없는 변수를 빈 문자열로 넘긴다(.env.example의
        `NC_CONFIG_PATH=`가 그렇다). 이걸 그대로 두면 `Path("")`가 `.`이 되어
        config 로딩이 디렉터리를 읽으려다 실패한다.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
