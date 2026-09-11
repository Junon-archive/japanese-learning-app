# Nihongo Context --- Specification Repository

이 저장소는 개인용 일본어 학습 앱 **Nihongo Context**의 제품·학습·기술
명세를 관리한다.

앱의 목적은 JLPT 점수 최적화가 아니라, 사용자가 **일본어 YouTube를
이해하고 일본인과 일상 대화를 할 수 있는 실용적 이해·청해 능력**을
만드는 것이다. 핵심 방식은 단어장 중심이 아니라 **Sentence-first → 표현
확인 → 이해도 추정 → 문맥 기반 SRS 재노출**이다.

## 현재 구현 단계

-   Current milestone: `MVP-01 Core Learning`
-   MVP는 폐기할 프로토타입이 아니라 **완성 제품의 첫 번째 작고 안정적인
    조각**이다.
-   MVP-01에서는 YouTube, Speaking, STT, 고급 통계, 복잡한 오프라인
    동기화를 구현하지 않는다.
-   실제 개인 학습 모드와 포트폴리오용 Public Demo를 분리한다.

## 명세 우선순위

충돌 시 다음 순서를 따른다.

1.  `spec/mvp-01-core/*`의 승인된 기능/상태 규칙
2.  전역 제품/아키텍처 명세
3.  `spec/reference/ui/core-learning-mockup.html`의 시각·인터랙션 방향
4.  구현상 편의

구현자가 명세 충돌을 발견하면 임의로 해석해 기능을 추가하지 않고, 충돌을
기록하고 최소 변경으로 해결한다.

## 주요 디렉터리

-   `spec/`: Source of truth
-   `spec/reference/ui/`: 시각적 목업
-   `docs/decisions/`: 중요한 기술 결정 기록
-   실제 구현 시 `frontend/`, `backend/`, `infra/`, `scripts/`,
    `data/`가 추가된다.
