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

## MVP-02 목업

`mvp-02-mockup.html`은 MVP-02 화면의 시각·인터랙션 reference다. 선택 홈, 상단바와 로그인 진입,
Login, demo 학습·설명 시트·probe·완료 화면, 가나 학습(표, 보고 읽기, 보고 고르기, 라운드 결과),
로그인한 Study Screen 상단, 화면 전환·토스트·reduced-motion을 한 파일에서 돌려 볼 수 있다.
외부 요청, 서버 호출, 브라우저 저장소 사용이 없는 정적 파일이다.

**우선순위**

1.  `spec/mvp-01-core/03_UI_UX_SPEC.md`와 `spec/mvp-02-onboarding/*`
2.  `mvp-02-mockup.html` (MVP-02 화면)
3.  `core-learning-mockup.html` (두 목업이 다르면 MVP-02 목업을 따른다)

**목업 속 데이터는 예시다.** 예시 문장·설명, 가나 표본, 로마자·한글 표기, 단어 목록, `200` 같은
숫자는 화면 모양을 보이기 위한 값이며 데이터 명세가 아니다. 가나 데이터·표기 규칙은
`03_UI_UX_SPEC.md`의 `가나 학습`, demo 규칙은 같은 문서의 `Demo`가 canonical이다.

**명세와 다른 곳 (명세가 우선한다)**

-   **장음 로마자:** 목업은 장음 부호를 쓴다(`gakkō`, `kōhī`, `okāsan`). 명세는 장음 부호를 쓰지
    않고 가나대로 적거나 모음을 반복한다(`gakkou`, `koohii`, `okaasan`).
-   **번역 표시:** 목업은 `문장 뜻 보기`를 시트로 연다. 명세는 문장 아래 인라인 펼침이며 시트는
    item 설명에만 쓴다(`화면 전환과 시트`).
-   **진도 초기화 확인:** 목업은 확인을 시트로 연다. 명세는 시트가 아닌 그 자리의 확인이다.
-   **로그아웃 뒤 이동:** 목업은 로그인 화면으로 간다. 명세는 선택 홈으로 간다(`로그아웃`).
-   **상단바:** 목업의 demo·가나·Login 화면은 왼쪽에 뒤로 가기 아이콘과 화면 제목을 둔다. 명세는
    모든 화면 왼쪽에 앱 이름(누르면 선택 홈)을, 공개 화면 오른쪽에 `로그인`을 둔다(`상단바`).
-   **후리가나 토글 위치와 모양:** 목업은 Study Screen과 demo의 진행 줄에 `role="switch"`로 둔다. 명세는 두
    화면 모두 상단바에 토글 버튼(`aria-pressed`)으로 둔다.
-   **화면 진입 이동 거리:** 목업은 12px이다. 명세는 10px이다(`화면 전환과 시트`).
-   **선택 홈 카드 1의 `200문장`:** 목업은 숫자를 적어 두었다. 명세는 카드에 문장 수 숫자를 적지 않는다
    (`선택 홈`).
-   **설명 머리의 읽기:** 목업은 기본형(`任せる`)과 그 읽기를 보여준다. 명세는 문장 속 표면형과
    데이터의 `reading`을 짝지어 보여주고 기본형은 따로 적는다(`Explanation`).

파일 머리 주석의 상대 경로(`../guitar-riff-motion.md`)와 `seed/` 문장 번호는 요청 참고 자료
위치(`updates/done/U-001-ui-ux-overhaul/refs/`)에서 작성할 때의 표기다. 이 사본은 원본과 같은 내용이다(후리가나를 `rt` 상시 생성 + documentElement class 전환으로 고친 판을 다시 복사했다).
