# Test Plan

## Unit

no-click rule, policy ratios/config, mastery signals, exposure count,
FSRS wrapper, validation, duplicate, auth.

## Integration

FastAPI↔Postgres, session↔selection, event↔mastery/SRS, job↔worker↔pool,
Alembic from empty DB, Demo isolation.

## E2E

`任せる` 신규 노출 → click → 설명 → 몰랐음 → event/mastery/SRS → due
review → exposure 누적 → 원문에서 새 문맥으로 transfer → 5회 이후에도
FSRS due면 계속.

## Golden Regression

장기적으로 약 100개 sample로
naturalness/correctness/difficulty/explanation/register를 회귀 검토.
별도 LLM judge는 필수 아님.
