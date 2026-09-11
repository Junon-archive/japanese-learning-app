# Database Specification

PostgreSQL을 canonical datastore로 사용한다. 아래는 논리 schema이며 구현
시 SQLAlchemy/Alembic으로 구체화한다.

## users

-   id
-   email / login identifier
-   password_hash or auth identity
-   created_at
-   is_active

## learning_items

-   id
-   type: word \| grammar \| expression
-   lemma / canonical_form
-   reading
-   default_meaning
-   metadata_json
-   created_at

## sentences

-   id
-   japanese
-   korean_translation
-   source_type
-   source_id nullable
-   difficulty_json
-   provenance_json
-   created_at
-   status

## sentence_items

-   id
-   sentence_id
-   learning_item_id
-   surface_form
-   start_offset
-   end_offset
-   role: new \| review \| exploration \| incidental

## user_mastery

-   user_id
-   learning_item_id
-   comprehension_mastery nullable
-   listening_mastery nullable
-   last_updated_at
-   evidence_count

Unique: `(user_id, learning_item_id)`.

## review_states

-   user_id
-   learning_item_id
-   FSRS state fields
-   meaningful_exposure_count
-   last_reviewed_at
-   next_review_at

## learning_events

Immutable event log. - id - user_id - session_id - sentence_id
nullable - learning_item_id nullable - event_type - payload_json -
created_at

## sessions

-   id
-   user_id
-   started_at
-   ended_at
-   target_minutes default 12
-   mode
-   summary_json

## generation_jobs

-   id
-   job_type
-   status
-   payload_json
-   result_ref nullable
-   retry_count
-   error_message nullable
-   created_at
-   started_at
-   finished_at

## content_flags

-   id
-   user_id
-   sentence_id / learning_item_id
-   reason: unnatural \| wrong \| too_easy \| too_hard \| other
-   note nullable
-   created_at
-   resolved_at nullable

## prompt_versions

-   id
-   task_type
-   version
-   model/provider metadata
-   created_at
-   active

## Demo Data

Demo content는 실제 개인 학습 데이터와 논리적으로 분리한다. Demo
action이 실제 `user_mastery`를 오염시키지 않게 한다.

## Migration Rule

DB schema 변경은 Alembic migration 없이 직접 production DB에 적용하지
않는다.
