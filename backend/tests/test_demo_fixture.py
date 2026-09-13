"""`scripts/build_demo_fixture.py` --- Public Demo fixture (12_TEST_PLAN.md `Fixture (demo, 불변식 20)`).

규칙의 canonical은 `mvp-01-core/03_UI_UX_SPEC.md`의 `Demo`의 `fixture`다. DB를 쓰지 않는다.

-   커밋된 fixture에 대한 단정(재생성 일치, ruby 일치, 출처)은 저장소의 `seed/`를 직접 YAML로 읽어
    스크립트의 파서를 거치지 않고 대조한다.
-   선택 규칙은 작은 합성 입력으로 `select_sentences`를 직접 부르고, 검사·출력은 합성 seed 디렉터리로
    `main`을 부른다.
"""

from __future__ import annotations

import importlib.util
import itertools
import re
import shutil
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from app.config import load_config
from app.furigana import RubyItem, compute_ruby
from app.render import ItemSpan, SpanRef, build_render_segments
from app.schemas.study import ExplanationResponse, PresentationPayload

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SEED_DIR = REPO_ROOT / "seed"
COMMITTED = REPO_ROOT / "frontend" / "src" / "demo" / "fixture-data.ts"
CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"

EXIT_OK = 0
EXIT_FAILED = 2

FIXTURE_LINE = re.compile(
    r"^fixture: sentences=(\d+)/(\d+) covered_items=(\d+)/(\d+) excluded=(\d+) "
    r"uncovered=(\d+) id=([0-9a-f]{16})$",
    re.MULTILINE,
)


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixture_script() -> ModuleType:
    return load_script("build_demo_fixture")


def _max_tappable() -> int:
    return load_config(CONFIG_PATH).learning.max_new_items_per_sentence


# --------------------------------------------------------------------------
# 합성 입력
# --------------------------------------------------------------------------

# 한 item = 한 단어. 문장은 단어를 `と`로 잇고 `。`로 끝낸다. 한자를 넣어 ruby 계산도 돈다.
WORDS = {
    "it_a": ("赤", "あか"),
    "it_b": ("青", "あお"),
    "it_c": ("白", "しろ"),
    "it_d": ("黒", "くろ"),
    "it_e": ("緑", "みどり"),
    "it_f": ("紫", "むらさき"),
}


def _item_entry(
    seed_id: str, difficulty: str = "beginner", rank: int | None = 10
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "seed_id": seed_id,
        "type": "word",
        "lemma": WORDS[seed_id][0],
        "reading": WORDS[seed_id][1],
        "default_meaning": "색",
        "difficulty_label": difficulty,
    }
    if rank is not None:
        entry["frequency_rank"] = rank
    return entry


def _explanation(seed_id: str) -> dict[str, Any]:
    return {
        "reading": WORDS[seed_id][1],
        "core_meaning": f"{seed_id} 뜻",
        "meaning_in_context": f"{seed_id} 문맥 뜻",
        "nuance": f"{seed_id} 뉘앙스",
        "example_sentence": f"{WORDS[seed_id][0]}です。",
        "example_translation": None,
    }


def _sentence_entry(seed_id: str, item_ids: Sequence[str]) -> dict[str, Any]:
    japanese = "と".join(WORDS[item_id][0] for item_id in item_ids) + "。"
    items = []
    cursor = 0
    for item_id in item_ids:
        surface = WORDS[item_id][0]
        start = japanese.index(surface, cursor)
        cursor = start + len(surface)
        items.append(
            {
                "item_seed_id": item_id,
                "surface_form": surface,
                "is_tappable": True,
                "spans": [{"start_codepoint": start, "end_codepoint": cursor, "span_order": 0}],
                "explanation": _explanation(item_id),
            }
        )
    return {
        "seed_id": seed_id,
        "japanese": japanese,
        "korean_translation": f"{seed_id} 번역",
        "items": items,
    }


def _write_seed(
    directory: Path, items: list[dict[str, Any]], sentences: list[dict[str, Any]]
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "items.yaml").write_text(
        yaml.safe_dump(items, allow_unicode=True), encoding="utf-8"
    )
    (directory / "sentences.yaml").write_text(
        yaml.safe_dump(sentences, allow_unicode=True), encoding="utf-8"
    )
    return directory


def _run(module: ModuleType, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    capsys.readouterr()
    code = module.main(list(argv))
    return code, capsys.readouterr().out


def _item(
    module: ModuleType, seed_id: str, difficulty: str, rank: int | None, order: int
) -> object:
    return module.SeedItem(
        seed_id=seed_id,
        type=module.LearningItemType.WORD,
        lemma=seed_id,
        difficulty_label=difficulty,
        frequency_rank=rank,
        learning_item_id=order,
    )


def _sentence(module: ModuleType, seed_id: str, item_ids: Sequence[str]) -> object:
    return module.SeedSentence(
        seed_id=seed_id,
        japanese=seed_id,
        korean_translation=seed_id,
        items=tuple(
            module.SeedSentenceItem(
                item_seed_id=item_id,
                surface_form=item_id,
                is_tappable=True,
                spans=(ItemSpan(0, 1, 0),),
                explanation=None,
            )
            for item_id in item_ids
        ),
    )


# --------------------------------------------------------------------------
# 재생성 일치
# --------------------------------------------------------------------------


def test_committed_fixture_matches_regeneration(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(fixture_script, capsys, "--check")
    assert code == EXIT_OK, out
    assert out.endswith("check: ok\n")


def test_check_fails_when_one_character_changes(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = tmp_path / "fixture-data.ts"
    shutil.copyfile(COMMITTED, copy)
    code, _ = _run(fixture_script, capsys, "--check", "--output", str(copy))
    assert code == EXIT_OK

    text = copy.read_text(encoding="utf-8")
    index = text.index('"korean_translation":"') + len('"korean_translation":"')
    replacement = "가" if text[index] != "가" else "나"
    copy.write_text(text[:index] + replacement + text[index + 1 :], encoding="utf-8")

    code, out = _run(fixture_script, capsys, "--check", "--output", str(copy))
    assert code == EXIT_FAILED
    assert out.endswith(f"check: differs {copy}\n")


def test_check_fails_when_the_file_is_missing(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    missing = tmp_path / "nothing.ts"
    code, out = _run(fixture_script, capsys, "--check", "--output", str(missing))
    assert code == EXIT_FAILED
    assert f"check: differs {missing}" in out
    assert not missing.exists()


def test_same_seed_writes_the_same_bytes(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry("it_a"), _item_entry("it_b")],
        [_sentence_entry("sn_1", ["it_a"]), _sentence_entry("sn_2", ["it_b"])],
    )
    first, second = tmp_path / "one.ts", tmp_path / "two.ts"
    assert _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(first))[0] == 0
    assert _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(second))[0] == 0
    assert first.read_bytes() == second.read_bytes()


# --------------------------------------------------------------------------
# 선택 규칙
# --------------------------------------------------------------------------


def test_items_are_visited_by_difficulty_then_rank_then_seed_id(fixture_script: ModuleType) -> None:
    m = fixture_script
    items = [
        _item(m, "it_inter", "intermediate", 1, 1),
        _item(m, "it_norank", "beginner", None, 2),
        _item(m, "it_rank50", "beginner", 50, 3),
        _item(m, "it_rank10_z", "beginner", 10, 4),
        _item(m, "it_rank10_a", "beginner", 10, 5),
        _item(m, "it_adv", "advanced", 1, 6),
    ]
    # 문장 seed_id 순서는 기대 순서와 일부러 어긋나게 둔다.
    passing = [
        _sentence(m, "sn_1", ["it_adv"]),
        _sentence(m, "sn_2", ["it_inter"]),
        _sentence(m, "sn_3", ["it_norank"]),
        _sentence(m, "sn_4", ["it_rank50"]),
        _sentence(m, "sn_5", ["it_rank10_z"]),
        _sentence(m, "sn_6", ["it_rank10_a"]),
    ]
    selected, uncovered = m.select_sentences(items, passing, 200)
    assert [s.seed_id for s in selected] == ["sn_6", "sn_5", "sn_4", "sn_3", "sn_2", "sn_1"]
    assert uncovered == []


def test_frequency_rank_none_goes_after_every_ranked_item_of_the_same_difficulty(
    fixture_script: ModuleType,
) -> None:
    m = fixture_script
    items = [
        _item(m, "it_a_none", "beginner", None, 1),
        _item(m, "it_z_huge", "beginner", 10**9, 2),
        _item(m, "it_inter", "intermediate", 1, 3),
    ]
    ordered: list[Any] = sorted(items, key=m.item_sort_key)
    assert [item.seed_id for item in ordered] == ["it_z_huge", "it_a_none", "it_inter"]


def test_picks_the_sentence_that_covers_the_most_uncovered_items(
    fixture_script: ModuleType,
) -> None:
    m = fixture_script
    items = [_item(m, "it_x", "beginner", 1, 1), _item(m, "it_y", "beginner", 2, 2)]
    passing = [
        _sentence(m, "sn_1", ["it_x"]),
        _sentence(m, "sn_2", ["it_x", "it_y"]),
    ]
    selected, _ = m.select_sentences(items, passing, 200)
    # sn_2가 it_y까지 덮었으므로 it_y 차례에 다른 문장을 고르지 않는다.
    assert [s.seed_id for s in selected] == ["sn_2"]


def test_already_covered_items_do_not_count_toward_coverage(fixture_script: ModuleType) -> None:
    m = fixture_script
    items = [
        _item(m, "it_x", "beginner", 1, 1),
        _item(m, "it_y", "beginner", 2, 2),
        _item(m, "it_z", "beginner", 3, 3),
        _item(m, "it_w", "beginner", 4, 4),
    ]
    passing = [
        _sentence(m, "sn_1", ["it_x", "it_w"]),
        # it_y 차례: 둘 다 item 2개지만 sn_2의 it_w는 이미 덮였다(새 1개), sn_3은 새 2개
        _sentence(m, "sn_2", ["it_y", "it_w"]),
        _sentence(m, "sn_3", ["it_y", "it_z"]),
    ]
    selected, _ = m.select_sentences(items, passing, 200)
    assert [s.seed_id for s in selected] == ["sn_1", "sn_3"]


def test_ties_go_to_the_smaller_sentence_seed_id(fixture_script: ModuleType) -> None:
    m = fixture_script
    items = [_item(m, "it_x", "beginner", 1, 1)]
    passing = [_sentence(m, "sn_b", ["it_x"]), _sentence(m, "sn_a", ["it_x"])]
    selected, _ = m.select_sentences(items, passing, 200)
    assert [s.seed_id for s in selected] == ["sn_a"]


def test_stops_at_the_cap_and_lists_the_rest_as_uncovered(fixture_script: ModuleType) -> None:
    m = fixture_script
    items = [_item(m, f"it_{n}", "beginner", n, n) for n in (1, 2, 3, 4)]
    passing = [_sentence(m, f"sn_{n}", [f"it_{n}"]) for n in (1, 2, 3, 4)]
    selected, uncovered = m.select_sentences(items, passing, 2)
    assert [s.seed_id for s in selected] == ["sn_1", "sn_2"]
    assert [item.seed_id for item in uncovered] == ["it_3", "it_4"]


def test_an_item_without_a_candidate_is_skipped_not_fatal(fixture_script: ModuleType) -> None:
    m = fixture_script
    items = [
        _item(m, "it_1", "beginner", 1, 1),
        _item(m, "it_2", "beginner", 2, 2),
        _item(m, "it_3", "beginner", 3, 3),
    ]
    passing = [_sentence(m, "sn_1", ["it_1"]), _sentence(m, "sn_3", ["it_3"])]
    selected, uncovered = m.select_sentences(items, passing, 200)
    assert [s.seed_id for s in selected] == ["sn_1", "sn_3"]
    assert [item.seed_id for item in uncovered] == ["it_2"]


def test_generated_order_is_selection_order(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry("it_a", rank=30), _item_entry("it_b", rank=20), _item_entry("it_c", rank=10)],
        [
            _sentence_entry("sn_1", ["it_a"]),
            _sentence_entry("sn_2", ["it_b"]),
            _sentence_entry("sn_3", ["it_c"]),
        ],
    )
    output = tmp_path / "out.ts"
    code, _ = _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(output))
    assert code == EXIT_OK
    _, data = fixture_script.read_fixture(output)
    assert [entry["korean_translation"] for entry in data] == [
        "sn_3 번역",
        "sn_2 번역",
        "sn_1 번역",
    ]
    assert [entry["presentation"]["sentence_id"] for entry in data] == [1, 2, 3]
    assert [entry["presentation"]["presentation_id"] for entry in data] == [1, 2, 3]


# --------------------------------------------------------------------------
# 검사 3종과 출력
# --------------------------------------------------------------------------


def test_each_check_excludes_the_sentence_and_prints_the_reason(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cap = _max_tappable()
    item_ids = list(WORDS)
    assert cap + 1 <= len(item_ids), "합성 단어가 상한 + 1개보다 적다"

    good = _sentence_entry("sn_good", ["it_a"])

    bad_span = _sentence_entry("sn_bad_span", ["it_b"])
    bad_span["items"][0]["spans"][0]["start_codepoint"] += 1
    bad_span["items"][0]["spans"][0]["end_codepoint"] += 1

    overlap = _sentence_entry("sn_overlap", ["it_c", "it_d"])
    overlap["items"][1]["surface_form"] = overlap["items"][0]["surface_form"]
    overlap["items"][1]["spans"] = overlap["items"][0]["spans"]

    no_explanation = _sentence_entry("sn_no_explanation", ["it_c"])
    del no_explanation["items"][0]["explanation"]

    empty_field = _sentence_entry("sn_empty_field", ["it_d"])
    empty_field["items"][0]["explanation"]["nuance"] = " "

    too_many = _sentence_entry("sn_too_many", item_ids[: cap + 1])

    none_tappable = _sentence_entry("sn_none_tappable", ["it_e"])
    none_tappable["items"][0]["is_tappable"] = False

    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry(item_id) for item_id in item_ids],
        [good, bad_span, overlap, no_explanation, empty_field, too_many, none_tappable],
    )
    output = tmp_path / "out.ts"
    code, out = _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(output))
    assert code == EXIT_OK

    excluded = re.findall(r"^excluded sentence=(\S+) reason=(\S+)$", out, re.MULTILINE)
    assert excluded == [
        ("sn_bad_span", "span_mismatch"),
        ("sn_overlap", "span_mismatch"),
        ("sn_no_explanation", "missing_explanation"),
        ("sn_empty_field", "missing_explanation"),
        ("sn_too_many", "tappable_count"),
        ("sn_none_tappable", "tappable_count"),
    ]
    match = FIXTURE_LINE.search(out)
    assert match is not None
    assert match.group(5) == "6"

    _, data = fixture_script.read_fixture(output)
    assert [entry["korean_translation"] for entry in data] == ["sn_good 번역"]


def test_a_sentence_at_the_tappable_cap_passes(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cap = _max_tappable()
    item_ids = list(WORDS)[:cap]
    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry(item_id) for item_id in item_ids],
        [_sentence_entry("sn_full", item_ids)],
    )
    code, out = _run(
        fixture_script, capsys, "--seed-dir", str(seed), "--output", str(tmp_path / "out.ts")
    )
    assert code == EXIT_OK
    assert "excluded sentence=" not in out


def test_excluded_seed_ids_are_escaped(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sentence = _sentence_entry("sn_\x1b[31m", ["it_a"])
    del sentence["items"][0]["explanation"]
    seed = _write_seed(tmp_path / "seed", [_item_entry("it_a")], [sentence])
    code, out = _run(
        fixture_script, capsys, "--seed-dir", str(seed), "--output", str(tmp_path / "out.ts")
    )
    assert code == EXIT_OK
    assert "\x1b" not in out
    assert "excluded sentence=sn_\\u001B[31m reason=missing_explanation\n" in out


def test_uncovered_items_are_listed_and_the_build_continues(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    only_in_excluded = _sentence_entry("sn_bad", ["it_b"])
    del only_in_excluded["items"][0]["explanation"]
    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry("it_a"), _item_entry("it_b"), _item_entry("it_c")],
        [_sentence_entry("sn_a", ["it_a"]), only_in_excluded],
    )
    output = tmp_path / "out.ts"
    code, out = _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(output))
    assert code == EXIT_OK
    assert re.findall(r"^uncovered item=(\S+)$", out, re.MULTILINE) == ["it_b", "it_c"]
    match = FIXTURE_LINE.search(out)
    assert match is not None
    assert match.groups()[:6] == ("1", "200", "1", "3", "1", "2")
    assert output.is_file()


def test_structural_seed_errors_exit_2_without_writing(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    unknown_item = _sentence_entry("sn_a", ["it_a"])
    unknown_item["items"][0]["item_seed_id"] = "it_missing"
    seed = _write_seed(tmp_path / "seed", [_item_entry("it_a")], [unknown_item])
    output = tmp_path / "out.ts"
    code = fixture_script.main(["--seed-dir", str(seed), "--output", str(output)])
    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert "unknown item_seed_id 'it_missing'" in captured.err
    assert not output.exists()


def test_summary_lines_are_printed(
    fixture_script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    seed = _write_seed(
        tmp_path / "seed", [_item_entry("it_a")], [_sentence_entry("sn_a", ["it_a"])]
    )
    output = tmp_path / "out.ts"
    code, out = _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(output))
    assert code == EXIT_OK
    lines = out.splitlines()
    assert FIXTURE_LINE.fullmatch(lines[0])
    assert re.fullmatch(
        r"ruby: algorithm_version=\d+ sentences=1 computed=1 failed=0 .* kanji_tokens=\d+", lines[1]
    )
    assert lines[2].startswith("rule 私->わたし hits=")
    assert lines[-1] == f"wrote {output}"


# --------------------------------------------------------------------------
# ruby
# --------------------------------------------------------------------------


def _seed_sentences_by_japanese() -> dict[str, dict[str, Any]]:
    entries = yaml.safe_load((SEED_DIR / "sentences.yaml").read_text(encoding="utf-8"))
    return {entry["japanese"]: entry for entry in entries}


def _seed_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = yaml.safe_load(
        (SEED_DIR / "items.yaml").read_text(encoding="utf-8")
    )
    return items


def _committed(module: ModuleType) -> tuple[str, list[dict[str, Any]]]:
    identifier, data = module.read_fixture(COMMITTED)
    return identifier, data


def test_ruby_equals_an_independent_recomputation(fixture_script: ModuleType) -> None:
    seeds = _seed_sentences_by_japanese()
    _, data = _committed(fixture_script)
    assert data
    with_ruby = 0
    for entry in data:
        presentation = entry["presentation"]
        seed = seeds[presentation["japanese"]]
        tappable = [item for item in seed["items"] if item["is_tappable"]]
        ids = presentation["tappable_items"]
        assert len(ids) == len(tappable)
        refs = [
            SpanRef(
                sentence_item_id=ref["sentence_item_id"],
                learning_item_id=ref["learning_item_id"],
                is_tappable=True,
                start_codepoint=span["start_codepoint"],
                end_codepoint=span["end_codepoint"],
            )
            for item, ref in zip(tappable, ids, strict=True)
            for span in item["spans"]
        ]
        ruby_items = [
            RubyItem(
                sentence_item_id=item["item_seed_id"],
                spans=tuple(ItemSpan(**span) for span in item["spans"]),
                explanation_reading=item["explanation"]["reading"],
            )
            for item in tappable
        ]
        computation = compute_ruby(
            presentation["japanese"], ruby_items, now=fixture_script.RUBY_COMPUTED_AT
        )
        expected = [
            {
                "text": segment.text,
                "sentence_item_id": segment.sentence_item_id,
                "ruby": [{"text": part.text, "reading": part.reading} for part in segment.ruby],
            }
            for segment in build_render_segments(
                presentation["japanese"], refs, ruby=computation.spans
            )
        ]
        assert presentation["render_segments"] == expected, seed["seed_id"]
        with_ruby += any(segment["ruby"] for segment in expected)
    assert with_ruby > 0


def test_segments_follow_the_render_segments_ruby_rules(fixture_script: ModuleType) -> None:
    _, data = _committed(fixture_script)
    for entry in data:
        presentation = entry["presentation"]
        segments = presentation["render_segments"]
        assert "".join(segment["text"] for segment in segments) == presentation["japanese"]
        for segment in segments:
            parts = segment["ruby"]
            if not parts:
                continue
            # R1
            assert "".join(part["text"] for part in parts) == segment["text"]
            # R2: []가 아니면 읽기가 하나 이상 있다
            assert any(part["reading"] is not None for part in parts)
            for part, following in itertools.pairwise(parts):
                # R3: 인접한 reading null 조각이 없다
                assert not (part["reading"] is None and following["reading"] is None)
            # R3: 빈 조각이 없다
            assert all(part["text"] for part in parts)


def test_ruby_failure_keeps_the_sentence_with_empty_ruby(
    fixture_script: ModuleType,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _write_seed(
        tmp_path / "seed",
        [_item_entry("it_a"), _item_entry("it_b")],
        [_sentence_entry("sn_a", ["it_a"]), _sentence_entry("sn_b", ["it_b"])],
    )
    real = fixture_script.compute_ruby

    def flaky(japanese: str, items: Sequence[RubyItem], *, now: datetime) -> object:
        if japanese.startswith(WORDS["it_b"][0]):
            raise ValueError("boom: secret detail")
        return real(japanese, items, now=now)

    monkeypatch.setattr(fixture_script, "compute_ruby", flaky)
    output = tmp_path / "out.ts"
    code, out = _run(fixture_script, capsys, "--seed-dir", str(seed), "--output", str(output))
    assert code == EXIT_OK
    assert "ruby_failed sentence=sn_b error=ValueError\n" in out
    assert "boom" not in out
    assert re.search(r"^ruby: .* sentences=2 computed=1 failed=1 ", out, re.MULTILINE)

    _, data = fixture_script.read_fixture(output)
    by_translation = {entry["korean_translation"]: entry for entry in data}
    assert set(by_translation) == {"sn_a 번역", "sn_b 번역"}
    failed_segments = by_translation["sn_b 번역"]["presentation"]["render_segments"]
    assert all(segment["ruby"] == [] for segment in failed_segments)
    assert any(s["ruby"] for s in by_translation["sn_a 번역"]["presentation"]["render_segments"])


# --------------------------------------------------------------------------
# fixture 식별자
# --------------------------------------------------------------------------


def test_fixture_id_is_deterministic_and_content_bound(fixture_script: ModuleType) -> None:
    identifier, data = _committed(fixture_script)
    assert re.fullmatch(r"[0-9a-f]{16}", identifier)
    assert fixture_script.fixture_id(data) == identifier
    assert fixture_script.fixture_id(data) == fixture_script.fixture_id(list(data))

    changed = [dict(entry) for entry in data]
    changed[0] = {**changed[0], "korean_translation": changed[0]["korean_translation"] + "."}
    assert fixture_script.fixture_id(changed) != identifier

    swapped = [data[1], data[0], *data[2:]]
    assert fixture_script.fixture_id(swapped) != identifier


def test_generated_file_shape(fixture_script: ModuleType) -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    identifier, data = _committed(fixture_script)
    lines = text.split("\n")
    assert lines[0] == "// 생성 파일. 손으로 고치지 않는다. scripts/build_demo_fixture.py"
    assert "http" not in lines[0]
    assert lines[1] == "import type { DemoSentence } from './fixture'"
    assert f"export const DEMO_FIXTURE_ID = '{identifier}'" in lines
    assert text.endswith("]\n")
    # 문장당 한 줄
    start = lines.index("export const DEMO_SENTENCES: readonly DemoSentence[] = [")
    assert len(lines) - start - 3 == len(data)
    assert fixture_script.render_ts(identifier, data) == text


# --------------------------------------------------------------------------
# 출처와 형식
# --------------------------------------------------------------------------


def test_every_sentence_translation_and_explanation_comes_from_seed(
    fixture_script: ModuleType,
) -> None:
    seeds = _seed_sentences_by_japanese()
    items = _seed_items()
    learning_ids = {item["seed_id"]: index + 1 for index, item in enumerate(items)}
    items_by_id = {item["seed_id"]: item for item in items}
    _, data = _committed(fixture_script)

    assert 0 < len(data) <= fixture_script.DEMO_SENTENCE_CAP
    for sentence_id, entry in enumerate(data, start=1):
        presentation = entry["presentation"]
        assert set(entry) == {"presentation", "korean_translation", "explanations"}
        PresentationPayload.model_validate(presentation)
        assert presentation["sentence_id"] == presentation["presentation_id"] == sentence_id
        assert presentation["probe"] is None
        assert presentation["translation_revealed"] is False

        seed = seeds[presentation["japanese"]]
        assert entry["korean_translation"] == seed["korean_translation"]
        tappable = [item for item in seed["items"] if item["is_tappable"]]
        expected_ids = [
            {
                "sentence_item_id": sentence_id * 10 + order,
                "learning_item_id": learning_ids[item["item_seed_id"]],
            }
            for order, item in enumerate(tappable, start=1)
        ]
        assert presentation["tappable_items"] == expected_ids
        assert set(entry["explanations"]) == {str(ref["sentence_item_id"]) for ref in expected_ids}

        for item, ref in zip(tappable, expected_ids, strict=True):
            explanation = entry["explanations"][str(ref["sentence_item_id"])]
            ExplanationResponse.model_validate(explanation)
            learning_item = items_by_id[item["item_seed_id"]]
            assert explanation == {
                **ref,
                "canonical_form": learning_item["lemma"],
                "item_type": learning_item["type"],
                **{
                    key: item["explanation"].get(key)
                    for key in (
                        "reading",
                        "core_meaning",
                        "meaning_in_context",
                        "nuance",
                        "example_sentence",
                        "example_translation",
                    )
                },
            }
