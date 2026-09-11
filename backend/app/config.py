"""학습 정책 설정 로더.

정책값은 `config/default.yaml`에만 존재한다. 코드 기본값을 두지 않는다
(AGENTS.md #9, 구현 지시서 §1). secret/인프라 값은 `app.settings`가 담당한다.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.settings import get_settings

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"

_RATIO_SUM_TOLERANCE = 1e-6

_SECTION_CONFIG = ConfigDict(extra="forbid", frozen=True)


class ConfigError(ValueError):
    """설정 파일을 읽거나 검증할 수 없다."""


class LearningConfig(BaseModel):
    model_config = _SECTION_CONFIG

    default_session_minutes: int = Field(...)
    extra_session_minutes: int = Field(...)
    review_ratio: float = Field(...)
    new_ratio: float = Field(...)
    exploration_ratio: float = Field(...)
    preferred_new_items_per_sentence: int = Field(...)
    max_new_items_per_sentence: int = Field(...)
    minimum_meaningful_exposures: int = Field(...)
    mastery_probe_target_per_session_min: int = Field(...)
    mastery_probe_target_per_session_max: int = Field(...)
    mastery_ema_alpha: float = Field(...)
    passive_review_deferral_hours: int = Field(...)
    passive_exposures_before_probe: int = Field(...)
    probe_skip_cooldown_days: int = Field(...)
    backlog_threshold: int = Field(...)
    backlog_review_ratio: float = Field(...)
    backlog_new_ratio: float = Field(...)
    backlog_exploration_ratio: float = Field(...)
    # 0.0이면 최소 지분 규칙이 꺼진다 (14_CONFIGURATION.md).
    reinforcement_min_share_of_review: float = Field(..., ge=0.0, le=1.0)
    exploration_recent_days: int = Field(...)

    @model_validator(mode="after")
    def _check_category_ratio_sums(self) -> LearningConfig:
        # backlog 세트는 같은 deficit 계산에 그대로 들어가므로 같은 합 검증을
        # 받는다 (14_CONFIGURATION.md).
        for prefix, total in (
            ("", self.review_ratio + self.new_ratio + self.exploration_ratio),
            (
                "backlog_",
                self.backlog_review_ratio + self.backlog_new_ratio + self.backlog_exploration_ratio,
            ),
        ):
            if not math.isclose(total, 1.0, abs_tol=_RATIO_SUM_TOLERANCE):
                raise ValueError(
                    f"learning.{prefix}review_ratio + {prefix}new_ratio + "
                    f"{prefix}exploration_ratio must sum to 1.0, got {total}"
                )
        return self


class SrsConfig(BaseModel):
    model_config = _SECTION_CONFIG

    fsrs_enable_fuzzing: bool = Field(...)


class SessionConfig(BaseModel):
    model_config = _SECTION_CONFIG

    study_session_idle_timeout_minutes: int = Field(...)
    active_time_idle_gap_seconds: int = Field(...)


class UserConfig(BaseModel):
    model_config = _SECTION_CONFIG

    user_timezone: str = Field(...)


class ContentConfig(BaseModel):
    model_config = _SECTION_CONFIG

    translation_default_visible: bool = Field(...)
    reading_default_visible: bool = Field(...)
    max_sentence_length_chars: int = Field(...)
    duplicate_similarity_threshold: float = Field(...)


class JobsConfig(BaseModel):
    model_config = _SECTION_CONFIG

    max_job_attempts: int = Field(...)
    retry_backoff_base_seconds: int = Field(...)


class LlmConfig(BaseModel):
    model_config = _SECTION_CONFIG

    public_demo_generation_enabled: bool = Field(...)
    daily_request_limit: int | None = Field(...)
    daily_token_limit: int | None = Field(...)

    @model_validator(mode="after")
    def _reject_public_demo_generation(self) -> LlmConfig:
        # Public Demo는 static frontend fixture다. provider/worker를 쓰지 않는다
        # (14_CONFIGURATION.md, 구현 지시서 불변식 8).
        if self.public_demo_generation_enabled:
            raise ValueError("llm.public_demo_generation_enabled must stay false")
        return self


class AppConfig(BaseModel):
    model_config = _SECTION_CONFIG

    learning: LearningConfig = Field(...)
    srs: SrsConfig = Field(...)
    session: SessionConfig = Field(...)
    user: UserConfig = Field(...)
    content: ContentConfig = Field(...)
    jobs: JobsConfig = Field(...)
    llm: LlmConfig = Field(...)


def load_config(path: Path | None = None) -> AppConfig:
    """YAML 설정 파일을 읽어 검증한다. 실패는 항상 ConfigError다."""
    config_path = DEFAULT_CONFIG_PATH if path is None else path
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"config file cannot be read: {config_path}") from exc
    try:
        raw: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must contain a YAML mapping: {config_path}")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config file {config_path}: {exc}") from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config(get_settings().nc_config_path)
