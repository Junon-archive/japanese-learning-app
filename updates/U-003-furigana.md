# U-003 후리가나 on/off

| 항목 | 값 |
|---|---|
| 번호 | U-003 |
| 제목 | 후리가나 on/off |
| 상태 | 배포 대기 |
| 우선순위 | 높음 |
| 요청일 | 2026-09-13 |
| 관련 명세 | `spec/mvp-01-core/03_UI_UX_SPEC.md`, `04_DB_SPEC.md`, `05_API_SPEC.md`, `08_LLM_SPEC.md`, `14_CONFIGURATION.md`, `spec/02_ARCHITECTURE.md`, `spec/06_LLM_ENGINEERING_PRINCIPLES.md`, `AGENTS.md` |
| 커밋 | 명세 b1ea50d, 7178f41, 78a3b38, 0b405c9 · 머지 8b89619, 82e9794, a55ce3a, ec581a7 |

---

## 1. 배경 --- 사용자 결정 (2026-09-13)

-   문장 안의 한자를 읽지 못하면 문장 자체를 읽을 수 없다.
-   지금은 furigana 상시 표시가 금지이고, 읽기는 item을 탭한 뒤 설명에서만 나온다.

## 2. 원하는 것 --- 사용자 결정 (2026-09-13)

### 표시 규칙

-   기본은 끔, 사용자가 켤 수 있음. 켜면 문장 안의 모든 한자에 읽기를 표시한다.
-   학습 표현이 아닌 한자(예: 仕事, 田中)에도 단다.
-   probe 중에도 그대로 표시한다. probe는 자기평가이고, 읽기는 뜻이 아니기 때문이다.

### 설정

-   기본값은 끔이다.
-   저장은 브라우저 localStorage다. DB와 API는 없다.
-   로그인 학습 화면과 demo에서 똑같이 동작한다.

### 읽기 계산 방식

-   형태소 분석기로 콘텐츠를 적재하거나 생성하는 시점에 한 번 계산하고 DB에 저장한다.
-   브라우저는 표시만 한다.

### 분석기 선정

-   기본 후보는 SudachiPy + SudachiDict-core다.
-   architect가 ADR로 확정한다. 확인할 것: 라이선스(Apache-2.0 계열의 허용적 라이선스), 이미지
    크기, Python 3.12 wheel.

### 데이터 설계 (architect + db-migration)

-   저장 방식: 문장별 ruby span 목록 `[start_codepoint, end_codepoint, reading]`
-   좌표계는 기존 `sentence_item_spans`와 같은 codepoint `[start, end)`다.
-   원문 `sentences.japanese`는 바꾸지 않는다.
-   ruby span은 한자 run 단위로 정렬한다(okurigana 분리). 그래서 tappable span 경계를 넘지 않는다.
    -   정렬이 모호한 토큰은 토큰 단위로 단다.
    -   경계를 넘게 되면 그 토큰은 읽기를 생략하고 관측(카운트/로그)한다.
-   분석기와 사전의 버전을 provenance로 기록한다.
-   읽기는 히라가나로 저장한다.
-   탭 가능한 item의 `explanation.reading`과 분석기 읽기가 어긋나면 자동으로 고치지 않고 보고
    목록에 남긴다.
-   후리가나 계산 실패는 문장 채택(ready)을 막지 않는다. 표시 보조이기 때문이다. 실패는 관측한다.

### 적용 대상

1.  seed 적재
2.  worker의 생성 파이프라인(검증을 통과한 뒤)
3.  기존 운영 DB의 문장 backfill 스크립트
    -   migration은 additive만 쓴다. 학습 기록을 보존하고 DB reset은 금지한다.
    -   스크립트는 멱등이다.
    -   `prod_db` 가드를 둔다.
    -   쓰기 전에 백업을 강제한다.
    -   dry-run 출력을 제공한다.
4.  demo fixture: 상세는 `U-005`.
    -   fixture 생성 스크립트가 같은 정렬 모듈로 ruby를 계산해 정적 데이터에 넣는다.
    -   분석기 출력과 fixture가 일치하는지 테스트한다.

### 경계 규칙

-   FastAPI 요청 경로에서 분석기를 호출하지 않는다. API는 저장된 ruby를 읽기만 한다.
-   후리가나 표시·토글은 학습 신호가 아니다.
    -   exposure/evidence/event를 만들지 않는다.
    -   서버로 보내지 않는다.

### 불변식 (MVP-02 추가 불변식 15·16·17·19)

-   15\. 후리가나는 적재·생성 시점에 결정적으로 계산해 저장한다. 요청 경로와 브라우저에서 분석하지 않는다.
-   16\. 후리가나 표시·토글, 가나 학습, demo 진행은 학습 이벤트·exposure·evidence를 만들지 않는다.
-   17\. ruby 표시가 원문 문자열, codepoint 좌표, tappable span 경계, 번역 reveal 규칙을 바꾸지 않는다.
-   19\. 운영 DB는 reset하지 않는다. migration은 additive만 쓰고 기존 학습 기록을 보존한다.

## 3. 원하지 않는 것 --- 사용자 결정 (2026-09-13)

-   LLM으로 읽기를 만들지 않는다. prompt도 바꾸지 않는다.
-   브라우저와 FastAPI 요청 경로에서 분석하지 않는다.
-   원문 `sentences.japanese`를 바꾸지 않는다.
-   `explanation.reading` 불일치를 자동으로 고치지 않는다.
-   운영 DB reset, additive가 아닌 migration.
-   형태소 분석기와 그 사전 외의 새 의존성.

## 4. 참고 --- 사용자 결정 (2026-09-13)

-   ruby span 좌표계: `spec/mvp-01-core/04_DB_SPEC.md`의 `sentence_item_spans`.
-   운영 DB 쓰기 가드 선례: `docs/decisions/ADR-020-production-topology.md`의 결정 7(`prod_db`).
-   demo fixture 적용: `U-005`.

## 5. 완료 확인 방법 --- 사용자 결정 (2026-09-13)

-   기본은 끔이고, 켜면 문장 안의 모든 한자에 읽기가 표시된다.
-   로그인 학습 화면과 demo에서 똑같이 동작한다.
-   분석기 출력과 demo fixture가 일치하는지 테스트한다.
-   ruby span이 tappable span 경계를 넘지 않는다. 넘게 되는 토큰은 읽기를 생략하고 관측된다.
-   후리가나 계산 실패가 문장 채택(ready)을 막지 않는다.
-   후리가나 표시·토글이 exposure/evidence/event를 만들지 않고 서버로 가지 않는다.
-   backfill 스크립트가 멱등이고, `prod_db` 가드·쓰기 전 백업 강제·dry-run 출력을 갖는다.

정식 합격 기준은 Wave 1의 `spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md`다.

---

## 6. 영향 명세·충돌 --- Claude 작성

### 충돌

-   `spec/mvp-01-core/03_UI_UX_SPEC.md`의 `Translation/Furigana`: "furigana 상시 표시 금지, item tap
    후 reading 제공." 새 규칙(기본 끔, 켤 수 있음)으로 바꾼다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/14_CONFIGURATION.md`의 `reading_default_visible` 단락: "`reading_default_visible`은
    항상 `false`를 유지한다. furigana 상시 표시 금지는 UI 규칙이며(`03_UI_UX_SPEC.md`) 이 키는
    reading reveal 기본 상태를 뜻한다." 금지 규칙 참조를 고치고, 이 키(item reading reveal)와
    후리가나 설정(localStorage)이 다른 것임을 적어야 한다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/14_CONFIGURATION.md` 같은 절: "presentation payload에는 `korean_translation`
    필드도 reading 필드도 존재하지 않으므로 … 번역과 reading은 각각 `/translation/reveal`과
    `/click`을 거쳐야만 나온다." payload에 ruby를 실으면 이 서술이 사실과 달라진다. item 설명의
    reading과 ruby의 관계를 정리해야 한다. (반영됨, b1ea50d)
-   `AGENTS.md`의 "MVP 구현 대상이 아님" 목록에 `형태소 분석기`가 있다. 이 항목만 MVP-02로
    해제한다. (반영됨, b1ea50d)
-   `.claude/agents/scope-guard.md`의 `즉시 위반으로 보고할 것`에 `형태소 분석기 도입`이 있다.
    그대로 두면 Wave 1 이후 게이트가 이 요청의 구현을 위반으로 보고한다. (반영됨, b1ea50d)
-   `spec/06_LLM_ENGINEERING_PRINCIPLES.md`의 MVP 제외 목록: "14번 중 형태소 분석기 도입". (반영됨,
    b1ea50d)

### 영향

-   `spec/mvp-01-core/01_USER_FLOW.md`: "reading은 item 설명에서 reveal." item 설명의 reading은
    그대로이고 후리가나는 별도 표시 보조라는 관계를 적는다. (반영됨, b1ea50d)
-   `spec/mvp-01-core/04_DB_SPEC.md`: ruby span 저장(additive migration), provenance, `Seed Data`
    적재 단계, `운영 DB에 migration을 적용하는 경로`와 backfill 관계. (반영됨, b1ea50d)
-   `spec/mvp-01-core/05_API_SPEC.md`의 `Sentence Presentation Payload`: 저장된 ruby를 싣는 필드.
    (반영됨, b1ea50d)
-   `spec/mvp-01-core/08_LLM_SPEC.md`: 검증 통과 뒤 파이프라인 후처리. prompt 불변. (반영됨, b1ea50d)
-   `spec/02_ARCHITECTURE.md`: 분석기가 적재·생성·backfill에만 있고 요청 경로에 없다는 경계.
    (반영됨, b1ea50d)
-   `spec/mvp-01-core/11_OBSERVABILITY.md`: 생략 토큰 수, 계산 실패, `explanation.reading` 불일치
    보고의 관측 위치. (반영됨, b1ea50d, 7178f41)
-   `spec/mvp-01-core/02_LEARNING_POLICY.md`: 후리가나 토글이 학습 신호가 아님(불변식 16).
    learning-verifier 게이트 대상. (반영됨, b1ea50d)
-   `spec/04_SECURITY_AND_DATA.md`: localStorage 사용 범위. (반영됨, b1ea50d, 7178f41)
-   `docs/decisions/ADR-021`: 분석기 선정, ruby 데이터 모델, 한자 run 정렬 규칙, backfill 방식.
    (반영됨, b1ea50d, 7178f41)

## 7. 결정 필요 질문 --- Claude 작성

없음(확정).

조건부 보고: 다음 경우에는 멈추고 보고한다.

1.  허용적 라이선스의 분석기와 사전을 찾지 못했을 때
2.  한자 run 정렬로 tappable span 경계를 지킬 수 없는 경우가 흔할 때(샘플의 5% 초과)
3.  additive migration만으로 후리가나 저장이 불가능할 때

## 8. 작업 계획 --- Claude 작성

| Wave | 레인 | 작업 |
|---|---|---|
| 1 | main | ADR-021, spec-sync 반영(위 영향 문서), `AGENTS.md` 형태소 분석기 해제 |
| 2 | `furigana-be` | 분석기 의존성, additive migration, 정렬 모듈, seed 적재·worker 파이프라인 연결, backfill 스크립트(가드·백업·멱등·dry-run), API payload, 운영 이미지에 사전 포함 |
| 3 | `furigana-fe` | 토글(기본 끔, localStorage), 공통 문장 렌더러의 ruby 렌더링(tap·번역 규칙 유지), 로그인 학습 화면 연결, e2e |
| 3 | `demo` | fixture 생성 스크립트의 ruby 계산, demo 화면에 토글 연결(`U-005`) |
| 4 | main | 정렬 통계 보고, `ROADMAP.md` 상태를 `배포 대기`로 갱신(`done/` 이동은 사용자 배포 확인 후) |

실제와 달라진 곳:

-   분석기와 사전은 worker 이미지에만 넣었다. API 이미지에는 넣지 않는다(b1ea50d, 8b89619).
-   Wave 2 게이트 수정으로 ruby 로그 단계 실패 격리와 `ruby.log_failed` 이벤트를 따로 머지했다(82e9794, a55ce3a, 명세 7178f41).
-   Wave 3 `furigana-fe`에 좁은 폭 상단바 배치(`U-001`)가 함께 들어갔다(ec581a7).
-   배포 참고: `infra/DEPLOY.md`의 17절 "MVP-02 업데이트"(migration, backfill dry-run·적용, 되돌리기)(655f5b6).
