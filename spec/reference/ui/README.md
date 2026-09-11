# UI Reference

`core-learning-mockup.html`은 시각·인터랙션 reference다. Pixel-perfect
최종 디자인이 아니며 기능/상태 충돌 시 `mvp-01-core/03_UI_UX_SPEC.md`가
우선한다.

## MVP-01 반영 사항

이 목업은 v0.2 이전에 작성되었으므로 현재 MVP 결정과 다음이 다르다.

-   `🔊 듣기` 버튼은 **MVP-01 범위 밖**이며 목업에서 disabled + `(Future)`
    표시로 남겨두었다. MVP interactive element가 아니다
    (`spec/mvp-01-core/00_SCOPE.md`).
-   Public Demo는 static frontend fixture이며 backend API를 호출하지
    않는다(`spec/04_SECURITY_AND_DATA.md`).
-   mastery probe UI는 `알고 있었음 / 애매함 / 몰랐음 / 건너뛰기` 4지
    선택으로 고정한다(`spec/mvp-01-core/02_LEARNING_POLICY.md`).
