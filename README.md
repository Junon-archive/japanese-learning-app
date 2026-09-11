# Nihongo Context --- Specification Repository

**Spec Version: v0.2**\
**Current Milestone: MVP-01 Core Learning**

개인용 일본어 학습 앱 Nihongo Context의 제품·학습·기술 명세다. 목표는
JLPT가 아니라 일본어 YouTube 이해와 일상 회화 능력이다.

## 문서 계층

-   `spec/00~06`: 장기적으로 유지할 제품/학습/기술 원칙
-   `spec/mvp-01-core/`: 현재 구현 범위
-   `spec/future/`: 지금 구현하지 않지만 보존할 장기 설계
-   `spec/reference/ui/`: 시각·인터랙션 reference

## 우선순위

``` text
MVP 구현 source of truth:
    spec/mvp-01-core/*

Global 문서 (spec/00~06):
    제품/기술 제약을 제공하지만 MVP Scope를 확대하지 않는다.

Future (spec/future/*):
    절대 구현 지시가 아니다.
```

충돌 시 다음 순서를 따른다.

1.  `spec/mvp-01-core/*`의 승인된 기능/상태 규칙
2.  Global principles (`spec/00~06`)
3.  UI reference (`spec/reference/ui/`)
4.  구현 편의

Future 문서는 MVP 범위를 넓히는 구현 지시가 아니다. Global/Future 문서에
숫자나 아이디어가 존재한다는 이유만으로 구현하지 않는다.

구현자가 명세 충돌을 발견하면 임의로 해석해 기능을 추가하지 않고, 충돌을
기록하고 최소 변경으로 해결한다.

MVP는 폐기용 prototype이 아니라 완성 제품의 첫 번째 작고 안정적인
조각이다.
