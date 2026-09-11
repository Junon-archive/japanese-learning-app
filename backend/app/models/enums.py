"""DB에 저장하는 열거값. 값은 명세에 적힌 문자열 그대로다.

PostgreSQL native enum을 쓰지 않으므로 이 값들은 `VARCHAR + CHECK`로 강제된다
(`app.models.base.enum_column`).
"""

from __future__ import annotations

import enum


class LearningItemType(enum.StrEnum):
    WORD = "word"
    GRAMMAR = "grammar"
    EXPRESSION = "expression"


class LearningItemOrigin(enum.StrEnum):
    SEED = "seed"
    GENERATED = "generated"


class StartingLevel(enum.StrEnum):
    """difficulty ladder와 공유하는 단조 등급 (06_LEARNING_ENGINE.md)."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SentenceSourceType(enum.StrEnum):
    GENERATED = "generated"
    SEED = "seed"


class SentenceStatus(enum.StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class ExplanationStatus(enum.StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    QUARANTINED = "quarantined"


class ContextStage(enum.StrEnum):
    ANCHOR = "anchor"
    NEAR_ORIGINAL = "near_original"
    VARIED = "varied"
    NEW_CONTEXT = "new_context"


class PresentationRole(enum.StrEnum):
    REVIEW = "review"
    NEW = "new"
    EXPLORATION = "exploration"


class ReviewReason(enum.StrEnum):
    FSRS_DUE = "fsrs_due"
    REINFORCEMENT = "reinforcement"
    CONTEXT_REPAIR = "context_repair"


class CandidateStatus(enum.StrEnum):
    QUEUED = "queued"
    READY = "ready"
    SHOWN = "shown"
    CONSUMED = "consumed"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"


class ExposureModality(enum.StrEnum):
    """MVP는 `reading`만 쓴다. `listening`은 Future이므로 값 자체를 두지 않는다."""

    READING = "reading"


class EventType(enum.StrEnum):
    SESSION_STARTED = "session_started"
    SENTENCE_VIEWED = "sentence_viewed"
    SENTENCE_COMPLETED = "sentence_completed"
    ITEM_CLICKED = "item_clicked"
    EXPLANATION_REVEALED = "explanation_revealed"
    TRANSLATION_REVEALED = "translation_revealed"
    SELF_REPORT_KNOWN = "self_report_known"
    SELF_REPORT_UNCERTAIN = "self_report_uncertain"
    SELF_REPORT_UNKNOWN = "self_report_unknown"
    MASTERY_PROBE_SHOWN = "mastery_probe_shown"
    MASTERY_PROBE_KNOWN = "mastery_probe_known"
    MASTERY_PROBE_UNCERTAIN = "mastery_probe_uncertain"
    MASTERY_PROBE_UNKNOWN = "mastery_probe_unknown"
    MASTERY_PROBE_SKIPPED = "mastery_probe_skipped"
    CONTENT_FLAGGED = "content_flagged"
    SESSION_EXTENDED = "session_extended"
    SESSION_FINISHED = "session_finished"


class ContentFlagReason(enum.StrEnum):
    UNNATURAL = "unnatural"
    WRONG = "wrong"
    TOO_EASY = "too_easy"
    TOO_HARD = "too_hard"
    OTHER = "other"


class GenerationJobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATED = "validated"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class LlmTaskType(enum.StrEnum):
    """08_LLM_SPEC.md의 MVP task. `prompt_versions.task_type`이 쓴다."""

    GENERATE_SENTENCE_BATCH = "GENERATE_SENTENCE_BATCH"
    EXPLAIN_ITEM = "EXPLAIN_ITEM"
    GENERATE_REVIEW_CONTEXT = "GENERATE_REVIEW_CONTEXT"


class JobType(enum.StrEnum):
    """`generation_jobs.job_type`. 08_LLM_SPEC.md의 3개로 확정됐다.

    pool replenishment는 job_type이 아니라 `GENERATE_SENTENCE_BATCH`를 enqueue하는
    트리거다. maintenance/cleanup은 MVP에 호출자가 없어 제외한다
    (`ANALYZE_SENTENCE`를 Future로 보낸 것과 같은 기준).
    """

    GENERATE_SENTENCE_BATCH = "GENERATE_SENTENCE_BATCH"
    EXPLAIN_ITEM = "EXPLAIN_ITEM"
    GENERATE_REVIEW_CONTEXT = "GENERATE_REVIEW_CONTEXT"
