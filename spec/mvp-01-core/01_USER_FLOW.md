# User Flow

`Open → 선택 홈 → (로그인 누름) auth → create/resume session → sentence → item tap/translation/probe/next → event → mastery/SRS update → next → ~12분 → 완료 → optional +5분`

MVP-02에서 앱을 열면 선택 홈이 먼저 나온다. 방문자는 거기서 Public Demo나 Kana Learning으로 가고,
사용자는 상단바 `로그인`을 눌러 Private Learning으로 간다(`03_UI_UX_SPEC.md`의 `선택 홈`,
`상단바`).

## Private Learning

``` text
App Open
→ 선택 홈 (로그인 상태를 확인하지 않는다)
→ 상단바 `로그인` 누름
→ Authentication check (GET /api/auth/me, 누를 때만)
   ├─ 로그인되어 있음 → 아래로
   └─ 401 → Login → 성공 → 아래로
→ Today session create/resume (idle timeout 초과 시 새 session)
→ Learning Engine이 다음 candidate 선택 → study_presentation 생성
→ Sentence displayed (일본어 먼저)
→ User reads Japanese first
   ├─ item tap → precomputed explanation + reading
   │             └─ optional known/uncertain/unknown feedback
   ├─ translation reveal
   ├─ occasional mastery probe (skip 가능)
   └─ next sentence
→ LearningEvent 저장
→ meaningful exposure 확정 / mastery·review state 갱신
→ next sentence 선택
→ ~12분 도달
→ session complete
→ optional +5분
```

-   self-report는 진행에 필수 아님.
-   no-click을 Known으로 처리하지 않음.
-   번역 기본 hidden.
-   reading은 item 설명에서 reveal.
-   후리가나(문장 속 한자의 읽기)는 위 reading과 **별개의 표시 보조**다. 기본은 끄고 사용자가
    켤 수 있으며, 켜도 item 설명의 reading은 그대로 tap 뒤 설명에서 나온다. 후리가나 표시와
    토글은 학습 신호가 아니다(`03_UI_UX_SPEC.md`의 `Translation/Furigana`,
    `02_LEARNING_POLICY.md`의 `학습 신호가 아닌 것 (MVP-02)`).
-   probe는 간헐적이고 skip 가능.
-   MVP에는 audio action이 없다(`00_SCOPE.md`).
-   **로그인 상태 확인은 사용자가 `로그인`을 누를 때만 한다**(불변식 14). 앱을 열 때 자동으로
    확인하지 않는다. API 서버가 꺼져 있어도 선택 홈, Public Demo, Kana Learning은 그대로 쓸 수
    있다.
-   Login·Study·History 화면에서 새로고침하면 선택 홈으로 돌아온다. 다시 `로그인`을 누르면 쿠키가
    유효하므로 곧바로 study session create/resume으로 간다. 로그아웃하면 선택 홈으로 간다
    (`03_UI_UX_SPEC.md`의 `상단바`).

## Public Demo

``` text
Visitor opens app
→ 선택 홈 (로그인 없음)
→ `표현 학습 체험해 보기` 카드 (#/demo)
→ static frontend fixture (seed/에서 스크립트로 고른 약 200문장, 진입할 때 불러온다)
→ item tap / explanation / translation / self-report / probe / 같은 문장 다시 보기 체험
→ 진도는 이 브라우저의 localStorage에 저장, 다시 열면 이어서
→ 모든 문장을 보면 완료 화면 → 글자 배우기 / 처음부터 다시
→ backend API 호출 없음
→ private DB 접근 없음
→ paid LLM call 없음
```

demo 진도는 그 브라우저의 localStorage에만 저장하고 서버로 보내지 않는다(MVP-01의 "browser
memory/session 수준에서만 유지"를 MVP-02에서 바꿨다). backend를 부르지 않으므로 private DB 접근과
paid LLM 호출이 **구조적으로 불가능**하다(`04_SECURITY_AND_DATA.md`의 `Public Demo 구조 (MVP 확정)`,
`localStorage 사용 범위 (MVP-02 확정)`).

demo의 "다시 보기"는 **같은 문장을 다시 보여주는 것**이다. 새 문맥 재등장(contextual review)은
demo가 약속하는 체험이 아니다(`03_UI_UX_SPEC.md`의 `Demo`).

## Kana Learning

``` text
Visitor opens app
→ 선택 홈 (로그인 없음)
→ `글자부터 배우기` 카드 (#/kana)
→ 히라가나 / 가타카나 탭 → 범위 선택 → 글자 표·단어 목록 보기
→ 퀴즈 (보고 읽기 / 보고 고르기), 한 라운드 문항 수는 03_UI_UX_SPEC.md의 가나 학습
→ 틀린 문항은 라운드 끝에 한 번 더
→ 라운드 결과 → 한 번 더 풀기 / 글자 표로 돌아가기
→ 진도는 이 브라우저의 localStorage에 저장
→ backend API 호출 없음
→ 학습 이벤트 없음
```

규칙은 `03_UI_UX_SPEC.md`의 `가나 학습`이다. 가나 학습은 Private Learning의 mastery·SRS와
연결되지 않는다.
