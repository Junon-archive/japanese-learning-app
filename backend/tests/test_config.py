from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import AppConfig, ConfigError, get_config, load_config

from .conftest import REPO_ROOT

DEFAULT_CONFIG_FILE = REPO_ROOT / "config" / "default.yaml"


def _raw_default() -> dict[str, Any]:
    loaded: Any = yaml.safe_load(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_default_config_file_loads() -> None:
    config = load_config(DEFAULT_CONFIG_FILE)
    assert isinstance(config, AppConfig)


def test_every_key_in_default_config_is_modelled() -> None:
    raw = _raw_default()
    dumped = load_config(DEFAULT_CONFIG_FILE).model_dump()
    assert set(raw) == {"learning", "srs", "session", "user", "content", "jobs", "llm"}
    assert set(raw) == set(dumped)
    for section, values in raw.items():
        assert set(values) == set(dumped[section]), section


def test_approved_acceptance_values() -> None:
    learning = load_config(DEFAULT_CONFIG_FILE).learning
    assert learning.max_new_items_per_sentence == 2
    assert learning.minimum_meaningful_exposures == 5
    assert learning.default_session_minutes == 12


def test_category_ratio_sum_uses_float_tolerance() -> None:
    learning = load_config(DEFAULT_CONFIG_FILE).learning
    total = learning.review_ratio + learning.new_ratio + learning.exploration_ratio
    # 0.70 + 0.20 + 0.10은 부동소수점으로 정확히 1.0이 아니다.
    assert total != 1.0
    assert abs(total - 1.0) < 1e-6


def test_invalid_category_ratio_sum_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["learning"]["new_ratio"] = 0.30
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_reinforcement_min_share_is_outside_every_ratio_sum(tmp_path: Path) -> None:
    # review 슬롯 *내부* 지분이므로 어느 합 검증에도 들어가지 않는다
    # (14_CONFIGURATION.md).
    raw = _raw_default()
    raw["learning"]["reinforcement_min_share_of_review"] = 0.9
    assert load_config(_write(tmp_path, raw)).learning.reinforcement_min_share_of_review == 0.9


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_reinforcement_min_share_outside_allowed_range_is_rejected(
    tmp_path: Path, value: float
) -> None:
    raw = _raw_default()
    raw["learning"]["reinforcement_min_share_of_review"] = value
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_reinforcement_min_share_may_be_zero(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["learning"]["reinforcement_min_share_of_review"] = 0.0
    assert load_config(_write(tmp_path, raw)).learning.reinforcement_min_share_of_review == 0.0


def test_exploration_recent_days_is_loaded() -> None:
    assert load_config(DEFAULT_CONFIG_FILE).learning.exploration_recent_days == 14


def test_fsrs_fuzzing_is_disabled() -> None:
    # ADR-003: 테스트 재현성을 위해 끈다.
    assert load_config(DEFAULT_CONFIG_FILE).srs.fsrs_enable_fuzzing is False


def test_invalid_backlog_ratio_sum_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["learning"]["backlog_new_ratio"] = 0.30
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["learning"]["unexpected_policy_key"] = 1
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["unexpected_section"] = {"a": 1}
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_missing_key_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    del raw["learning"]["minimum_meaningful_exposures"]
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_missing_section_is_rejected(tmp_path: Path) -> None:
    raw = _raw_default()
    del raw["jobs"]
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_null_llm_limits_load_as_none() -> None:
    llm = load_config(DEFAULT_CONFIG_FILE).llm
    assert llm.daily_request_limit is None
    assert llm.daily_token_limit is None


def test_public_demo_generation_cannot_be_enabled(tmp_path: Path) -> None:
    raw = _raw_default()
    raw["llm"]["public_demo_generation_enabled"] = True
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_missing_config_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_default_config_contains_no_secret() -> None:
    text = DEFAULT_CONFIG_FILE.read_text(encoding="utf-8").lower()
    for needle in ("password", "secret", "api_key", "apikey", "sk-", "://"):
        assert needle not in text, needle


def test_get_config_honours_nc_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = _raw_default()
    raw["learning"]["default_session_minutes"] = 7
    monkeypatch.setenv("NC_CONFIG_PATH", str(_write(tmp_path, raw)))
    assert get_config().learning.default_session_minutes == 7
