"""structured output 응답 fixture 조립기 (`08_LLM_SPEC.md`의 Structured Output 스키마).

`tests.provider_double.RecordingProvider`가 돌려줄 본문을 만든다. 이 응답도 **실제
구현과 똑같은 deterministic validation을 받는다** --- 검증을 건너뛰는 경로를 만들면
double로 통과한 Wave 3이 실제 provider에서 처음 실패한다.

span을 문장에서 **계산한다.** offset을 손으로 세면 문장을 한 글자 고칠 때마다 span이
조용히 어긋나고, 그것을 잡아야 할 테스트가 무엇을 검사하는지 알 수 없게 된다.

## `tests/provider_double.py`와의 경계

여기는 **문자열만** 만든다. `LlmProvider`를 구현하지 않고 호출을 기록하지 않는다 ---
그쪽은 `tests/provider_double.py`의 `RecordingProvider`이고, 두 역할을 한 파일에 두면
"무엇을 돌려줬는가"와 "무엇을 받았는가"가 같은 객체의 상태로 뒤섞인다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def explanation_payload(**overrides: str | None) -> dict[str, Any]:
    """필수 field가 모두 찬 explanation. `example_translation`만 null 허용이다."""
    payload: dict[str, Any] = {
        "reading": "まかせる",
        "core_meaning": "맡기다",
        "meaning_in_context": "그 일을 상대에게 넘기다",
        "nuance": "일상 대화에서 쓴다",
        "example_sentence": "あとは彼に任せるよ。",
        "example_translation": "나머지는 그에게 맡길게.",
    }
    payload.update(overrides)
    return payload


def item_payload(
    label: str,
    surface: str,
    japanese: str,
    *,
    is_tappable: bool = True,
    explanation: dict[str, Any] | str | None = "default",
) -> dict[str, Any]:
    start = japanese.index(surface)
    return {
        "item_ref": label,
        "surface_form": surface,
        "is_tappable": is_tappable,
        "spans": [
            {
                "start_codepoint": start,
                "end_codepoint": start + len(surface),
                "span_order": 0,
            }
        ],
        "explanation": explanation_payload() if explanation == "default" else explanation,
    }


def sentence_payload(
    japanese: str,
    items: Sequence[dict[str, Any]],
    *,
    korean_translation: str = "번역",
    difficulty_label: str = "beginner",
) -> dict[str, Any]:
    return {
        "japanese": japanese,
        "korean_translation": korean_translation,
        "difficulty_label": difficulty_label,
        "items": list(items),
    }


def batch_response(*sentences: dict[str, Any]) -> str:
    """`GENERATE_SENTENCE_BATCH` / `GENERATE_REVIEW_CONTEXT`의 응답 본문 (같은 스키마)."""
    return json.dumps({"sentences": list(sentences)}, ensure_ascii=False)
