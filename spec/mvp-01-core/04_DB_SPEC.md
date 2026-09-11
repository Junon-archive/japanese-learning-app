# Database Specification

논리 schema이며 SQLAlchemy/Alembic으로 구현한다.

-   `users`
-   `learning_items`: type, lemma/canonical, reading, default_meaning,
    metadata
-   `sentences`: japanese, translation, source, difficulty, provenance,
    status
-   `sentence_items`: sentence/item, surface, offsets,
    role(new/review/exploration/incidental)
-   `user_mastery`: user/item, comprehension_mastery, listening_mastery,
    evidence_count
-   `review_states`: FSRS fields, meaningful_exposure_count,
    next_review_at
-   `learning_events`: immutable event_type/payload/time
-   `sessions`: start/end/target_minutes/mode/summary
-   `generation_jobs`: type/status/payload/result/retry/error/timestamps
-   `content_flags`: unnatural/wrong/too_easy/too_hard/other
-   `prompt_versions`

Demo state는 private mastery를 오염시키지 않는다.

Future-ready: item senses, register, active-use/recognize-only, richer
difficulty, morphology provenance, audio metadata, production mastery.
