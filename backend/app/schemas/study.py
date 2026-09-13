"""Study endpoint 스키마 (05_API_SPEC.md의 `Study Session` / `Interaction`).

두 가지를 스키마 수준에서 못 박는다.

1.  **`korean_translation`은 presentation 응답에 필드로 존재하지 않는다.** 숨기는
    플래그를 두면 언젠가 그 플래그가 뒤집히지만, 필드가 없으면 새어 나갈 방법이
    없다. 번역은 `POST /translation/reveal`의 응답에만 있다(05_API_SPEC.md:
    "번역은 reveal 전 응답에 포함하지 않는다").
2.  **id는 전부 JSON number다**(ADR-005). 문자열로 감싸지 않는다. 예외는 client가
    만드는 `client_event_id`(UUID) 하나뿐이다.

offset은 응답에 싣지 않는다. frontend는 `render_segments`의 `text`를 순서대로 이어
붙일 뿐 인덱스를 계산하지 않는다(`app/render.py`).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, PlainSerializer, field_validator

from app.models.enums import (
    ContentFlagReason,
    ContextStage,
    ExplicitSignal,
    LearningItemType,
    PresentationRole,
    ReviewReason,
)

# probe 화면 문구. 학습 정책값이 아니라 UI 문자열이므로 config에 두지 않는다
# (`14_CONFIGURATION.md`는 정책값만 담는다). 05_API_SPEC.md의 예시 그대로다.
PROBE_PROMPT = "이 표현을 알고 계세요?"

# `content_flags.note`는 자유 입력이다. 상한이 없으면 한 번의 POST로 임의 크기
# 텍스트가 DB에 들어간다.
FLAG_NOTE_MAX_LENGTH = 500

# 모든 id는 bigint다(04_DB_SPEC.md). 범위를 벗어난 값을 그대로 조회에 넘기면
# psycopg가 `NumericValueOutOfRange`를 던져 client 입력만으로 500이 난다.
BIGINT_MAX = 2**63 - 1


class IdOutOfRangeError(Exception):
    """client가 보낸 id가 bigint 범위 밖이다.

    ValueError를 쓰지 않는 이유는 422가 되면 안 되기 때문이다. 범위 밖 id는 어떤
    행도 가리킬 수 없으므로 **존재하지 않는 id와 똑같이** 404로 나가야 한다. 상태
    코드가 갈리면 client가 두 경우를 다르게 다루게 되고, 응답 모양이 id마다 달라진다.
    pydantic은 ValueError/AssertionError만 검증 오류로 바꾸므로 이 예외는 그대로
    올라가 `app.api.study._http_errors()`가 404로 옮긴다.
    """


def _check_id_range(value: int) -> int:
    if not 1 <= value <= BIGINT_MAX:
        raise IdOutOfRangeError(f"id {value} is outside the bigint range")
    return value


# client가 보내는 id는 path든 body든 **전부** 이 타입이다. 새 endpoint가 `int`로
# 선언하면 `tests/test_route_error_mapping.py`가 빨개진다.
ResourceId = Annotated[int, AfterValidator(_check_id_range)]


def _to_utc_iso(value: datetime) -> str:
    """UTC ISO-8601 (05_API_SPEC.md의 `공통 규칙`)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcTimestamp = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str)]


class ProbeResponseValue(enum.StrEnum):
    """probe 응답 4값. `skip`은 `ExplicitSignal`에 **없다**.

    skip은 mastery evidence도 FSRS grade도 아니므로(02_LEARNING_POLICY.md의 `Skip`)
    `ExplicitSignal`로 표현될 수 없어야 한다. 그래서 여기서 한 번 더 갈라 놓고,
    `to_signal()`이 `None`으로 내보낸다 --- service가 skip을 evidence 경로에 넘기는
    것이 타입상 불가능해진다.
    """

    KNOWN = "known"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"
    SKIP = "skip"

    def to_signal(self) -> ExplicitSignal | None:
        if self is ProbeResponseValue.SKIP:
            return None
        return ExplicitSignal(self.value)


# 05_API_SPEC.md의 probe payload `options`. 선언 순서가 곧 표시 순서다.
PROBE_OPTIONS: list[str] = [value.value for value in ProbeResponseValue]


# --------------------------------------------------------------------------
# request
# --------------------------------------------------------------------------


class ClientEventRequest(BaseModel):
    """client 발급 `client_event_id`를 받는 요청 (05_API_SPEC.md의 표).

    server 발급 event(`/next`, `/complete`, `/finish`, `POST /session`)는 이 body를
    받지 않는다. 자연키가 있어 UUIDv5로 계산할 수 있기 때문이다(ADR-008).

    **client key는 UUIDv4만이다**(05_API_SPEC.md의 `키 공간 분리`). 검증은 이 클래스
    하나에만 있다. 상속하는 요청 schema가 전부 물려받으므로 endpoint마다 붙이다
    하나를 빠뜨리는 구멍이 생기지 않는다.
    """

    client_event_id: uuid.UUID

    @field_validator("client_event_id")
    @classmethod
    def _must_be_random_uuid(cls, value: uuid.UUID) -> uuid.UUID:
        """v4가 아니면 거부한다. server 발급 키(v5) 선점을 구조적으로 막는다.

        `uuid5(NC_EVENT_NAMESPACE, "session_finished:{sid}")`는 공개 상수로 누구나
        계산할 수 있고, client가 그것을 `/extend`로 먼저 점유하면 `/finish`가 영구
        409, idle timeout 만료까지 막혀 세션이 끝나지도 새로 생기지도 않았다
        (ADR-008의 `후속 결정 --- 키 공간 분리`). version nibble이 겹치지 않으면
        점유 시도 자체가 성립하지 않는다.

        여기서는 `ValueError`가 맞다 --- 의도된 응답이 **422**이기 때문이다. 위
        `IdOutOfRangeError`가 ValueError를 피한 것과 반대인데, 이유가 다르다. 범위 밖
        id는 "없는 것"이라 404여야 하지만, v5 key는 **client가 보내면 안 되는 값**이라
        body 검증 실패로 알려주는 것이 맞다. 상태 코드가 목적이고 예외 타입은 수단이다.
        """
        if value.version != 4:
            raise ValueError("client_event_id must be a random UUID (version 4)")
        return value


class SelfReportRequest(ClientEventRequest):
    sentence_item_id: ResourceId
    value: ExplicitSignal


class ProbeResponseRequest(ClientEventRequest):
    """`learning_item_id`를 받지 않는다.

    응답 event의 대상은 조회한 probe event의 값을 그대로 쓴다(05_API_SPEC.md).
    client가 보낸 값을 믿으면 위조된 대상에 evidence를 붙일 수 있다.
    """

    probe_id: ResourceId
    value: ProbeResponseValue


class ContentFlagRequest(ClientEventRequest):
    reason: ContentFlagReason
    note: str | None = Field(default=None, max_length=FLAG_NOTE_MAX_LENGTH)


# --------------------------------------------------------------------------
# response
# --------------------------------------------------------------------------


class StudySessionPayload(BaseModel):
    session_id: int
    started_at: UtcTimestamp
    last_activity_at: UtcTimestamp
    ended_at: UtcTimestamp | None
    active_seconds: int
    target_minutes: int
    extended_minutes: int


class OpenSessionResponse(BaseModel):
    """`GET /api/study/session`. 열린 session이 없으면 `session: null`이다."""

    session: StudySessionPayload | None


class StartSessionResponse(BaseModel):
    session: StudySessionPayload
    resumed: bool
    # idle timeout으로 이번에 닫힌 직전 session. client가 "이전 세션이 종료됐다"를
    # 표시할 수 있게 남긴다.
    timed_out_session_id: int | None


class RubyPartPayload(BaseModel):
    """segment 안의 표시 조각. `reading`이 null이면 후리가나 없이 text만 그린다."""

    text: str
    reading: str | None


class RenderSegmentPayload(BaseModel):
    text: str
    sentence_item_id: int | None
    # 후리가나 표시 보조(MVP-02, 05_API_SPEC.md R1~R7). 학습 신호가 아니다. 달 읽기가 없거나
    # 미계산·저장값 무효면 `[]`이고, 그 밖에는 parts의 text를 이으면 `text`와 같다.
    # 토글 상태와 무관하게 항상 싣는다(R7).
    ruby: list[RubyPartPayload]


class TappableItemPayload(BaseModel):
    sentence_item_id: int
    learning_item_id: int


class ProbePayload(BaseModel):
    probe_id: int
    learning_item_id: int
    prompt: str
    expression: str
    options: list[str]


class PresentationPayload(BaseModel):
    """`korean_translation`이 **없다.** 추가하지 않는다(모듈 docstring)."""

    presentation_id: int
    sentence_id: int
    japanese: str
    render_segments: list[RenderSegmentPayload]
    presentation_role: PresentationRole
    review_reason: ReviewReason | None
    context_stage: ContextStage
    translation_revealed: bool
    tappable_items: list[TappableItemPayload]
    probe: ProbePayload | None


class NextPresentationResponse(BaseModel):
    """Ready Pool이 비면 `presentation: null`이고 **상태 코드는 200이다.**

    빈 pool은 오류가 아니라 "지금 보여줄 문장이 없다"는 상태다. 예외를 던지면
    client가 무한 spinner나 오류 화면으로 가고, 그것이 10_ERROR_HANDLING.md의
    `Empty Pool`이 금지하는 것이다.
    """

    presentation: PresentationPayload | None


class CompletePresentationResponse(BaseModel):
    presentation_id: int
    completed_at: UtcTimestamp


class ExplanationResponse(BaseModel):
    """precomputed `sentence_item_explanations` 그대로다. live LLM fallback은 없다."""

    sentence_item_id: int
    learning_item_id: int
    canonical_form: str
    reading: str
    item_type: LearningItemType
    core_meaning: str
    meaning_in_context: str
    nuance: str
    example_sentence: str
    example_translation: str | None


class TranslationResponse(BaseModel):
    korean_translation: str


class ProbeResultResponse(BaseModel):
    """이미 응답한 probe에 다시 POST하면 기존 결과가 그대로 나온다."""

    probe_id: int
    learning_item_id: int
    value: ProbeResponseValue
