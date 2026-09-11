# Future --- Experimental Parameters

`spec/05_LEARNING_SYSTEM_VISION.md`에 있던 구체 수치를 여기로 옮긴다.

아래 값은 전부 **non-binding experimental starting point**다. MVP-01
구현 지시가 아니며, 실제 사용 데이터로 검증하기 전까지 어떤 코드나
acceptance 조건에도 넣지 않는다.

## Comprehensible Input 난이도 밴드

``` text
Comfort   : known 95~98%
Normal    : known 90~95%
Challenge : known 80~90%
```

고정 법칙이 아니며 MVP에서는 **문장당 신규 1\~2개 규칙이 우선한다**
(`spec/mvp-01-core/02_LEARNING_POLICY.md`). MVP는 사용자 mastery가
희소한 초기 구간에서 known 비율을 신뢰도 있게 계산할 수 없으므로 이
밴드를 구현하지 않는다.

## Content Source Mix

``` text
real source            60
source transformation  30
fully generated        10
```

실험 가이드이지 확정값이 아니다. 같은 내용이
`spec/future/CONTENT_SYSTEM.md`에도 기록되어 있다.

## Habit --- Busy/Deadline Mode

기본 세션은 12분이다. 장기적으로 바쁜 날에는 **약 5분 최소 세션**으로
습관을 유지하는 모드를 실험할 수 있다.

MVP에는 Busy/Deadline 모드가 없다. `14_CONFIGURATION.md`에도 해당 키를
두지 않는다.

streak 벌점 대신 최근 30일 활동 / 주간 학습시간 / meaningful exposure
같은 지표를 선호한다는 방향은 유지한다
(`spec/01_PRODUCT_PRINCIPLES.md` #11).
