# CC / Agent Implementation Instructions

1.  구현 전 관련 `spec/` 전체를 읽고 implementation plan을 먼저
    작성한다.
2.  MVP In Scope만 구현한다. Future 기능을 선제 구현하지 않는다.
3.  DB 변경은 SQLAlchemy model + Alembic migration으로 관리한다.
4.  PostgreSQL이 사용자 상태의 canonical source다.
5.  Learning Engine이 무엇을/언제 학습할지 결정하고 LLM은 언어
    생성·설명을 담당한다.
6.  핵심 기능은 테스트 없이 완료 처리하지 않는다.
7.  secret, `.env`, DB volume, backup은 Git에 넣지 않는다.
8.  Public Demo는 유료 LLM 호출과 private data 접근을 금지한다.
9.  불확실한 학습 정책값은 configuration으로 둔다.
10. 명세 충돌을 발견하면 기능을 임의 확장하지 않는다.

`05_LEARNING_SYSTEM_VISION`, `06_LLM_ENGINEERING_PRINCIPLES`,
`future/*`는 미래 의도를 보존하지만 MVP 구현 범위를 넓히지 않는다.

`updates/`는 변경 요청이지 명세가 아니다. 요청은 spec-sync가 `spec/`에
반영한 뒤에만 구현한다.

**Global/Future 문서에 숫자나 아이디어가 존재한다는 이유만으로 구현하지
않는다.** MVP 구현 source of truth는 `spec/mvp-01-core/*` +
`spec/mvp-02-onboarding/*`(MVP-02 delta) + `spec/mvp-03-english/*`(MVP-03 delta)다.

특히 다음은 MVP 구현 대상이 아니다: audio/TTS, `ANALYZE_SENTENCE`,
comprehensible-input 난이도 밴드, source mix 비율, Busy/Deadline 모드,
register/sense/multidimensional difficulty, 형태소 분석기, embedding
duplicate detector, golden eval harness, admin UI, export.

위 목록에서 **두 가지가 부분적으로 해제되었다.** 나머지 항목은 그대로 구현 대상이 아니다.

-   **형태소 분석기 (MVP-02).** 콘텐츠를 적재·생성하는 시점에 후리가나를 계산하는 용도에 한해
    허용한다. API 요청 경로와 브라우저에서는 쓰지 않는다(`spec/mvp-02-onboarding/00_SCOPE.md`).
    **MVP-03: `language = 'ja'` 콘텐츠에만 쓴다.** 영어용 분석기·lemmatizer는 도입하지 않는다.
-   **audio/TTS (MVP-03).** **브라우저 내장 `speechSynthesis`의 로컬 음성으로 영어 문장·예문을
    재생하는 것**까지만 허용한다. 서버 TTS, 오디오 파일 생성·저장, audio endpoint, 듣기 probe,
    `listening_mastery` 갱신은 계속 범위 밖이다. 재생은 학습 신호가 아니다
    (`spec/mvp-03-english/00_SCOPE.md`, ADR-025).

## 언어 (MVP-03)

학습 대상 언어는 **일본어와 영어** 둘이다.

-   **언어는 콘텐츠의 축이다.** 엔진·SRS·mastery·이벤트 경로를 언어별로 복제하지 않는다
    (`spec/03_DOMAIN_MODEL.md`의 `Language`, ADR-023).
-   **사용자별 학습 테이블에 `language`를 두지 않는다.** `learning_item_id`가 이미 언어를
    결정한다.
-   **외부 어휘 자료 원본을 커밋하지 않는다.** `data/wordlists/`는 gitignore다. 커밋하는 것은
    선별 결과(`seed/en/*.yaml`), 선별 스크립트, 출처 표기다(ADR-024).
