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


def test_probe_min_gap_presentations_is_loaded() -> None:
    # 06_LEARNING_ENGINE.md의 Probe Pacing이 강제하는 두 값 중 하나다.
    assert load_config(DEFAULT_CONFIG_FILE).learning.probe_min_gap_presentations == 3


def test_candidate_materialization_batch_size_is_loaded() -> None:
    # Ready Pool 생성 1회 실행당 role별 상한 (06_LEARNING_ENGINE.md).
    assert load_config(DEFAULT_CONFIG_FILE).learning.candidate_materialization_batch_size == 20


@pytest.mark.parametrize(
    ("key", "value"),
    [("probe_min_gap_presentations", 9), ("candidate_materialization_batch_size", 5)],
)
def test_pacing_keys_are_outside_every_ratio_sum(tmp_path: Path, key: str, value: int) -> None:
    # 비율 합 검증 대상은 review/new/exploration 세트와 backlog_* 세트뿐이다
    # (14_CONFIGURATION.md). 이 두 키를 바꿔도 합 검증에 걸리지 않아야 한다.
    raw = _raw_default()
    raw["learning"][key] = value
    assert getattr(load_config(_write(tmp_path, raw)).learning, key) == value


@pytest.mark.parametrize(
    "key", ["probe_min_gap_presentations", "candidate_materialization_batch_size"]
)
def test_pacing_keys_must_be_positive_integers(tmp_path: Path, key: str) -> None:
    # 14_CONFIGURATION.md: 둘 다 양의 정수다. 0이면 probe 간격 규칙이 사라지고
    # materialization이 아무것도 만들지 못한다.
    raw = _raw_default()
    raw["learning"][key] = 0
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


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


def test_worker_loop_and_batch_keys_are_loaded() -> None:
    # 14_CONFIGURATION.md의 jobs worker loop 키와 llm generation batch 키.
    config = load_config(DEFAULT_CONFIG_FILE)
    assert config.jobs.poll_interval_seconds == 5
    assert config.jobs.claim_lease_seconds == 300
    assert config.jobs.heartbeat_interval_seconds == 30
    assert config.jobs.heartbeat_stale_seconds == 120
    assert config.llm.sentences_per_batch == 5
    assert config.llm.avoid_examples_per_item == 3


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("jobs", "poll_interval_seconds"),
        ("jobs", "claim_lease_seconds"),
        ("jobs", "heartbeat_interval_seconds"),
        ("jobs", "heartbeat_stale_seconds"),
        ("llm", "sentences_per_batch"),
        ("llm", "avoid_examples_per_item"),
    ],
)
def test_worker_loop_and_batch_keys_must_be_positive_integers(
    tmp_path: Path, section: str, key: str
) -> None:
    # 14_CONFIGURATION.md: 여섯 키 모두 양의 정수다.
    raw = _raw_default()
    raw[section][key] = 0
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


@pytest.mark.parametrize("stale", [30, 29])
def test_heartbeat_stale_must_exceed_the_write_interval(tmp_path: Path, stale: int) -> None:
    """14_CONFIGURATION.md / 09_BACKGROUND_JOBS.md: stale > interval.

    같거나 작으면 정상 동작 중인 worker가 주기적으로 stale로 보고된다 --- heartbeat가
    말하려던 것과 정반대의 신호가 된다.
    """
    raw = _raw_default()
    raw["jobs"]["heartbeat_interval_seconds"] = 30
    raw["jobs"]["heartbeat_stale_seconds"] = stale
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, raw))


def test_worker_loop_and_batch_keys_are_outside_every_ratio_sum(tmp_path: Path) -> None:
    # 비율 합 검증 대상은 learning의 두 세트뿐이다 (14_CONFIGURATION.md:
    # "srs, session, user, content, jobs, llm 섹션의 키는 비율 합 검증 대상이 아니다").
    raw = _raw_default()
    raw["jobs"]["poll_interval_seconds"] = 1
    raw["jobs"]["claim_lease_seconds"] = 60
    raw["llm"]["sentences_per_batch"] = 1
    config = load_config(_write(tmp_path, raw))
    assert config.jobs.poll_interval_seconds == 1
    assert config.jobs.claim_lease_seconds == 60
    assert config.llm.sentences_per_batch == 1


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
