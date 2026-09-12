"""문장 정규화와 유사도 (08_LLM_SPEC.md validation 11·12).

DB를 쓰지 않는다. 순수 함수이므로 integration 마커도 fixture도 없다.

이 파일의 핵심은 마지막 절이다: **seed 적재 경로와 생성 경로가 같은 문장에 같은
해시를 낸다.** 두 경로가 갈리면 exact duplicate 검출은 예외 없이 조용히 실패한다
--- 중복 문장이 그냥 통과하고 아무 신호도 남지 않는다.
"""

from __future__ import annotations

import pytest

from app.config import get_config
from app.normalization import (
    normalized_sentence_hash,
    normalized_sentence_text,
    similarity_ratio,
)

SENTENCE = "仕事を任せる。"


# --------------------------------------------------------------------------
# 정규화 규칙
# --------------------------------------------------------------------------


def test_the_hash_is_deterministic() -> None:
    assert normalized_sentence_hash(SENTENCE) == normalized_sentence_hash(SENTENCE)


def test_the_hash_is_sha256_hex() -> None:
    digest = normalized_sentence_hash(SENTENCE)

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_whitespace_does_not_change_the_hash() -> None:
    """일본어 문장은 공백을 의미 있게 쓰지 않는다. 전각 공백(U+3000)도 공백이다."""
    spaced = " 仕事を\t任せる。　"

    assert normalized_sentence_text(spaced) == SENTENCE
    assert normalized_sentence_hash(spaced) == normalized_sentence_hash(SENTENCE)


def test_nfkc_folds_fullwidth_forms() -> None:
    """NFKC를 지우면 빨개진다.

    전각 영숫자와 반각 영숫자는 같은 문장의 표기 변형이다. 접지 않으면 같은
    문장이 서로 다른 해시를 갖고 중복 검출을 그냥 빠져나간다.
    """
    fullwidth = "ＡＢＣ１２３のテスト"
    halfwidth = "ABC123のテスト"

    assert normalized_sentence_text(fullwidth) == halfwidth
    assert normalized_sentence_hash(fullwidth) == normalized_sentence_hash(halfwidth)


def test_different_sentences_get_different_hashes() -> None:
    assert normalized_sentence_hash(SENTENCE) != normalized_sentence_hash("仕事を任せた。")


def test_the_normalization_rule_is_pinned() -> None:
    """규칙(NFKC -> 공백 제거 -> sha256)이 바뀌면 빨개진다.

    이미 적재된 `sentences.normalized_hash`는 이 규칙으로 계산된 값이다. 규칙을
    바꾸면 그 행들은 새로 생성되는 문장과 영영 비교되지 않는다. 바꿔야 한다면
    기존 행을 재계산하는 migration이 함께 와야 한다.
    """
    assert normalized_sentence_hash("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert normalized_sentence_hash(SENTENCE) == (
        "f4a8c849f2910fd83cf717f14d5ad5b2239d6689aeea6c3dcf02cbc3a39fc115"
    )


# --------------------------------------------------------------------------
# 두 경로가 같은 해시를 낸다
# --------------------------------------------------------------------------


def test_seed_and_generation_paths_share_one_hash_function() -> None:
    """seed loader가 자기만의 정규화를 다시 갖지 않는다.

    Wave 2의 `seed_loader._normalized_hash`가 이 함수로 대체됐다. seed loader가
    해시를 직접 계산하는 순간(`hashlib`을 다시 import하는 순간) 두 경로가 갈리고
    duplicate 검출이 조용히 실패한다.

    실제로 적재된 행의 해시까지 확인하는 것은 `test_seed_loader.py`의
    `test_stored_normalized_hash_matches_the_shared_function`이다.
    """
    from app.services import seed_loader

    assert not hasattr(seed_loader, "_normalized_hash")
    assert seed_loader.__dict__["normalized_sentence_hash"] is normalized_sentence_hash
    assert "hashlib" not in seed_loader.__dict__


# --------------------------------------------------------------------------
# similarity
# --------------------------------------------------------------------------


def test_identical_sentences_score_one() -> None:
    assert similarity_ratio(SENTENCE, SENTENCE) == 1.0


def test_sentences_with_no_shared_characters_score_zero() -> None:
    assert similarity_ratio("仕事を任せる。", "ABCDEFG") == 0.0


def test_similarity_is_symmetric_and_bounded() -> None:
    a, b = "今日は気が乗らない。", "今日は気が乗る。"

    assert similarity_ratio(a, b) == similarity_ratio(b, a)
    assert 0.0 < similarity_ratio(a, b) < 1.0


def test_similarity_ignores_whitespace_like_the_hash() -> None:
    assert similarity_ratio(SENTENCE, " 仕事を 任せる。 ") == 1.0


def test_a_one_character_edit_lands_above_the_configured_threshold() -> None:
    """조사 하나만 바꾼 긴 문장은 near-duplicate로 잡힌다(threshold 위).

    짧은 문장에서는 한 글자만 달라도 비율이 크게 떨어진다 --- 7자 문장의 한 글자는
    14%다. 그래서 threshold 근처를 확인하려면 문장이 어느 정도 길어야 한다.
    """
    threshold = get_config().content.duplicate_similarity_threshold
    original = "今日は仕事を後輩に任せるつもりだったが、時間がなかった。"
    edited = "今日は仕事を後輩が任せるつもりだったが、時間がなかった。"

    assert similarity_ratio(original, edited) > threshold


def test_a_different_sentence_lands_below_the_configured_threshold() -> None:
    """주제가 다른 문장은 threshold 아래다. 아니면 정상 생성물이 중복으로 버려진다."""
    threshold = get_config().content.duplicate_similarity_threshold

    original = "今日は仕事を後輩に任せるつもりだったが、時間がなかった。"

    assert similarity_ratio(original, "昨日の映画はとても面白かった。") < threshold


@pytest.mark.parametrize("empty", ["", "   ", "　"])
def test_two_empty_sentences_score_one(empty: str) -> None:
    """`SequenceMatcher`는 빈 문자열 둘을 1.0으로 본다. 호출자가 알고 있어야 한다."""
    assert similarity_ratio(empty, "") == 1.0
