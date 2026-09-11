"""테스트 환경 격리 목록이 설정 모델과 어긋나지 않는지 본다.

`conftest.clean_env`는 `Settings`가 읽는 환경변수를 전부 지워야 한다. 하나라도
빠지면 개발자 셸에 그 변수가 있을 때만 결과가 달라지는, 재현이 어려운 실패가 된다.
설정이 늘 때마다 손으로 두 목록을 맞추는 대신 모델에서 이름을 끌어와 비교한다.
"""

from __future__ import annotations

from pydantic.fields import FieldInfo

from app.settings import Settings

from .conftest import _ENV_VARS


def _env_name(field_name: str, field: FieldInfo, prefix: str) -> str:
    alias = field.validation_alias
    if alias is None:
        return f"{prefix}{field_name}".upper()
    assert isinstance(alias, str), (
        f"{field_name}: validation_alias가 문자열이 아니다. "
        "AliasChoices를 쓰기 시작했다면 이 헬퍼를 그에 맞게 고쳐야 한다."
    )
    return alias.upper()


def test_clean_env_clears_every_settings_field() -> None:
    prefix = Settings.model_config.get("env_prefix") or ""
    expected = {_env_name(name, field, prefix) for name, field in Settings.model_fields.items()}
    assert set(_ENV_VARS) == expected


def test_env_var_list_has_no_duplicates() -> None:
    assert len(set(_ENV_VARS)) == len(_ENV_VARS)
