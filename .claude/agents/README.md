# Agents

Nihongo Context MVP-01 구현용 subagent 정의.

## 상시 (구현)

| agent | 역할 | 주 담당 명세 |
|---|---|---|
| `planner` | 작업 분할 + implementation plan | `mvp-01-core/*` 전체 |
| `architect` | 모듈 경계·인터페이스·ADR | `02_ARCHITECTURE`, `docs/decisions/` |
| `backend-implementer` | FastAPI / worker / 엔진 구현 | `05,06,07,08,09,10` |
| `frontend-implementer` | PWA / 학습 UI / demo fixture | `01,03,05` |
| `debugger` | 실패 재현·원인 수정 | 해당 없음 |

## 게이트 (기능/PR 단위 호출, 대부분 읽기 전용)

| agent | 무엇을 막는가 |
|---|---|
| `db-migration` | schema 제약 누락 → exposure/job 중복으로 인한 데이터 오염 |
| `learning-verifier` | 코드는 통과하는데 학습 정책이 틀린 상태 |
| `test-engineer` | 테스트 없는 완료 처리 (AGENTS.md #6) |
| `scope-guard` | Future 기능 유입으로 MVP 붕괴 |
| `security-reviewer` | auth·CORS/CSRF·secret·demo 격리 결함 |

## 전문

| agent | 역할 |
|---|---|
| `llm-prompt` | prompt / structured output / validation / provenance |
| `spec-sync` | 명세 공백·충돌을 spec에 역반영, ADR·CHANGELOG |

## 권장 흐름

```
planner → architect → db-migration → backend/frontend-implementer
        → test-engineer → learning-verifier → security-reviewer
        → scope-guard → (commit)
```

`debugger`와 `spec-sync`는 필요할 때 끼어든다.

## 아직 만들지 않은 것

- **infra/devops** — docker-compose, cloudflared, backup/restore 검증.
  배포 단계에서 추가. 그전까지는 `architect`가 겸한다.
- **seed-curator** — starter seed set(일본어 고빈도 표현) 작성.
  seed 실작성 시점에 추가.
- **git-specialist** — 만들지 않았다. 커밋 컨벤션은 에이전트보다
  `CLAUDE.md` 규칙 + hook이 확실하고, "diff를 범위와 대조하는" 실제
  필요는 `scope-guard`가 담당한다.

## 모델

모든 정의에서 `model`을 지정하지 않았으므로 **세션 모델을 상속**한다.
비용을 조절하려면 각 파일 frontmatter에 `model: sonnet` 등을 추가한다.
판단이 중요한 `learning-verifier` / `security-reviewer` / `scope-guard` /
`architect`는 상위 모델 유지를 권한다.
