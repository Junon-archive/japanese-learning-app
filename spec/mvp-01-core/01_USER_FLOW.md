# User Flow

`Open → 언어 선택 홈 → 언어별 홈 → (로그인 누름) auth → 언어 선택 → create/resume session → sentence → item tap/translation/probe/next → event → mastery/SRS update → next → ~12분 → 완료 → optional +5분`

MVP-02에서 앱을 열면 선택 홈이 먼저 나왔다. **MVP-03에서 그 앞에 언어 선택이 한 단계
생겼다**(사용자 결정 2026-10-01, ADR-025 결정 1·2).

``` text
#/        언어 선택 홈     [일본어] [영어]        + 상단 로그인
#/ja      일본어 홈        [표현 체험] [글자]
#/en      영어 홈          [표현 체험]
```

방문자는 언어를 고른 뒤 그 언어의 Public Demo(또는 일본어의 Kana Learning)로 가고, 사용자는
어느 화면에서든 상단바 `로그인`을 눌러 Private Learning으로 간다(`03_UI_UX_SPEC.md`의
`언어 선택 홈`, `상단바`).

## Private Learning

``` text
App Open
→ 언어 선택 홈 또는 언어별 홈 (로그인 상태를 확인하지 않는다)
→ 상단바 `로그인` 누름
→ Authentication check (GET /api/auth/me, 누를 때만)
   ├─ 로그인되어 있음 → 아래로
   └─ 401 → Login → 성공 → 아래로
→ GET /api/study/session
   ├─ 열린 세션 있음 → 그 세션의 language로 바로 아래로 (언어를 묻지 않는다)
   └─ 없음          → 언어 선택 화면 → 고른 언어로 아래로
→ Today session create/resume (idle timeout 초과 시 새 session)
   열린 세션과 다른 언어를 보내면 409. 조용히 닫지 않는다 (05_API_SPEC.md)
→ Learning Engine이 다음 candidate 선택 → study_presentation 생성
   조회·집계는 전부 그 세션의 language 범위다 (06_LEARNING_ENGINE.md)
→ Sentence displayed (대상 언어 원문 먼저)
→ User reads the target-language sentence first
   ├─ item tap → precomputed explanation (+ reading. 영어는 null이라 그 줄이 없다)
   │             └─ optional known/uncertain/unknown feedback
   ├─ translation reveal
   ├─ (영어만) 문장·예문 소리 재생 — 학습 신호가 아니다
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
-   **영어 화면에만 소리 재생 버튼이 있다**(MVP-03). 브라우저 내장 TTS의 로컬 음성이고, 쓸
    음성이 없으면 버튼이 없다. 재생은 학습 신호가 아니다(`00_SCOPE.md`의 Audio 블록,
    `02_LEARNING_POLICY.md`의 `학습 신호가 아닌 것`, ADR-025 결정 4). 일본어 화면에는 없다.
-   **후리가나 토글은 일본어 화면에만 있다.** 영어 문장에는 ruby가 없다(불변식 23).
-   **로그인 상태 확인은 사용자가 `로그인`을 누를 때만 한다**(불변식 14). 앱을 열 때 자동으로
    확인하지 않는다. API 서버가 꺼져 있어도 공개 화면 여섯(언어 선택 홈, 언어별 홈 둘, demo 둘,
    Kana Learning)은 그대로 쓸 수 있다.
-   Login·Study·History 화면에서 새로고침하면 **언어 선택 홈(`#/`)**으로 돌아온다. 다시
    `로그인`을 누르면 쿠키가 유효하므로 곧바로 `GET /api/study/session`으로 가고, 열린 세션이
    있으면 그 언어로 학습이 이어진다. 로그아웃하면 언어 선택 홈으로 간다(`03_UI_UX_SPEC.md`의
    `상단바`).
-   **학습 중에 언어를 바꾸는 길은 상단바에 없다.** 언어를 바꾸려면 세션을 끝내야 하므로
    (불변식 22) 그 입구는 **완료 화면의 `다른 언어로`** 하나다. 학습 중에 누르기 쉬운 자리에
    세션을 끝내는 버튼을 하나 더 만들지 않는다.

## Public Demo

``` text
Visitor opens app
→ 언어 선택 홈 (로그인 없음) → 일본어 또는 영어 홈
→ `표현 학습 체험해 보기` 카드 (#/ja/demo 또는 #/en/demo)
→ static frontend fixture (seed/<language>/에서 스크립트로 고른 약 200문장, 진입할 때 불러온다)
→ item tap / explanation / translation / self-report / probe / 같은 문장 다시 보기 체험
   (영어 demo에는 소리 재생도 있다. 일본어 demo에는 후리가나 토글이 있다)
→ 진도는 이 브라우저의 localStorage에 저장, 다시 열면 이어서
   언어별로 따로 저장한다 (nc.demo.ja.v1 / nc.demo.en.v1)
→ 모든 문장을 보면 완료 화면 → (일본어) 글자 배우기 / 처음부터 다시
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

가나 학습은 **일본어 전용**이다(불변식 23). 영어 쪽에 대응 화면이 없다.

``` text
Visitor opens app
→ 언어 선택 홈 → 일본어 홈 (로그인 없음)
→ `글자부터 배우기` 카드 (#/ja/kana)
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
