"""문장 정규화와 유사도 (08_LLM_SPEC.md의 deterministic validation 11·12).

`sentences.normalized_hash`를 만드는 **유일한 자리**다. seed 적재 경로와 생성
경로가 서로 다른 해시를 쓰면 exact duplicate 검출이 예외 없이 조용히 실패한다
--- 중복이 통과할 뿐 아무 신호도 남지 않는다. 그래서 두 경로가 이 함수 하나를
부른다.

규칙은 seed 적재가 이미 기록한 값(NFKC -> 모든 공백 제거 -> sha256 hexdigest)을
그대로 승계한다. 바꾸면 적재된 seed 행의 해시가 새 해시와 맞지 않게 되어
duplicate 검출에서 사라진다.

DB를 모른다.
"""

from __future__ import annotations

import difflib
import hashlib
import unicodedata


def normalized_sentence_text(japanese: str) -> str:
    """NFKC 정규화 후 모든 공백을 제거한다.

    NFKC는 전각 영숫자와 기호를 반각으로 접어 같은 문장의 표기 변형을 하나로
    만든다(U+FF21 -> "A"). 일본어 문장은 공백을 의미 있게 쓰지 않으므로 공백
    유무만 다른 문장은 같은 문장으로 본다. `str.split()`은 전각 공백(U+3000)을
    포함한 모든 whitespace를 나눈다.
    """
    return "".join(unicodedata.normalize("NFKC", japanese).split())


def normalized_sentence_hash(japanese: str) -> str:
    """`sentences.normalized_hash`. exact duplicate 검출의 키다."""
    return hashlib.sha256(normalized_sentence_text(japanese).encode("utf-8")).hexdigest()


def similarity_ratio(a: str, b: str) -> float:
    """정규화한 두 문장의 유사도 0.0~1.0 (08_LLM_SPEC.md 12번의 "simple similarity").

    `difflib.SequenceMatcher`다. embedding이나 형태소 분석기를 쓰지 않는다 ---
    MVP 의무 범위 밖이고, 모델이나 사전 버전이 바뀌면 같은 문장 쌍의 판정이
    조용히 달라진다. 문자 단위 비교는 그 자리에서 재현된다.

    `autojunk=False`다. 기본값은 200자를 넘는 순간 자주 나오는 문자를 junk로
    빼기 시작해서 길이에 따라 판정 기준이 달라진다.
    """
    return difflib.SequenceMatcher(
        None, normalized_sentence_text(a), normalized_sentence_text(b), autojunk=False
    ).ratio()
