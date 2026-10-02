"""언어별 `normalized_sentence_text` / `normalized_sentence_hash` (08_LLM_SPEC.md의
`normalized_hash`, ADR-024 결정 6).

`backend/tests/test_normalization.py`가 이미 **일본어 전용**(기본 `language="ja"`) 규칙을
핀으로 고정해 둔다 --- 그 테스트가 여전히 그대로 통과한다는 사실 자체가 ja 규칙이 한 글자도
바뀌지 않았다는 첫 증거다. 이 파일은 그 위에 다음을 더한다.

-   실제 `seed/ja/sentences.yaml` 전체에 대해 **이 모듈을 전혀 참조하지 않는 독립
    재구현**(NFKC -> 공백 전부 제거 -> sha256)과 비교해 ja 규칙을 다시 증명한다.
-   seed loader를 실제로 두 번(서로 다른 빈 DB) 돌려 같은 문장이 같은 해시를 내는지 본다.
-   영어 규칙(casefold, 공백 접기, 앞뒤 strip)을 고정한다.
-   언어 분기가 `app/normalization.py` 안에만 있다는 것(`casefold` 호출 위치)을 소스에서
    확인한다.
-   같은 원문이 ja/en 두 언어로 공존해도 해시가 다르다 --- corpus를 언어로 좁히는 근거다.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import get_config
from app.llm.duplicates import CorpusSentence, find_duplicate
from app.models.content import Sentence
from app.normalization import normalized_sentence_hash, normalized_sentence_text, similarity_ratio
from app.services.seed_loader import load_seed
from tests import db_support

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_SEED_JA = REPO_ROOT / "seed" / "ja"
APP_ROOT = REPO_ROOT / "backend" / "app"


# --------------------------------------------------------------------------
# 일본어 규칙 불변 (독립 재구현과 대조)
# --------------------------------------------------------------------------


def _reference_ja_hash(text: str) -> str:
    """`08_LLM_SPEC.md`의 ja 규칙을 `app.normalization`을 전혀 쓰지 않고 다시 구현한다.

    `normalized_sentence_hash`가 바뀌어도 이 함수는 바뀌지 않으므로, 둘이 계속 같다는
    것은 구현이 문서화된 규칙(NFKC -> 공백 전부 제거 -> sha256)에서 벗어나지 않았다는
    증거다.
    """
    return hashlib.sha256(
        "".join(unicodedata.normalize("NFKC", text).split()).encode("utf-8")
    ).hexdigest()


def test_ja_rule_matches_an_independent_reimplementation_for_the_real_corpus() -> None:
    entries = yaml.safe_load(REAL_SEED_JA.joinpath("sentences.yaml").read_text(encoding="utf-8"))
    texts = [entry["text"] for entry in entries]
    assert len(texts) > 100  # 실제 seed 규모가 작아지지 않았다는 안전장치

    for text in texts:
        assert normalized_sentence_hash(text) == _reference_ja_hash(text), text
        assert normalized_sentence_hash(text, "ja") == _reference_ja_hash(text), text


@pytest.mark.integration
def test_the_seed_loader_produces_the_same_hash_in_two_independent_runs(
    postgres_admin_dsn: URL,
) -> None:
    """seed loader를 두 번(서로 다른 빈 DB) 돌려 같은 문장이 같은 해시를 내는지 본다.

    고정 기대값을 테스트에 적지 않는다 --- 두 독립 실행의 결과를 서로 비교한다.
    """
    now = datetime.now(UTC)
    hashes: list[dict[str, str]] = []
    names = [f"nc_norm_lang_{suffix}" for suffix in ("a", "b")]
    try:
        for name in names:
            dsn = db_support.recreate_database(postgres_admin_dsn, name)
            db_support.alembic_upgrade(dsn)
            engine = sa.create_engine(dsn, poolclass=NullPool)
            try:
                with Session(engine) as session:
                    load_seed(session, REAL_SEED_JA, now=now, cfg=get_config())
                    rows = session.execute(
                        sa.select(Sentence.source_id, Sentence.normalized_hash)
                    ).all()
                    hashes.append({str(source_id): digest for source_id, digest in rows})
            finally:
                engine.dispose()
    finally:
        for name in names:
            db_support.drop_database(postgres_admin_dsn, name)

    first, second = hashes
    assert first  # 실제로 뭔가 적재됐다
    assert first == second


# --------------------------------------------------------------------------
# 영어 규칙
# --------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["Come on.", "come on.", "  come   on. "])
def test_en_casefold_and_whitespace_collapse_share_one_hash(variant: str) -> None:
    anchor = normalized_sentence_hash("Come on.", "en")
    assert normalized_sentence_hash(variant, "en") == anchor


def test_en_does_not_strip_all_whitespace() -> None:
    """영어는 단어 경계로 공백을 쓴다. 전부 지우면 서로 다른 문장이 같은 문자열로 접힌다."""
    assert normalized_sentence_hash("a nice house", "en") != normalized_sentence_hash(
        "anicehouse", "en"
    )


def test_en_text_is_casefolded_and_collapsed() -> None:
    assert normalized_sentence_text("  Come   ON. ", "en") == "come on."


def test_en_similarity_uses_the_same_normalization() -> None:
    assert similarity_ratio("Come on.", "  COME   on.  ", "en") == 1.0


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        normalized_sentence_text("x", "fr")


# --------------------------------------------------------------------------
# 분기는 normalized_sentence_text 안에만 있다
# --------------------------------------------------------------------------


def test_casefold_is_called_in_exactly_one_module() -> None:
    """언어 분기(특히 `casefold`)가 `app/normalization.py` 하나에만 있다.

    다른 곳(seed loader, worker validation, duplicates.py)이 각자 분기를 다시 구현하면
    규칙이 갈라진다 --- 호출부는 `language`를 전달만 해야 한다.
    """
    hits = [
        path for path in APP_ROOT.rglob("*.py") if ".casefold(" in path.read_text(encoding="utf-8")
    ]
    assert hits == [APP_ROOT / "normalization.py"]


# --------------------------------------------------------------------------
# duplicate corpus는 언어로 좁힌다
# --------------------------------------------------------------------------


def test_the_same_raw_text_hashes_differently_per_language() -> None:
    """언어가 다르면 같은 원문도 다른 해시를 낸다 --- 같은 문자열이 ja corpus와 en corpus에
    공존해도 서로를 중복으로 보지 않는 근거다(`08_LLM_SPEC.md`의 `duplicate 비교 corpus`).
    """
    # 전각 로마자 + 전각 공백: ja는 공백을 전부 지우고 접지 않지만(NFKC만), en은
    # casefold하고 공백을 하나로 접는다 --- 두 결과가 다른 문자열이 되어야 한다.
    text = "猫  cat"
    assert normalized_sentence_hash(text, "ja") != normalized_sentence_hash(text, "en")


def test_find_duplicate_does_not_cross_languages() -> None:
    """`find_duplicate`에 ja로 적재된 corpus를 주고 같은 원문을 en으로 검사하면 안 잡힌다.

    실제 DB 조회(`jobs/generate_sentence_batch.load_corpus`)는 애초에 언어로 좁혀서
    넘기지만, 이 함수 자체도 언어별 해시를 쓰므로 안전하다.
    """
    text = "猫  cat"
    ja_corpus = (
        CorpusSentence(
            sentence_id=1, text=text, normalized_hash=normalized_sentence_hash(text, "ja")
        ),
    )

    assert (
        find_duplicate(
            text, ja_corpus, similarity_threshold=0.90, skip_similarity=True, language="en"
        )
        is None
    )
