"""auth service 단위 테스트 (DB 불필요)."""

from __future__ import annotations

import pytest

from app.services import auth


def test_hash_password_produces_argon2id_phc_string() -> None:
    assert auth.hash_password("correct horse").startswith("$argon2id$")


def test_hash_password_is_salted() -> None:
    # salt가 없으면 같은 password가 같은 해시가 되어 rainbow table이 성립한다.
    assert auth.hash_password("same") != auth.hash_password("same")


def test_verify_password_accepts_the_original_password() -> None:
    assert auth.verify_password(auth.hash_password("s3cret"), "s3cret") is True


def test_verify_password_rejects_a_wrong_password() -> None:
    assert auth.verify_password(auth.hash_password("s3cret"), "s3crat") is False


def test_verify_password_returns_false_for_a_malformed_hash() -> None:
    # 예외가 밖으로 새면 handler가 500을 내고 그 자체가 oracle이 된다.
    assert auth.verify_password("not-a-hash", "s3cret") is False


def test_hash_password_rejects_an_empty_password() -> None:
    with pytest.raises(ValueError, match="password"):
        auth.hash_password("")


def test_generate_session_token_is_unique_and_long_enough() -> None:
    tokens = {auth.generate_session_token() for _ in range(100)}
    assert len(tokens) == 100
    # 256bit를 urlsafe base64로 담으면 43자다.
    assert all(len(token) >= 43 for token in tokens)


def test_hash_token_is_deterministic_and_hides_the_token() -> None:
    token = auth.generate_session_token()
    assert auth.hash_token(token) == auth.hash_token(token)
    assert auth.hash_token(token) != token
    # SHA-256 hex.
    assert len(auth.hash_token(token)) == 64


def test_hash_token_differs_per_token() -> None:
    assert auth.hash_token("a") != auth.hash_token("b")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" JuNon ", "junon"),
        ("JUNON", "junon"),
        ("junon", "junon"),
        ("\tUser+Tag@Example.COM\n", "user+tag@example.com"),
    ],
)
def test_normalize_login_id(raw: str, expected: str) -> None:
    assert auth.normalize_login_id(raw) == expected


def test_dummy_password_hash_verifies_nothing_useful() -> None:
    # user enumeration 방지용. 아무 입력도 통과시키면 안 된다.
    assert auth.verify_password(auth.DUMMY_PASSWORD_HASH, "") is False
    assert auth.verify_password(auth.DUMMY_PASSWORD_HASH, "password") is False
