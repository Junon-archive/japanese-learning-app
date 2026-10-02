"""MVP-03 영어 seed YAML 조립 (ADR-024 결정 2의 6~7단계).

`select_english_candidates.py --json-out`로 만든 후보 목록(메타데이터)과, 에이전트가 직접
작성한 콘텐츠(예문·설명 JSON)를 합쳐 `seed/en/items.yaml`, `seed/en/sentences.yaml`을 쓴다.

콘텐츠 JSON 파일 하나는 다음 형태의 객체 배열이다(여러 파일로 나눠도 된다 -- 배치 작성):

    [
      {
        "seed_id": "en_it_0001",
        "default_meaning": "그러니까, 내 말은",
        "sentences": [
          {
            "text": "I mean, it's not like we had a choice.",
            "korean_translation": "그러니까, 우리한테 선택권이 있었던 것도 아니잖아.",
            "surface_form": "I mean",
            "explanation": {
              "core_meaning": "...", "meaning_in_context": "...", "nuance": "...",
              "example_sentence": "...", "example_translation": "..."
            }
          }
        ]
      }
    ]

`surface_form`은 `text` 안에 실제로 등장하는 연속 부분 문자열이어야 한다 --- 이 스크립트가
그 위치를 찾아 `start_codepoint`/`end_codepoint` span을 자동 계산한다(`reading`은 영어라
없다 --- `01_ENGLISH_CONTENT.md`). 문장 하나에 target item은 하나만 둔다(배치 단위로
독립적으로 작성하므로 교차 참조하지 않는다).

사용법:
    uv run python scripts/build_english_seed.py \\
        --candidates /tmp/candidates.json \\
        --content-dir /tmp/content/ \\
        --out-dir seed/en
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_EXPLANATION_FIELDS = (
    "core_meaning",
    "meaning_in_context",
    "example_sentence",
    "example_translation",
)


class BuildError(Exception):
    """조립 중 복구 불가능한 문제 -- 아무 파일도 쓰지 않는다."""


def load_candidates(path: Path) -> dict[str, dict[str, Any]]:
    candidates = json.loads(path.read_text(encoding="utf-8"))
    return {c["seed_id"]: c for c in candidates}


def load_content(content_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for file in sorted(content_dir.glob("*.json")):
        entries.extend(json.loads(file.read_text(encoding="utf-8")))
    return entries


def build(
    candidates: dict[str, dict[str, Any]], content: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    items_yaml: list[dict[str, Any]] = []
    sentences_yaml: list[dict[str, Any]] = []
    sentence_counter = 0

    seen_seed_ids: set[str] = set()
    for entry in content:
        seed_id = entry.get("seed_id")
        if not isinstance(seed_id, str):
            errors.append(f"seed_id가 없거나 문자열이 아니다: {entry!r}")
            continue
        meta = candidates.get(seed_id)
        if meta is None:
            errors.append(f"{seed_id}: 후보 메타데이터(candidates)에 없다")
            continue
        if seed_id in seen_seed_ids:
            errors.append(f"{seed_id}: content 안에서 중복")
            continue
        seen_seed_ids.add(seed_id)

        default_meaning = entry.get("default_meaning")
        if not default_meaning:
            errors.append(f"{seed_id}: default_meaning이 비어있다")
            continue

        items_yaml.append(
            {
                "seed_id": seed_id,
                "type": meta["type"],
                "lemma": meta["lemma"],
                "default_meaning": default_meaning,
                "difficulty_label": meta["difficulty_label"],
                "topic_tags": meta["topic_tags"],
                "frequency_rank": meta["frequency_rank"],
            }
        )

        sentences = entry.get("sentences") or []
        if not sentences:
            errors.append(f"{seed_id}: sentences가 비어있다")
            continue

        for sent in sentences:
            text = sent.get("text")
            surface_form = sent.get("surface_form")
            korean_translation = sent.get("korean_translation")
            if not text or not surface_form or not korean_translation:
                errors.append(
                    f"{seed_id}: 문장에 text/surface_form/korean_translation 누락 - {sent!r}"
                )
                continue

            start = text.find(surface_form)
            if start == -1:
                errors.append(f"{seed_id}: surface_form {surface_form!r}이 text {text!r} 안에 없다")
                continue
            end = start + len(surface_form)
            if text.find(surface_form, end) != -1:
                errors.append(
                    f"{seed_id}: surface_form {surface_form!r}이 text 안에 두 번 이상 등장(모호) - {text!r}"
                )
                continue

            exp = sent.get("explanation") or {}
            missing = [f for f in REQUIRED_EXPLANATION_FIELDS if not exp.get(f)]
            if missing:
                errors.append(f"{seed_id}: explanation 필드 누락 {missing} - text={text!r}")
                continue

            sentence_counter += 1
            sentences_yaml.append(
                {
                    "seed_id": f"en_sn_{sentence_counter:04d}",
                    "text": text,
                    "korean_translation": korean_translation,
                    "items": [
                        {
                            "item_seed_id": seed_id,
                            "surface_form": surface_form,
                            "is_tappable": True,
                            "spans": [
                                {"start_codepoint": start, "end_codepoint": end, "span_order": 0}
                            ],
                            "explanation": {
                                "core_meaning": exp["core_meaning"],
                                "meaning_in_context": exp["meaning_in_context"],
                                "nuance": exp.get("nuance") or "",
                                "example_sentence": exp["example_sentence"],
                                "example_translation": exp["example_translation"],
                            },
                        }
                    ],
                }
            )

    missing_ids = set(candidates) - seen_seed_ids
    for seed_id in sorted(missing_ids):
        errors.append(f"{seed_id}: candidates에는 있지만 content에 없다")

    return items_yaml, sentences_yaml, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--content-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("seed/en"))
    args = parser.parse_args()

    candidates = load_candidates(args.candidates)
    content = load_content(args.content_dir)
    items_yaml, sentences_yaml, errors = build(candidates, content)

    sys.stdout.write(
        f"items: {len(items_yaml)} / sentences: {len(sentences_yaml)} / errors: {len(errors)}\n"
    )
    if errors:
        sys.stdout.write("\n--- 오류 목록 ---\n")
        for e in errors:
            sys.stdout.write(f" - {e}\n")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "items.yaml").write_text(
        yaml.dump(items_yaml, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    (args.out_dir / "sentences.yaml").write_text(
        yaml.dump(sentences_yaml, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    sys.stdout.write(f"작성 완료: {args.out_dir}/items.yaml, {args.out_dir}/sentences.yaml\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
