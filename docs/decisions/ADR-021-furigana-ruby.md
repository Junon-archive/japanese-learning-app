# ADR-021 --- 후리가나(ruby)의 계산·저장·전달

Status: Accepted

Decision: 문장 전체의 후리가나는 **SudachiPy + SudachiDict-core**로 콘텐츠를 적재·생성하는
시점에 한 번 계산해 **`sentences.ruby_json`(JSONB, nullable) 한 컬럼**에 저장한다. 읽기는 **한자
run 단위**로 정렬하고, tappable span 경계를 넘는 ruby는 만들지 않는다. 분석기의 체계적 오독은
**교정 계층**(tappable item의 `explanation.reading` 우선 + 저장소에 커밋된 작은 교정 표)으로 줄인다
(`algorithm_version = 2`). API는 저장값을 `render_segments[].ruby`로 잘라 보내기만 하고 분석기를
import하지 않는다.

``` text
분석기        sudachipy==0.6.11 + sudachidict-core==20260723, SplitMode.C
교정 (v2)     1 tappable item span: explanation.reading으로 run 정렬이 성립하면 그 읽기
              2 그 밖의 토큰: app/furigana.py의 CORRECTION_RULES(표면형 + 앞/뒤 토큰 조건 -> 읽기)
              seed 전체에서 20문장 표본의 틀린 ruby 5 -> 1, explanation.reading 불일치 4 -> 0
배치          worker 이미지 + 호스트 CLI(uv run). API 이미지에는 없다 (dependency group "furigana")
저장          sentences.ruby_json JSONB NULL      NULL = 미계산(또는 계산 실패)
                                                   {"spans": [], ...} = 계산했고 달 읽기가 없다
좌표          [start_codepoint, end_codepoint, reading]  sentence_item_spans와 같은 [start, end)
계산 지점     seed 적재 / worker 저장 직전(검증 통과 후) / backfill 스크립트 / demo fixture 생성
실패          ruby_json = NULL로 두고 문장은 그대로 validated. 관측은 로그와 CLI 출력
payload       render_segments[].ruby: RubyPart[]   []  또는  parts.text 이음 == segment.text
경계 guard    G14: sudachipy는 app/furigana.py에서만, app.furigana는 seed_loader·persistence에서만
```

`spec/`에 반영하기 전까지 구현 근거가 아니다(사용자 결정 2026-09-13). canonical 반영 위치는 끝의
`명세 반영 대상`에 적었다.

---

## 맥락

사용자 결정(2026-09-13, `updates/done/U-003-furigana.md`, `updates/done/U-005-demo-expansion.md`)은 이미 확정이다. 이 ADR이 정하는 것은
그 결정을 구현할 수 있게 하는 다섯 가지다.

1.  어느 분석기와 사전인가(라이선스·wheel·크기·버전 조회)
2.  ruby를 어디에 어떤 모양으로 저장하는가(미계산과 한자 없음의 구분, provenance)
3.  토큰 읽기를 한자 run에 붙이는 결정적 규칙, tappable 경계와 부딪힐 때의 처리
4.  어디서 계산하고, 실패를 어떻게 관측하며, 분석기가 요청 경로에 들어오지 않게 무엇으로 막는가
5.  presentation payload의 모양(Wave 3 `furigana-fe`와 `demo`가 병렬로 소비한다)

지금 코드에서 이 결정이 닿는 자리:

``` text
backend/app/services/seed_loader.py   load_seed()        문장 INSERT
backend/app/jobs/persistence.py       _insert_sentence() 검증 통과 문장 INSERT (DRAFT -> _promote_to_validated)
backend/app/services/presentation.py  _build_view()      build_render_segments(japanese, spans)
backend/app/render.py                 L0 pure. RenderSegment(text, sentence_item_id)
backend/app/schemas/study.py          RenderSegmentPayload(text, sentence_item_id)
frontend/src/types.ts                 RenderSegment
frontend/src/ui/segments.ts           renderSentence(segments, onTapItem)
infra/Dockerfile.backend, .worker     둘 다 uv sync --frozen --no-dev (같은 의존성 집합)
```

---

## 실측 (2026-09-13)

설치 실험은 저장소 밖 임시 환경의 venv(uv 0.12.13, CPython 3.12.14)에서만 했다. `pyproject.toml`과
`uv.lock`은 건드리지 않았다. 실험 스크립트는 저장소에 넣지 않는다.

### SudachiPy + SudachiDict-core

``` text
wheel         sudachipy-0.6.11-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl   1.6 MiB
              sudachidict_core-20260723-py3-none-any.whl                                    68.9 MiB
              사전(system.dic)이 wheel 안에 있다. 설치·실행 중 내려받기가 없다
라이선스      SudachiPy         METADATA License: Apache-2.0
                                wheel에 LICENSE 파일이 없다. 상류 sudachi.rs 저장소 LICENSE = Apache-2.0
              SudachiDict-core  METADATA License: Apache-2.0, dist-info/licenses/LICENSE-2.0.txt
                                상류 LEGAL: 전 파일 Apache-2.0. 일부가 UniDic(BSD-3-Clause,
                                UniDic Consortium)과 NEologd(Apache-2.0)에서 왔다. LEGAL은 wheel에 없다
설치 크기     sudachipy 4.3M, sudachidict_core 208M (system.dic 217,466,039 bytes)
              runtime 의존성 site-packages  88M -> 300M  (+212M)
로드 시간     import 0.012~0.015s, Dictionary(dict="core") 0.020~0.021s (4회), 첫 tokenize < 1ms
              seed 765문장(7,283 토큰) 전체 tokenize 0.014s
메모리        사전 로드 직후 프로세스 RSS 약 80MB(인터프리터 포함). 사전은 mmap이다
버전 조회     importlib.metadata.version("sudachipy")        -> "0.6.11"
              importlib.metadata.version("sudachidict_core") -> "20260723"
              Python API의 Dictionary에는 사전 header 버전 접근자가 없다 (close/create/lookup/
              pos_matcher/pos_of/pre_tokenizer뿐) -> 패키지 메타데이터로 기록한다
좌표          Morpheme.begin()/end()는 code point index다. 𠮟(U+20B9F)와 이모지가 각각 1칸이고
              surface()는 원문 slice와 같다(반각 가나 포함). 같은 입력의 반복 결과가 같다
타입          py.typed가 없다. mypy strict에서 import-untyped 오류 -> import 한 줄에만 ignore
```

### seed 전체에 정렬 규칙 적용 (v1: 아래 `결정 3`의 규칙만, 교정 계층 없음)

중단 판정(tappable 경계 때문에 생략한 토큰이 5%를 넘는 일이 흔하면 멈추고 사용자에게 묻는다, 사용자 결정 2026-09-13)은 **seed 전체 765문장**의 한자 포함 토큰을 분모로, tappable 경계 때문에 생략한 토큰을
분자로 한다.

``` text
문장                          765
한자 포함 토큰                2,097        (분모)
  run 정렬 유일                2,042
  모호 -> 축약 span              0
  불일치 -> 토큰 전체            0
  경계 때문에 생략               0   = 0.00%  (분자, 중단 기준 5%)
    SplitMode.A 재분할로 구제     4   (連絡先, 気分転換, 残業代, 本人確認)
                                     구제가 없었다면 4 / 2,097 = 0.19%
  숫자 규칙으로 생략            55   = 2.62%  (28문장)
  읽기 없음으로 생략             0
ruby span                     2,105
한자 문자                     3,023        그중 읽기가 달린 문자 2,961 (97.9%)
tappable item(한자 포함) 비교   492        한자 없는 item 308은 비교 대상 아님
explanation.reading 불일치       4        전부 お腹が空い/空く: 분석기 あい/あく, 설명 すい/すく (분석기 오류)
```

생략 비율은 중단 조건(5% 초과)에 해당하지 않는다.

### 20문장 표본(정성 확인)과 읽기 오류 경향

이름·날짜어·복수 읽기·숫자·재분할이 섞이게 고른 20문장(`sn_0001 0003 0004 0006 0014 0030 0071 0114
0120 0124 0172 0182 0363 0383 0491 0500 0529 0598 0659 0737`): 한자 포함 토큰 63, 경계 생략 0, 숫자
생략 7, 재분할 구제 3. 표시된 ruby span 60개 중 틀린 읽기 5개(약 8%: 私, 何 두 번, 一日, 空).

``` text
この仕事、田中さんに任せてもいい？      仕事[しごと] 田中[たなか] 任[まか]                맞음
お疲れ様でした。あとは私に任せて…      私[わたくし]                                      틀림(わたし)
何を食べるか、まだ決めていない。        何[なん]                                          틀림(なに)
この量を一日で終わらせるのは無理だ。    一日[ついたち]                                    틀림(いちにち)
お腹が空いた。何か食べよう。            腹[なか] 空[あ] 何[なん]                          空·何 틀림
すみません、この席は空いていますか。    空[あ]                                            맞음
明日は早いから、もう寝なきゃ。          明日[あす]                                        맞음(あした가 더 흔함)
連絡先を交換しませんか。(tappable 連絡) 連絡[れんらく] 先[さき]                           재분할 구제
```

seed 전체에서 같은 표면형의 읽기 분포(분석기 출력):

``` text
私    ワタクシ 16/16        何    ナン 19/19 (何を·何か도 なん)     明日  アス 28/28
一日  ツイタチ 2/2 (기간)   空い  アイ 4 (1 맞음, お腹が空いた 3 틀림)  今日中 今日=コンニチ
一日中 中=チュウ            三十分 -> 三 | 十分(ジュウブン)          一点·一週間 イチ+テン·イチ+シュウカン
이름  田中 タナカ, 山田 ヤマダ 맞음. 사전에 없는 한자(𠮟)는 읽기 = 표면형(한자) -> 생략
```

**오류는 문맥 의존 복수 읽기와 수사+조수사 음변화에 몰려 있다.** 이름·일반 명사·활용형 okurigana는
표본에서 틀린 것이 없었다.

### 대안 확인: fugashi + unidic-lite

라이선스는 허용적이라 대안 확인이 필수는 아니었지만, 위 오류가 Sudachi 고유인지 보려고 같은 방식으로
확인했다.

``` text
fugashi 1.5.2      MIT AND BSD-3-Clause, cp312 manylinux wheel, 1.2M
unidic-lite 1.0.8  MIT + UniDic BSD, **sdist만 있다**(wheel 없음), 설치 249M, UniDic 2.1.2
같은 감사 결과     私 ワタクシ 16/16, 何 ナン 21/21, 明日 アス 28/28, 一日 ツイタチ 2/2,
                   空い アイ 4/4, 三十分 サンジュウ+フン, 一点 イチ+テン
```

두 분석기 모두 UniDic 계열 어휘 읽기를 쓰므로 오류 경향이 같다. 바꿔서 얻는 정확도가 없다.

### 교정 계층 전후 (v1 -> v2, seed 전체 765문장)

같은 임시 환경의 스크립트로 세 변형을 돌렸다: v1(교정 없음), 교정 표만, v2(교정 표 + explanation 우선).

``` text
                                          v1        교정 표만    v2
한자 포함 토큰                             2,097     2,097        2,097
  explanation 읽기로 덮인 토큰               -         -            508
  경계 때문에 생략                           0         0            0     (0.00%)
  재분할 구제                                4         4            4
  숫자 규칙으로 생략                        55        55           55     (2.62%)
  읽기 없음으로 생략                         0         0            0
ruby span                                  2,105     2,105        2,105
읽기가 달린 한자 문자                       2,961     2,961        2,961  / 3,023
explanation 정렬 성립 item                   -         -            492 / 492
explanation.reading 불일치                   4         0            0
  (v2: 정렬 불성립 item의 분석기 읽기 불일치 0, 정렬 성립 item에서 교정 후 분석기와 다른 것 0)
v1 대비 읽기가 바뀐 ruby span                -         68           68
20문장 표본의 틀린 ruby                      5         1            1     (남은 것: 一日[ついたち])
```

교정 표 규칙별 결과(seed 전체). "적중"은 조건이 맞은 토큰 수, "변경"은 v1 읽기와 달라진 수다. 적중한
토큰을 전부 문장과 함께 눈으로 확인했고 틀린 교정은 없었다.

``` text
규칙                                   적중   변경   v1 읽기 -> 교정 읽기     확인한 문맥
私 -> わたし                             16     16     わたくし -> わたし       16개 전부 평서·구어체
明日 -> あした                           28     28     あす -> あした           28개 전부 일상 대화
今日 -> きょう                           34      1     こんにち -> きょう       今日中. 나머지 33은 이미 きょう
何 + 다음 토큰 {を,が,も,か} -> なに      17     17     なん -> なに             何を 4, 何か 7, 何が 2, 何も 4
                                                                                 (何です 2는 조건 밖이라 なん 유지 = 맞음)
中 + 앞 토큰 今日 -> じゅう                1      1     ちゅう -> じゅう         今日中
中 + 앞 토큰 日 -> じゅう                  1      1     ちゅう -> じゅう         一日中
                                                                                 (会議中·旅行中·試験中·ダイエット中은 ちゅう 유지 = 맞음)
空い + 앞 토큰 お腹,が -> すい             3      3     あい -> すい             お腹が空いた/空いて (席は空いて는 あい 유지)
空く + 앞 토큰 お腹,が -> すく             1      1     あく -> すく             お腹が空くと
```

-   v2에서 `空い`/`空く` 규칙의 적중은 0이다. 네 문장 모두 `お腹が空い(く)`가 tappable item이라 explanation
    읽기가 먼저 덮었다. 결과 읽기는 교정 표만 쓴 경우와 같다. 규칙은 탭할 수 없는 자리의 같은 표현을 위해
    남긴다.
-   **v2에서 explanation 우선 계층이 교정 표 결과를 바꾼 span은 0이다.** seed의 explanation 읽기와 교정 후
    분석기 읽기가 492 item 전부에서 같았다. 교정 표 없이 explanation만 쓰면 불일치 4건(お腹が空い)은
    explanation 쪽으로 고쳐지고 탭할 수 없는 私·何·明日는 그대로 남는다. 두 계층은 서로 다른 자리를 덮는다.
-   `一日`(ツイタチ 2/2, 기간 뜻)은 규칙을 넣지 않았다. 뒤 토큰(`で`, `休み`)으로 날짜와 기간을 가르는
    규칙은 seed 두 문장에 맞춘 추측이다.

---

## 결정 1 --- 분석기: SudachiPy 0.6.11 + SudachiDict-core 20260723, SplitMode.C

-   **라이선스가 허용적이다.** 둘 다 Apache-2.0이고 사전에 섞인 UniDic 부분은 BSD-3-Clause다.
    허용적 라이선스가 없으면 멈춘다는 중단 조건에 해당하지 않는다.
-   **Python 3.12 x86_64 wheel이 있고 사전이 wheel에 들어 있다.** 이미지 빌드와 실행에 네트워크
    내려받기가 없고 `uv.lock`의 해시로 고정된다.
-   **버전을 정확히 고정한다(`==`).** `fsrs==6.3.2`와 같은 취급이다. 사전 버전이 바뀌면 같은 문장의
    ruby가 달라지고, demo fixture 일치 테스트가 그 변화를 잡는다. 사전 갱신은 `uv.lock` 변경 +
    fixture 재생성을 한 커밋으로 한다. 이미 저장된 행을 다시 계산하는 수단은 지금 없으며(`한계`), 사전을
    올리는 변경이 그 수단을 함께 설계한다.
-   **`ruby_json`에 적는 분석기·사전 버전은 `app/furigana.py`의 코드 상수(`ANALYZER_VERSION`, `DICTIONARY_VERSION`)다
    (Wave 2 보완 결정, 2026-09-13).** `backend/app/`은 `importlib`을 쓰지 않으므로(ADR-015 G13) 실행 중에 설치
    버전을 조회하지 않고, 이 guard에 예외를 열지 않는다. 대신 테스트가 `importlib.metadata`로 설치 버전과 두
    상수를 대조한다. 그래서 `uv.lock`으로 버전을 올리는 커밋은 상수도 함께 올려야 테스트가 통과한다.
-   **SplitMode.C**(가장 긴 단위)로 토큰화한다. 복합어 읽기(本棚 ほんだな의 연탁)는 긴 단위가
    정확하다. 짧은 단위(A)는 경계 충돌을 풀 때만 조건부로 쓴다(`결정 3`).
-   `sudachidict-core`는 `full`보다 작고(고유명사 확장 없음) 이름 표본(田中, 山田)은 core로 맞았다.

---

## 결정 2 --- 데이터 모델: `sentences.ruby_json` JSONB nullable 한 컬럼

### 모양

``` json
{
  "algorithm_version": 2,
  "analyzer":   {"name": "sudachipy",        "version": "0.6.11"},
  "dictionary": {"name": "sudachidict_core", "version": "20260723"},
  "split_mode": "C",
  "computed_at": "2026-09-13T09:00:00Z",
  "spans": [[5, 7, "たなか"], [10, 11, "まか"]],
  "omitted": {"tappable_boundary": 0, "numeric": 0, "no_reading": 0},
  "corrected": {"explanation_tokens": 1, "table_rules": 0}
}
```

``` text
컬럼          sentences.ruby_json  JSONB  NULL 허용, default 없음
NULL          미계산. 아직 계산하지 않았거나 계산이 예외로 끝났다. backfill의 대상이다
spans = []    계산했고 달 읽기가 없다(한자가 없거나 전부 생략). backfill 대상이 아니다
spans[i]      [start_codepoint, end_codepoint, reading]  start 오름차순, 서로 겹치지 않는다
reading       히라가나 비어 있지 않은 문자열 (U+3041..U+3096, ゝ ゞ ー)
omitted       사유 세 개의 토큰 수. 키 세 개는 값이 0이어도 항상 있다
corrected     explanation_tokens = explanation 읽기로 덮인 분석기 토큰 수
              table_rules        = 교정 표 규칙이 적중한 토큰 수 (결정 3a). 두 키는 항상 있다
computed_at   UTC ISO-8601. 호출자가 주입한 now (ADR-007: 계산 모듈이 시계를 읽지 않는다)
```

-   **원문 `sentences.japanese`와 `sentence_item_spans`는 바꾸지 않는다.** ruby는 옆 컬럼이다.
-   **migration은 `ADD COLUMN ruby_json JSONB NULL` 하나다.** default가 없는 nullable 컬럼 추가는
    PostgreSQL에서 테이블을 다시 쓰지 않는다. 기존 학습 기록은 건드리지 않는다(`updates/done/U-003-furigana.md`의 불변식 19).
    additive migration만으로 저장할 수 없으면 멈춘다는 중단 조건에 해당하지 않는다.
-   **provenance는 이 값 안에 둔다.** `sentences.provenance_json`에 넣지 않는다 --- 그 컬럼은 생성
    provenance(provider/model/prompt_version)이고 seed 행은 `{}`다. backfill이 그 컬럼을 고치게 되면
    생성 기록과 표시 보조의 기록이 한 값에 섞인다.
-   **`algorithm_version`**은 `결정 3`과 `결정 3a`(교정 표 내용 포함)의 규칙 버전이다.
    `mastery_algorithm_version`, `fsrs_params_version`과 같은 방식이다. 정렬 규칙이나 교정 표가 바뀌면 1씩
    올린다. 1은 교정 계층이 없는 규칙이며 **배포된 적이 없다.** 첫 배포 값은 2다.
-   **Python `None`은 SQL NULL로 저장한다(Wave 2 보완 결정, 2026-09-13).** 컬럼 매핑을 `JSONB(none_as_null=True)`로
    둔다. 기본 매핑은 `None`을 JSON `null` 값으로 써서 `ruby_json IS NULL`(미계산 판정, backfill 대상)에 걸리지
    않는 행이 생긴다.
-   **DB CHECK를 두지 않는다.** 실제로 지켜야 하는 무결성(원문 길이 안, 겹침 없음, tappable 경계
    안)은 다른 컬럼·테이블과 대조해야 해서 CHECK로 표현되지 않는다. `sentence_item_spans`도 원문
    대조를 애플리케이션 검증으로 한다. 같은 검증 함수를 계산 시점과 표시 시점에 **둘 다** 부른다
    (`결정 5`의 `ruby.invalid_stored`).

### 판정 기준별 비교

``` text
기준                       JSONB 컬럼(채택)                       별도 테이블 sentence_ruby_spans
additive                   ADD COLUMN 1개                          CREATE TABLE 1개 (둘 다 가능)
좌표                       같은 codepoint [start, end)             같다
원문 불변                  같다                                    같다
미계산 vs 한자 없음        NULL vs spans=[]  (한 컬럼으로 표현)    행 0개가 둘 다를 뜻한다
                                                                   -> 문장별 상태 행/테이블이 하나 더 필요
provenance 위치            같은 값 안                              상태 테이블 또는 행마다 반복
무결성                     애플리케이션 검증 (CHECK 불가)          start>=0, end>start만 CHECK 가능.
                                                                   원문·tappable 대조는 여전히 앱 검증
조회 비용                  _build_view가 이미 읽는 Sentence 행에   presentation마다 쿼리 1개 추가
                           들어 있다. 추가 쿼리 0
backfill 멱등              WHERE ruby_json IS NULL                  상태 테이블 LEFT JOIN
쓰기                       문장당 UPDATE/INSERT 1회                 문장당 span 수만큼 INSERT
```

**결정 요인은 "미계산과 한자 없음의 구분"이다(Wave 1 보완 결정, 2026-09-13).** 별도 테이블은 행이 없다는 사실로 둘을 가를 수
없어 문장별 상태를 담는 두 번째 구조가 필요해지고, 그러면 그것이 사실상 이 컬럼이다.

---

## 결정 3 --- 한자 run 정렬 규칙 (v1에서 정하고 v2에서도 그대로 쓴다)

### 문자 분류

``` text
한자 문자  U+3400..U+4DBF  U+4E00..U+9FFF  U+F900..U+FAFF  U+20000..U+3FFFF
           U+3005 々  U+3006 〆  U+3007 〇  U+30F5 ヵ  U+30F6 ヶ
가나 변환  U+30A1..U+30F6 (ァ..ヶ) -> 코드포인트 -0x60 (ぁ..ゖ). ー와 그 밖의 문자는 그대로
숫자       ASCII 0-9, 전각 ０-９
```

-   범위를 **코드포인트 목록으로 고정한다.** `unicodedata`는 Python minor마다 Unicode 버전이 달라져
    같은 입력의 판정이 갈릴 수 있다.
-   々 〆 〇 ヶ ヵ는 한자 run에 붙는다. `時々`는 run 하나 `ときどき`가 된다. `東京ヶ丘`의 ヶ는
    Sudachi가 별도 토큰(ガ)으로 내므로 `ヶ[が]`가 된다.

### 토큰 하나의 처리 (SplitMode.C 토큰 순서대로)

``` text
0  표면형에 한자 문자가 없다                         -> 건너뜀 (세지 않는다)
   (v2) 한자 문자가 전부 explanation span에 덮였다    -> 건너뜀 (corrected.explanation_tokens로 센다)
1  reading = 가나변환(reading_form())
   (v2) 교정 표 규칙이 적중하면 reading = 규칙의 읽기 (결정 3a)
   reading이 위 히라가나 조건을 어긴다               -> 생략 no_reading
     (사전에 없는 한자는 reading_form이 표면형 그대로다. is_oov는 판정에 쓰지 않는다 ---
      Sudachi는 한자 수사(三, 十万)를 OOV로 표시하면서 읽기는 정상으로 준다)
2  숫자 규칙: 다음 중 하나                           -> 생략 numeric
     a. part_of_speech()[1] == "数詞"
     b. 표면형에 숫자 문자가 있다
     c. 바로 앞 토큰(prev.end == begin)이 a에 해당하고 이 토큰에 한자가 있다
3  표면형을 한자 run / 비한자 run으로 자르고 정렬을 모두 찾는다(2개까지)
     비한자 run: 가나변환(그 run) 이 reading의 그 자리와 글자 그대로 같아야 한다
     한자 run:   reading의 비어 있지 않은 연속 부분 문자열 하나
   정렬이 정확히 1개      -> 한자 run마다 span [begin+run_start, begin+run_end, 부분 읽기]
   정렬이 2개 이상 (모호) -> span 1개: 첫 한자 run 시작 ~ 마지막 한자 run 끝,
                              읽기 = reading에서 앞뒤 비한자 run 글자를 뗀 것
   정렬이 0개 (불일치)    -> span 1개: 토큰 전체 [begin, end), 읽기 = reading 전체
4  경계 검사: 만든 span 전부가 모든 tappable span T=[s, e)에 대해
     (span ⊆ T) 또는 (span ∩ T = ∅)                  -> 통과, 채택
5  4를 어기면 재분할 시도:
     subs = morpheme.split(SplitMode.A), len(subs) > 1 이고
     이음(가나변환(sub.reading_form())) == reading 일 때만
     각 sub에 0, 3을 적용해 만든 span 전부가 4를 통과  -> 그 span들을 채택 (구제, 생략 아님)
   그 밖                                             -> 그 토큰의 ruby 전부 생략 tappable_boundary
6  (v2) 채택한 span 중 explanation span과 한 글자라도 겹치는 것은 버린다 (explanation이 이긴다)
```

-   **결정적이다.** 입력은 원문, tappable span 목록, 고정 버전 사전뿐이고 난수·시계·설정이 없다.
-   **okurigana는 3에서 분리된다.** `任せ マカセ` -> `任[まか]`, `お疲れ様でした`의 `疲[つか]`
    `様[さま]`, `大人しい オトナシイ` -> `大人[おとな]`.
-   **모호/불일치는 토큰 단위로 단다(사용자 결정).** 모호는 앞뒤 okurigana만 뗀 축약 span이다 ---
    정렬이 둘 이상이면 앞뒤 비한자 run은 정의상 reading과 맞았으므로 떼는 것이 항상 가능하다.
    seed에서는 둘 다 0건이었다. 합성 입력으로 동작만 확인했다(`赤か青 あかかあお` -> 축약,
    `1人 ヒトリ` -> 숫자 규칙 이전에는 불일치 경로).
-   **재분할(5)은 생략을 줄이는 결정적 단계다.** tappable span이 복합어 한가운데를 자르는 경우
    (`連絡先`에서 tappable `連絡`) 짧은 단위 읽기로 다시 단다. **읽기 이음이 원래 읽기와 글자 그대로
    같을 때만** 쓰므로 연탁 오류가 들어오지 않는다: `本棚 ホンダナ`는 A 분할이 `ホン + タナ`라서
    구제하지 않고 생략한다.
-   **숫자 규칙은 경계 생략과 별개의 생략 사유다.** 수사와 뒤따르는 조수사의 음변화(一点 いってん,
    一週間 いっしゅうかん, 三十分 さんじゅっぷん)를 사전 읽기 이음이 틀리게 내고, 토큰화 자체가 틀리기도
    한다(三十分 -> 三 | 十分 じゅうぶん). seed 28개 수사 묶음 중 6개가 틀린 읽기였다. 틀린 후리가나는
    읽기를 잘못 가르치므로 **틀릴 수 있는 묶음 전체를 달지 않는다.** 음변화 표를 만들지 않는다 ---
    그것은 읽기 엔진을 새로 짓는 일이다. 이미 한 토큰으로 사전에 있는 수 표현(一人 ひとり, 二人
    ふたり, 二十歳 はたち)은 2a에 걸리지 않으므로 달린다.
-   **생략은 그 토큰의 한자 전부를 비워 둔다.** 부분만 남기지 않는다.

### tappable span의 범위

4의 검사 대상은 그 문장의 **`is_tappable = true`인 sentence_item의 span 전부**다. non-tappable
item의 span은 렌더링에서 일반 텍스트로 흐르므로(`app/render.py`) 경계가 아니다. 이 조건을
만족하면 모든 ruby span은 **`build_render_segments`가 만드는 segment 하나 안에** 들어간다 ---
일반 텍스트 segment는 인접한 tappable span 사이의 최대 구간이기 때문이다.

---

## 결정 3a --- 교정 계층 (`algorithm_version = 2`)

분석기의 오독은 무작위가 아니라 **표면형별로 체계적**이다(`실측`). 새 의존성·LLM 없이 결정적으로 줄이는
두 계층을 `결정 3` 앞뒤에 둔다. 적용 순서는 **1 explanation 우선 -> 2 교정 표 -> 결정 3의 나머지**다.

### 계층 1 --- tappable item span은 `explanation.reading` 우선

``` text
대상      is_tappable = true 이고 surface_form에 한자 문자가 있는 item
입력      그 item의 span들을 span_order 순으로 이은 code point 위치 목록 P
          읽기 R = 가나변환(explanation.reading에서 NFKC -> 모든 공백 제거)
run       P의 글자를 한자/비한자로 자르고, **span 경계마다 자른다** (위치가 이어지지 않는 불연속 span 경계뿐
          아니라 위치가 이어지는 span 경계에서도 자른다. 그래서 run이 항상 span 하나 안에 있다.
          Wave 2 보완 결정, 2026-09-13)
정렬      결정 3의 3과 같은 방식으로 R에 대해 정렬을 찾는다(2개까지)
          정확히 1개이고 모든 부분 읽기가 히라가나 조건을 만족 -> 한자 run마다 explanation span
          0개 또는 2개 이상                                  -> 이 item은 계층 1을 쓰지 않는다
결과      explanation span은 item span 안에 있으므로 tappable 경계 검사를 항상 통과한다
          그 글자를 덮는 분석기 span은 버린다 (결정 3의 0, 6)
```

-   **explanation 행의 출처.** 세 계산 지점 모두 DB 쓰기 없이 읽을 수 있음을 코드에서 확인했다.

    ``` text
    seed 적재   seed/sentences.yaml의 items[].explanation.reading   (loader가 필수로 파싱한다)
    worker      SentencePayload.items[].explanation.reading          (_insert_sentence가 같은 payload로
                                                                     SentenceItemExplanation을 만든다.
                                                                     tappable item은 Ready invariant상 반드시 있다)
    backfill    sentence_item_explanations.reading (status = validated) 중 id가 가장 작은 행
                (EXPLAIN_ITEM 재실행으로 validated 행이 둘일 수 있다. 결정적으로 하나를 고른다)
    fixture     seed YAML (seed 적재와 같다)
    ```

-   **`explanation.reading`은 "문장 속 표면형의 읽기"다.** 예: 표면형 `任せ`의 읽기는 `まかせ`이고 기본형
    `任せる`의 읽기(`まかせる`)가 아니다. seed 데이터가 이 정의를 따른다. 계층 1은 이 정의에 기댄다.
    spec-sync가 `04_DB_SPEC.md` 또는 `08_LLM_SPEC.md`에 한 줄로 적는다.
-   **정의가 prompt에 있는 곳은 `EXPLAIN_ITEM` 하나다.** 현재 주 생성 경로인 `GENERATE_SENTENCE_BATCH`와
    `GENERATE_REVIEW_CONTEXT`의 prompt에는 `reading`의 정의가 없고, 요청의 target item에는 기본형 읽기
    (`learning_items.reading`)가 실린다. 그래서 **생성 문장에서는 설명 읽기가 기본형으로 올 가능성이 크다.**
-   **이 계층은 설명 데이터를 고치지 않는다.** ruby 계산의 입력으로 쓸 뿐 `explanation.reading`은 그대로다.
    "자동으로 고치지 않는다"(사용자 결정)는 설명 데이터를 고치지 않는다는 뜻이며 그대로 지킨다.
-   **정렬이 성립하지 않는 경우**(설명이 표면형이 아니라 기본형 읽기를 적었다, 기호가 섞였다 등)는 분석기
    읽기를 쓰고 아래 불일치 판정의 `reading_mismatch`로 보고한다. prompt는 바꾸지 않는다.
-   seed에서는 한자가 든 tappable item 492개가 **전부** 정렬되었다(토큰 508개가 덮였다).

### 계층 2 --- 교정 표 `CORRECTION_RULES`

``` python
@dataclass(frozen=True)
class CorrectionRule:
    surface: str                              # SplitMode.C 토큰 표면형과 글자 그대로 같다
    reading: str                              # 그 토큰 전체의 읽기(히라가나). 결정 3의 정렬에 들어간다
    prev: tuple[str, ...] = ()                # 바로 앞 토큰들의 표면형(끝이 바로 앞). 끊김 없이 이어져야 한다
    next_in: frozenset[str] = frozenset()     # 비어 있지 않으면 바로 다음 토큰 표면형이 이 안에 있어야 한다

CORRECTION_RULES: tuple[CorrectionRule, ...] = (
    CorrectionRule("私", "わたし"),
    CorrectionRule("明日", "あした"),
    CorrectionRule("今日", "きょう"),
    CorrectionRule("何", "なに", next_in=frozenset({"を", "が", "も", "か"})),
    CorrectionRule("中", "じゅう", prev=("今日",)),
    CorrectionRule("中", "じゅう", prev=("日",)),
    CorrectionRule("空い", "すい", prev=("お腹", "が")),
    CorrectionRule("空く", "すく", prev=("お腹", "が")),
)
```

``` text
적용 위치   결정 3의 1 (reading_form을 가나변환한 직후). 그 뒤 no_reading·숫자·정렬·경계·재분할은 그대로
판정        표 순서대로 보고 처음 적중한 규칙 하나만 쓴다
재분할      결정 3의 5는 교정된 reading과 A 분할 읽기 이음을 비교한다 (다르면 구제하지 않는다)
```

-   **위치는 `backend/app/furigana.py`의 코드 상수다.** `config/` 아래 데이터 파일로 두지 않는다.
    -   `config/`는 API·worker가 전 키를 읽어 검증하는 **학습 정책** 파일 자리이고, production은 그 파일의
        전체 사본을 `/etc` 아래에 둔다(`14_CONFIGURATION.md`의 `production override`). 교정 표를 거기 두면
        배포마다 사본과 어긋날 수 있는 두 번째 파일이 생기고, 운영자가 표를 바꿔도 `algorithm_version`이
        오르지 않는다.
    -   교정 표는 `algorithm_version`과 demo fixture 일치 테스트에 묶인 **알고리즘의 일부**다. 같은 파일,
        같은 커밋에서 바뀌어야 한다.
    -   **학습 정책값이 아니므로 `14_CONFIGURATION.md`의 대상이 아니다.** 실사용 후 튜닝하는 값이 아니라
        읽기의 사실 교정이고, API·worker의 config 로더가 읽지 않는다.
-   **규칙을 넣는 조건.** seed 전체에서 **적중한 토큰을 문장과 함께 전부 확인했고 틀린 교정이 0**이며,
    변경이 1건 이상인 것만 넣는다. 추측 규칙(seed에서 확인할 수 없는 문맥 판단)은 넣지 않는다.
    -   `一日`(날짜 ついたち / 기간 いちにち)은 넣지 않았다. seed 두 문장은 둘 다 기간이지만 뒤 토큰(`で`,
        `休み`)으로 가르는 규칙은 그 두 문장에 맞춘 추측이다.
    -   `何`의 `と`(なんと / なにと), `で`(なんで / なにで), `の`는 조건에 넣지 않았다. seed에 없거나 뜻에 따라
        갈린다.
-   **규칙을 바꾸는 절차.** 표를 고치는 커밋은 (1) `algorithm_version`을 올리고 (2) seed 전체의 규칙별
    적중·변경 목록을 커밋 설명에 적고 (3) demo fixture를 재생성하고 (4) **이미 저장된 행을 다시 계산하는
    수단을 그 변경에서 함께 설계한다.** 지금의 backfill은 NULL 행만 채운다(`버린 대안`).

### `explanation.reading` 불일치 판정 (v2)

``` text
대상        is_tappable = true 이고 surface_form에 한자 문자가 있는 item
분석기 읽기 계층 1을 뺀 계산(교정 표는 포함)의 ruby로 item span을 훑는다
              ruby span이 i에서 시작하고 그 span 안에서 끝남 -> 그 읽기를 붙이고 끝으로 건너뜀
              한자 문자(ruby 없음)                           -> 비교 불가(세고 넘어간다)
              그 밖                                          -> 가나변환(그 문자)
설명 읽기   NFKC -> 모든 공백 제거 -> 가나변환
보고 두 종류
  reading_mismatch      계층 1 정렬 불성립 + 두 읽기가 다르다   -> 저장된 ruby는 분석기 읽기
  explanation_override  계층 1 정렬 성립   + 두 읽기가 다르다   -> 저장된 ruby는 explanation 읽기
비교 불가   다음 item은 비교하지 않고 uncomparable_items로 센다 (Wave 2 보완 결정, 2026-09-13)
              분석기 읽기에 ruby 없는 한자 문자가 남은 item
              validated 설명이 없는 tappable item (설명 읽기 없음. 계층 1도 쓰지 않고 span은 tappable
              경계로만 쓴다. 빈 설명과의 불일치를 보고하지 않기 위해서다)
            uncomparable_items는 계산 결과(compute_ruby 반환값)의 관측 값이며 CLI 요약 줄과 로그 필드에는 없다
```

-   결과는 **stdout(CLI)과 로그로만** 낸다. DB에 저장하지 않는다. 설명 데이터를 자동으로 고치지 않는다.
-   `explanation_override`를 따로 보고하는 이유: **생성 문장의 `explanation.reading`은 LLM 출력이다.**
    구조 검증은 거쳤지만 읽기의 정확성은 검증되지 않았다. 설명이 틀리고 분석기가 맞는 경우 계층 1이 틀린
    읽기를 ruby에 올린다. 그 사건이 관측되어야 한다.
-   seed 결과: v1 불일치 4(전부 분석기 오류, お腹が空い) -> v2 `reading_mismatch` 0, `explanation_override` 0
    (교정 표가 먼저 같은 읽기를 냈다).

---

## 결정 4 --- 계산 지점, 실패, 관측, 모듈 경계

### 모듈

``` text
backend/app/render.py     L0 (기존, pure 유지)
                          RubySpan(start_codepoint, end_codepoint, reading)
                          RubyPart(text, reading | None)
                          RubySpanError(RenderSpanError)
                          validate_ruby_spans(japanese, ruby, tappable_spans)
                          build_render_segments(japanese, spans, ruby=None)
                            -> RenderSegment(text, sentence_item_id, ruby: tuple[RubyPart, ...])
backend/app/furigana.py   L1 (신규). L0 + sudachipy만 import. DB·설정·시계를 모른다
                          문자 분류, 가나 변환, 결정 3의 정렬, 결정 3a의 교정 계층(CORRECTION_RULES),
                          사전 어댑터, ruby_json 값 조립, explanation.reading 불일치 판정
                          ALGORITHM_VERSION = 2
                          load_analyzer()                       사전을 한 번 적재 (프로세스 내 캐시)
                          compute_ruby(japanese, items, *, now) -> RubyComputation
                            items: tappable item마다 (sentence_item 식별자, span 목록, explanation.reading)
                            -> spans, omitted, corrected, rule별 적중 수, 불일치 목록(두 종류)
```

-   **정렬과 사전 어댑터를 한 파일에 둔다.** 정렬 함수의 소비자는 어댑터 하나뿐이고, 사전은 호스트
    테스트 환경에 항상 있다(`결정 6`의 기본 group). 정렬 단위 테스트는 토큰 dataclass를 직접 만들어
    넣는다(모호·불일치처럼 사전이 잘 내지 않는 입력). 파일을 나누면 소비자 하나를 위한 경계가 생긴다.
-   **검증과 segment 분할은 `render.py`에 둔다.** API가 import해야 하고, 그 모듈의 기존 원칙("판정
    기준이 갈리면 검증을 통과한 문장이 렌더링에서 터진다")이 그대로 적용된다. `furigana.py`는 계산
    결과를 저장하기 전에 같은 `validate_ruby_spans`를 부른다.
-   함수 이름은 구현이 조정할 수 있다. 바꾸지 않는 것은 위 책임 배치와 `결정 5`의 payload다.

### 계산 지점

``` text
1 seed 적재      services/seed_loader.load_seed()  문장마다 compute_ruby -> Sentence(ruby_json=...)
                 같은 트랜잭션. 실패한 문장은 ruby_json = NULL로 적재를 계속한다
2 worker 생성    jobs/persistence._insert_sentence()  Sentence(...) 생성 직전, payload의 tappable item
                 (span + explanation.reading)으로
                 검증(08_LLM_SPEC의 13항목)은 이미 끝났다. ruby는 검증 항목이 아니다
                 _promote_to_validated는 ruby_json을 보지 않는다 (Ready invariant 불변)
3 backfill       scripts/backfill_ruby.py  (아래)
4 demo fixture   demo 레인의 생성 스크립트가 compute_ruby + render.build_render_segments를 그대로 쓴다
                 fixture의 segment.ruby는 API와 같은 함수가 만든 값이다
```

-   **`EXPLAIN_ITEM`은 다시 계산하지 않는다.** 문장·span을 바꾸지 않는다. `GENERATE_REVIEW_CONTEXT`는
    같은 `save_sentences`를 지나므로 2에 포함된다.
-   **prompt와 structured output 스키마는 바꾸지 않는다.** LLM이 읽기를 만들지 않는다.
-   계산은 문장당 1ms 미만의 CPU 작업이고 provider 호출이 아니므로, persistence의 트랜잭션 안에서
    해도 ADR-015 결정 5("provider 호출 중 트랜잭션 금지")와 부딪히지 않는다. 사전 적재는 부팅에서
    끝낸다(아래).

### 실패 두 종류

``` text
per-sentence 예외   compute_ruby가 던짐 (예상 밖 입력, 검증 실패 등)
                    -> ruby_json = NULL, 문장은 정상 저장·validated. ready를 막지 않는다
                    -> 로그 ruby.failed. backfill이 다음 실행에서 다시 시도한다
분석기 부재         sudachipy import 실패, 사전 적재 실패
                    -> worker 진입점(scripts/run_worker.py)이 부팅에서 load_analyzer()를 부르고
                       예외를 잡지 않는다. worker가 뜨지 않는다 (fail-closed)
                    -> seed CLI, backfill CLI도 시작에서 실패한다
```

-   **둘을 가르는 이유:** 사용자 결정 "계산 실패는 ready를 막지 않는다"는 문장 단위 표시 보조의
    실패를 말한다. 분석기가 이미지에 없는 것은 **배포 결함**이고, 그것을 문장마다 NULL로 흡수하면
    worker가 몇 주 동안 후리가나 없는 문장만 쌓아도 아무도 모른다. 부팅 실패는 배포 직후 로그에서
    바로 보인다. `LLM_PROVIDER` 누락을 부팅 실패로 둔 것(ADR-016)과 같은 판단이다. worker가 뜨지
    않는 동안 학습 세션은 Ready Pool로 계속된다.

### 관측 (`11_OBSERVABILITY.md`의 MVP-02 추가 절)

기존 닫힌 집합(`job.*`, `provider.call`, `pool.ready_size`, `cost.*`)과 `generation_jobs.result_ref`
구조는 바꾸지 않는다. 문장 텍스트·읽기 문자열은 로그에 남기지 않는다(생성 콘텐츠 원문 금지 규칙).

``` text
worker  ruby.computed              info     sentence_id, algorithm_version, spans, omitted_tappable_boundary,
                                            omitted_numeric, omitted_no_reading,
                                            corrected_explanation_tokens, corrected_table_rules
        ruby.failed                warning  sentence_id, error (observability.describe_error)
        ruby.reading_mismatch      info     sentence_id, sentence_item_id
        ruby.explanation_override  info     sentence_id, sentence_item_id
        ruby.log_failed            warning  sentence_id, error_type   (위 ruby 로그 단계에서 예외가 났다.
                                            예외 타입 이름만 싣는다. 문장 저장·promote를 막지 않는다.
                                            Wave 2 보완 결정, 2026-09-13)
API     ruby.invalid_stored        warning  sentence_id   (저장값이 validate_ruby_spans를 통과 못 함)
CLI     seed / backfill / fixture 생성의 stdout 요약 + 규칙별 적중 + 불일치 목록
        ruby: algorithm_version=2 sentences=N computed=N failed=N omitted_tappable_boundary=N
              omitted_numeric=N omitted_no_reading=N corrected_explanation_tokens=N
              corrected_table_rules=N reading_mismatches=N explanation_overrides=N kanji_tokens=N
              (kanji_tokens = 생략 비율의 분모인 한자를 포함한 토큰 수. 줄 끝. Wave 2 보완 결정, 2026-09-13)
        rule 私->わたし hits=N  (CORRECTION_RULES 순서대로 한 줄씩, 0이어도 출력)
        rule 中->じゅう prev=今日 hits=N          조건 있는 규칙은 prev=(앞 토큰, 쉼표로 이음)와
        rule 何->なに next=か|が|も|を hits=N     next=(다음 토큰 후보, 정렬해 |로 이음)를 덧붙인다.
                                                 같은 표면형 규칙이 여러 줄이어도 구분된다 (Wave 2 보완 결정, 2026-09-13)
        mismatch kind=<reading_mismatch|explanation_override> sentence=<seed_id 또는 id>
                 item=<sentence_item_id> surface=<표면형> explanation=<설명 읽기> analyzer=<분석기 읽기>
        (운영자 터미널 출력이다. 로그 파일이 아니므로 텍스트를 싣는다)
DB      SELECT count(*) FROM sentences WHERE ruby_json IS NULL   = 미계산 잔량 (새 테이블 없음)
```

### backfill 스크립트 (`scripts/backfill_ruby.py`)

`scripts/db_migrate.py`와 같은 형태다.

``` text
1 대상 출력     pg_tools.describe_target(dsn)  password를 가린 DSN, 현재 ALGORITHM_VERSION
2 대상 조회     WHERE ruby_json IS NULL ORDER BY id
                그 문장들의 tappable span과 explanation.reading(validated 중 최소 id)
3 계산          메모리에서만. 요약, 규칙별 적중, 불일치 목록 출력. 계산 실패 수 F를 센다
                실패한 문장은 "failed sentence=<id> error=<예외 타입 이름>" 한 줄. 예외 메시지는 싣지 않는다
                (Wave 2 보완 결정, 2026-09-13)
4 dry-run       --apply가 없으면 "dry-run: nothing written" 을 출력하고 끝낸다
                F > 0 이면 exit 2, 아니면 exit 0
0 인자 확인     --apply인데 --pg-bin이 없으면 분석기 적재·DB 접속 전에 exit 2로 끝난다
                (계산을 다 한 뒤 백업 단계에서야 실패하지 않게. Wave 2 보완 결정, 2026-09-13)
5 --apply       쓸 행(계산 성공 행)이 0이면 백업 없이 7로
                있으면 db_backup.create_backup(--pg-bin 필수, 새 백업 검증 포함)
                백업 실패 -> 아무것도 쓰지 않고 exit 2. 백업을 건너뛰는 옵션은 없다
6 쓰기          한 트랜잭션:
                UPDATE sentences SET ruby_json = :value WHERE id = :id AND ruby_json IS NULL
                commit 후 갱신 행 수 출력
7 종료 코드     F > 0 이면 **쓸 행 수와 무관하게** exit 2 (성공분은 6에서 이미 썼다.
                다음 실행은 실패분만 대상으로 다시 본다). F = 0 이면 exit 0
```

-   **멱등 판정은 `ruby_json IS NULL` 하나다.** 두 번째 실행은 대상 0(실패분 제외), 백업 없음, exit 0이다.
-   **API와 worker를 멈추지 않아도 된다.** 읽는 것은 `sentences`와 콘텐츠 annotation뿐이고 학습
    테이블에 닿지 않는다. 쓰기의 `AND ruby_json IS NULL`이 동시에 들어온 worker 행(이미 값이 있다)이나
    동시에 돈 다른 backfill의 결과를 덮어쓰지 않는다. 경합에서 늦은 쪽은 0행 갱신으로 끝난다.
-   **CLI 출력의 제어문자를 이스케이프한다.** 불일치 목록의 `explanation=`, `surface=` 값은 생성 문장에서
    LLM이 낸 문자열일 수 있다. 제어문자(C0·C1, U+007F)는 `\uXXXX` 형태로 바꿔 출력해 터미널 제어 시퀀스가
    운영자 터미널에서 해석되지 않게 한다. seed CLI와 fixture 생성 CLI도 같은 출력 함수를 쓴다.
-   **운영 대상 확인은 스크립트가 아니라 절차가 한다.** `infra/DEPLOY.md`가 ADR-020 결정 7의 `prod_db`
    함수를 체인 맨 앞에 둔다(`prod_db && make backfill-ruby ARGS="--apply --pg-bin <PG_BIN>"`). 스크립트가
    `APP_ENV=production`을 거부하지 않는 이유는 이 스크립트의 목적이 운영 DB이기 때문이다(`db_reset`과
    반대, `db_migrate`와 같다). 운영 DSN 문자열을 코드에 넣을 수도 없다(ADR-020 결정 6).
-   `computed_at`은 진입점이 `utc_now()`로 한 번 읽어 모든 행에 같은 값을 넣는다(ADR-007).
-   **되돌림:** 표시 보조 컬럼이므로 `UPDATE sentences SET ruby_json = NULL`로 충분하다. 강제 백업은
    사용자 결정이며 이 되돌림과 무관하게 유지한다.
-   Makefile 타깃 이름은 구현이 정한다.

### 분석기 import 경계: G14 (ADR-007·ADR-015 guard의 연장)

``` text
G14(a)  sudachipy / sudachidict_core import는 app/furigana.py 에서만
G14(b)  app.furigana import는 ANALYZER_IMPORTERS에서만
          services/seed_loader.py
          jobs/persistence.py
        (scripts/는 검사 범위 밖이다. backfill·fixture 스크립트와 run_worker.py가 여기서 import한다)
G14(c)  app/furigana.py는 sqlalchemy, app.db, app.models, app.services, app.api, app.jobs,
        app.learning, app.srs, app.llm, app.config, app.settings, app.clock 를 import하지 않는다
        (L0 중 render만 쓴다)
런타임  test_no_provider_in_request_path.py의 별도 프로세스 탐침에서
        FORBIDDEN_IN_API_PROCESS에 "app.furigana", "sudachipy", "sudachidict_core"를 더한다
        (API를 띄워 요청까지 밟은 뒤 sys.modules에 없어야 한다)
```

-   `backend/tests/test_module_boundaries.py` 상단 상수(`ANALYZER_IMPORTERS`)로 둔다. 늘리려면 이 ADR을
    먼저 고친다(ADR-007의 allowlist 규칙).
-   **정적 guard만으로는 부족하다.** `services/seed_loader.py`를 `api/`가 import하는 순간 분석기가 API
    프로세스에 들어온다. 그 전이 경로는 런타임 탐침이 잡는다. 반대로 탐침만 두면 아직 밟지 않은 요청
    경로를 놓친다. provider 경계(G4/G12 + 탐침)와 같은 분담이다.
-   **배포 수준에서 한 번 더 막힌다.** API 이미지에 패키지가 없으므로(`결정 6`) 전이 import가 생기면
    API 컨테이너가 기동에서 `ModuleNotFoundError`로 죽는다. 조용히 요청 경로에서 분석하는 상태는
    만들어질 수 없다.
-   `render.py`는 `PURE_MODULES`에 그대로 남는다(G11(b)). 분석기를 모른다.

---

## 결정 5 --- API 계약: `render_segments[].ruby`

### 형태

``` json
"render_segments": [
  {"text": "この仕事、田中さんに", "sentence_item_id": null,
   "ruby": [{"text": "この", "reading": null}, {"text": "仕事", "reading": "しごと"},
            {"text": "、", "reading": null},   {"text": "田中", "reading": "たなか"},
            {"text": "さんに", "reading": null}]},
  {"text": "任せ", "sentence_item_id": 5511,
   "ruby": [{"text": "任", "reading": "まか"}, {"text": "せ", "reading": null}]},
  {"text": "てもいい", "sentence_item_id": 5512, "ruby": []},
  {"text": "？", "sentence_item_id": null, "ruby": []}
]
```

``` python
class RubyPartPayload(BaseModel):
    text: str
    reading: str | None

class RenderSegmentPayload(BaseModel):
    text: str
    sentence_item_id: int | None
    ruby: list[RubyPartPayload]
```

``` ts
/** segment 안의 표시 조각. reading이 null이면 후리가나 없이 text만 그린다. */
export type RubyPart = {
  text: string
  reading: string | null
}

export type RenderSegment = {
  text: string
  sentence_item_id: number | null
  /**
   * 후리가나 표시 보조. 학습 신호가 아니다.
   * []  이 segment에 달 읽기가 없다 (한자 없음 / 생략 / 미계산 / 저장값 무효 --- 구분하지 않는다)
   * 그 밖  parts.map(p => p.text).join('') === text
   */
  ruby: RubyPart[]
}
```

### 규칙

``` text
R1  ruby는 [] 이거나, parts의 text를 이으면 segment.text와 같다
R2  segment 안에 ruby span이 하나도 없으면 []. 있으면 segment 전체를 덮는 parts
R3  part.text는 비어 있지 않다. reading이 null인 인접 part는 하나로 합친다 (정규형)
R4  reading은 비어 있지 않은 문자열이고 모든 문자가 U+3041..U+3096, U+309D(ゝ), U+309E(ゞ), U+30FC(ー) 안에 있다
R5  ruby_json이 NULL이면 모든 segment의 ruby = []  (미계산과 한자 없음을 payload에서 가르지 않는다)
R6  저장값이 validate_ruby_spans를 통과 못 하면 모든 segment의 ruby = [] + ruby.invalid_stored.
    표시 시점 검증은 범위·겹침·tappable 경계에 더해 **R4의 읽기 문자 집합**을 다시 확인한다
    (저장값이 손으로 고쳐졌거나 규칙 버그로 가타카나·ASCII·제어문자가 들어온 경우).
    **모양이 틀린 저장값도 같다:** `ruby_json`이 객체가 아니거나, `spans`가 없거나 배열이 아니거나, 원소가
    길이 3의 배열이 아니거나, start·end가 정수가 아니거나 reading이 문자열이 아니면 모든 segment의
    ruby = []이고 응답은 200이다(파싱 예외를 500으로 올리지 않는다)
    500을 내지 않는다
R7  toggle 상태와 무관하게 항상 싣는다
```

-   **서버가 자른다(`render.py`).** `render_segments`를 서버가 만드는 이유(`05_API_SPEC.md`: frontend가
    UTF-16 index를 계산하지 않는다)가 ruby에도 그대로 적용된다. 좌표 `[start, end, reading]`을
    payload에 싣지 않는다.
-   **payload가 `null`을 쓰지 않는 이유:** 프론트엔드가 네 경우를 구분해서 할 일이 없다. 모든
    경우의 동작이 "그 segment는 글자만 그린다" 하나다. `null`을 두면 `null`과 `[]`를 가르는 분기와
    그 분기의 테스트가 생기지만 화면 결과는 같다.
-   **R2의 `[]`는 "달 것이 없다"만 뜻한다.** `[{"text": "てもいい", "reading": null}]`로 보내지 않는다.
    정규형이 하나여야 demo fixture와 API 출력의 일치 테스트가 결정적이다.
-   **R6이 500이 아닌 이유:** 표시 보조가 학습을 막지 않는다. 기존 `RenderSpanError`(tappable span
    오류)는 여전히 500이다 --- 그것은 탭 대상 자체가 틀린 것이다.
-   probe의 `expression`, explanation 응답(`canonical_form`, `reading`, `example_sentence`)에는 ruby가
    없다(표시 범위는 학습 문장뿐이다, Wave 1 보완 결정 2026-09-13).

### R7 --- 토글이 꺼져 있어도 항상 싣는다

토글은 브라우저 localStorage에만 있고 **서버로 가지 않는다**(불변식 16, ADR-022). 서버는 토글 상태를
모르므로 조건부로 실을 수 없다. 조건부로 싣게 하려면 토글을 요청에 실어야 하고, 그것이 불변식 16을
어긴다. 비용은 문장당 수백 바이트다.

### `14_CONFIGURATION.md`의 서술과의 관계

현행: "presentation payload에는 `korean_translation` 필드도 reading 필드도 존재하지 않으므로 번역과
reading은 각각 `/translation/reveal`과 `/click`을 거쳐야만 나온다."

``` text
item 설명의 reading       sentence_item_explanations.reading
                          /click 응답에만 있다. item_clicked·explanation_revealed의 대상. 변경 없음
                          content.reading_default_visible: false 는 이 설명 패널 reading의 기본 상태다
문장 ruby                 sentences.ruby_json 에서 온 render_segments[].ruby
                          문장 전체 한자의 표시 보조. 항상 payload에 있다. event를 만들지 않는다
후리가나 토글              브라우저 localStorage. 기본 끔. 서버·config에 없다
```

-   spec-sync는 위 문장을 "presentation payload에는 번역과 **item 설명의 reading**이 없다"로 좁히고,
    문장 ruby가 payload에 있다는 사실과 그것이 학습 신호가 아니라는 사실을 함께 적는다.
-   **토글 기본값을 config 키로 두지 않는다.** 서버가 소비하지 않는 값이고, 두면 기본값의 source of
    truth가 둘(config와 frontend)이 된다. `reading_default_visible`을 토글 기본값으로 재해석하지도
    않는다 --- 이 키는 설명 패널의 reading을 뜻한다.
-   **학습 신호가 아니다(불변식 16).** ruby 표시와 토글은 `learning_events`, `item_exposures`, evidence를
    만들지 않는다. 토글이 켜져 있으면 tappable item의 읽기(v2에서는 대개 설명 시트의 `reading`과 같은 값, `결정 3a`)가 탭 전에 보이지만, 어떤 정책도 "읽기를
    보았는가"를 입력으로 쓰지 않는다(mastery는 이해 신호만 본다). `item_clicked`/`explanation_revealed`의
    의미는 그대로다. learning-verifier 확인 대상이다.

---

## 결정 6 --- 이미지와 의존성 배치

``` toml
[dependency-groups]
furigana = ["sudachipy==0.6.11", "sudachidict-core==20260723"]

[tool.uv]
default-groups = ["dev", "furigana"]
```

``` text
Dockerfile.backend  RUN uv sync --frozen --no-default-groups --no-build                    (분석기 없음)
Dockerfile.worker   RUN uv sync --frozen --no-default-groups --group furigana --no-build  (분석기 포함)
호스트              uv sync / uv run  (기본 group 전부: dev + furigana)
```

-   **두 이미지 명령에 `--no-build`를 붙인다(Wave 2 보완 결정, 2026-09-13).** 이미지 빌드에서 sdist를 빌드하지 않고
    `uv.lock`에 고정된 wheel만 설치한다. wheel이 없는 패키지가 생기면 이미지 빌드가 조용히 컴파일로 넘어가지 않고
    실패한다.

임시 환경의 프로젝트 사본(pyproject + uv.lock 복사 후 group 추가, `uv lock`)으로 확인했다.

``` text
--no-default-groups                     site-packages 88M,  sudachi 0, pytest 0
--no-default-groups --group furigana    site-packages 300M, sudachi 있음, pytest 0
--no-dev (현행 Dockerfile 명령)         site-packages 300M, sudachi 있음   <- default-groups에 furigana가
                                                                            있으면 --no-dev로는 빠지지 않는다
```

-   **backend(API) 이미지에는 필요 없다.** API는 저장값을 읽기만 한다. seed 적재와 backfill은 컨테이너가
    아니라 호스트 `uv run`에서 한다(ADR-020 결정 1). 그래서 API 이미지는 그대로 88M이다.
-   **worker 이미지는 약 +212M(압축 전), 내려받기 약 70 MiB가 는다.** 사전이 wheel에 들어 있어 런타임
    내려받기와 쓰기 권한이 필요 없다. site-packages는 root 소유 읽기 전용이고 uid 10001이 mmap으로 읽는다.
-   **두 Dockerfile의 명령을 반드시 함께 바꾼다.** `default-groups`만 추가하고 Dockerfile을 그대로 두면
    `--no-dev`가 furigana group을 포함해 API 이미지에도 212M가 들어간다(위 세 번째 줄). 조용한 실패다.
    Wave 2가 `backend/tests/test_infra_compose.py` 옆에 두 명령을 고정하는 테스트를 둔다. 같은 테스트가
    `pyproject.toml`의 `[project.dependencies]`에 `sudachipy`·`sudachidict-core`가 **없고** `furigana` group에만
    있음을 단정한다. main dependencies로 옮기면 두 Dockerfile 명령과 무관하게 API 이미지에 들어가기 때문이다.
-   `sudachipy`에 `py.typed`가 없어 `app/furigana.py`의 import 한 줄에만 `# type: ignore[import-untyped]`를
    둔다. mypy 전역 override는 두지 않는다(범위가 한 줄이다).
-   **LEGAL 고지:** 이미지는 외부에 배포하지 않는다. 공개되는 것은 demo fixture 안의 **계산된 읽기**뿐이고
    사전 자체가 아니다. 그래도 README의 기술 스택 절에 분석기·사전 이름과 라이선스(Apache-2.0, UniDic
    BSD-3-Clause 포함)를 한 줄 적는다. 이미지를 공개 배포하게 되면 상류 LEGAL 파일을 이미지에 넣는다.

---

## 버린 대안

-   **fugashi + unidic-lite.** 라이선스는 허용적이다. 같은 감사에서 오류 경향이 Sudachi와 같았고,
    unidic-lite는 wheel이 없는 sdist라 설치가 빌드 단계를 거치며 크기(249M)도 비슷하다. 사전이 2013년
    UniDic 2.1.2다. 얻는 것이 없다.
-   **별도 테이블 `sentence_ruby_spans`.** `결정 2`의 비교. 미계산과 한자 없음을 가르려면 문장별 상태
    구조가 하나 더 필요하고 presentation마다 쿼리가 는다.
-   **`sentences.provenance_json`에 분석기 provenance를 넣는다.** 생성 provenance와 표시 보조 기록이 한
    값에 섞이고 backfill이 생성 기록 컬럼을 고치게 된다.
-   **payload에 좌표 `[start, end, reading]`을 그대로 싣는다.** frontend가 code point -> UTF-16 변환을
    해야 한다. `sentence_item_spans`에서 이미 금지한 방식이다.
-   **payload에 `ruby: RubyPart[] | null`.** `결정 5`. 구분해서 할 일이 없는 상태를 타입에 만든다.
-   **API 이미지에도 분석기를 넣는다(main dependencies).** Dockerfile 변경이 없다는 것이 유일한 이점이다.
    API 이미지가 88M -> 300M가 되고, 요청 경로에서 분석기를 import해도 배포 수준에서 드러나지 않는다.
-   **분석기 부재도 문장별 NULL로 흡수한다(부팅 성공).** `결정 4`의 `실패 두 종류`. 배포 결함이 조용히
    쌓인다.
-   **분석기 객체를 provider처럼 worker 진입점에서 주입한다.** worker loop -> runner -> handler ->
    persistence 시그니처가 전부 인자 하나씩 는다. 분석기는 결정적이고 비용·secret이 없어 test double이
    필요 없다(테스트는 실제 사전을 쓴다). 실패 주입 테스트는 `compute_ruby`를 대체하는 것으로 충분하다.
    진입점은 `load_analyzer()`로 부팅 검사만 한다.
-   **수사 음변화 표로 숫자 읽기를 고친다.** 조수사마다 촉음·반탁음·연탁 규칙이 다르다. 표가 틀리면 틀린
    읽기가 결정적으로 반복된다. 읽기 엔진을 새로 짓는 일이고 MVP-02 범위가 아니다.
-   **SplitMode.A로 처음부터 토큰화한다.** 경계 충돌은 줄지만 복합어 연탁을 잃는다(本棚 -> ほんたな).
    C로 읽고 충돌할 때만 읽기 이음이 같은 경우에 A를 쓰는 편이 둘 다 지킨다.
-   **backfill에 버전이 낮은 행을 다시 계산하는 옵션(`--recompute-older-than`)을 지금 둔다.** 첫 배포 버전이
    2이므로 다시 계산할 옛 버전 행이 없다. 요청되지 않은 기능이다. 교정 표나 사전을 바꾸는 미래 변경이
    재계산 수단(대상 조건, 멱등, 기본값)을 함께 설계한다.
-   **교정 표를 `config/` 아래 YAML 데이터 파일로 둔다.** `결정 3a`. production 전체 사본 규칙과 섞이고
    `algorithm_version`과 떨어진다.
-   **LLM으로 읽기를 교정한다.** 사용자 결정으로 금지다(비용, 비결정성).
-   **SudachiDict 사용자 사전으로 교정한다.** 사전 항목의 비용 조정은 토큰화 자체를 바꿔 경계·재분할 결과까지
    흔든다. 사전 빌드 단계가 이미지 빌드에 들어온다. 표면형 + 앞뒤 토큰 조건의 교정 표가 영향 범위를 가장
    좁게 한정한다.
-   **`一日`·`何+と/で`처럼 seed로 확인할 수 없는 규칙을 넣는다.** 추측 규칙은 틀린 읽기를 결정적으로
    반복시킨다. `결정 3a`의 규칙 추가 조건.
-   **explanation 우선 계층 없이 교정 표만.** seed에서는 결과가 같았다. 그러나 생성 문장에는 교정 표가 모르는
    표현이 계속 들어오고, 탭 대상 표현은 설명 읽기가 문맥에 맞춰 적혀 있다. 학습 대상 표현의 읽기가 설명
    시트와 문장 ruby에서 서로 다르게 보이는 일도 막는다.

---

## 결과와 한계

-   **"켜면 문장 속 모든 한자에 읽기"에는 명세에 적는 예외가 있다.** seed에서 한자 문자 3,023개 중
    62개(2.1%)에 읽기가 없다. 전부 숫자 규칙(수사와 바로 뒤 조수사, 28묶음)이다. 경계 생략은 0이었다.
    틀린 읽기를 보이는 것보다 비워 두는 쪽을 택했고, 이 예외를 `03_UI_UX_SPEC.md`의 후리가나 규칙에 적는다.
    사전에 없는 한자(no_reading)와 tappable 경계 생략도 같은 예외에 든다.
-   **읽기 오류가 줄었지만 남는다.** 20문장 표본의 틀린 ruby는 v1 5개 -> v2 1개(`一日[ついたち]`)다.
    교정 표는 seed에서 확인한 8개 규칙뿐이라, **seed에 없는 문맥 의존 복수 읽기**(생성 문장의 새 표현)는
    v1과 같은 비율로 틀릴 수 있다. tappable 표현은 계층 1이 설명 읽기로 덮고, 탭할 수 없는 한자의 오류는
    여전히 어디에도 드러나지 않는다. 새 오류가 확인되면 `결정 3a`의 절차로 규칙을 더하고 버전을 올린다.
-   **계층 1은 설명 읽기가 틀리면 틀린 ruby를 만든다.** 생성 문장의 설명 읽기는 LLM 출력이다.
    `ruby.explanation_override`로만 관측되고 자동 판정은 없다.
-   **교정 표 규칙은 전역이다.** `私 -> わたし`는 격식체 문장의 わたくし도 わたし로 단다. seed 16개는 전부
    평서·구어체였다. `明日 -> あした`는 일기예보 문체의 あす를 あした로 단다(틀린 읽기는 아니다).
-   **생성 문장은 seed와 분포가 다를 수 있다.** 경계 생략 0%는 사람이 span을 단 seed의 결과다. LLM이 단
    span이 복합어를 자주 자르면 생략이 는다. `ruby.computed`의 `omitted_tappable_boundary`로 보인다.
-   **교정 표·정렬 규칙·사전을 바꿔도 기존 행은 옛 계산을 유지한다.** 지금은 재계산 수단이 없다.
    `ruby_json.algorithm_version`과 `dictionary.version`으로 섞여 있다는 사실은 조회할 수 있다.
-   **생성 문장에서는 계층 1이 자주 성립하지 않을 수 있다.** 표면형 읽기 정의는 `EXPLAIN_ITEM` prompt에만
    있고, 문장 생성(`GENERATE_SENTENCE_BATCH`)과 review context prompt에는 정의가 없으며 요청의 target item에
    기본형 `learning_items.reading`이 실린다. prompt는 바꾸지 않으므로 활용형 표현(`任せ`에 `まかせる`)은 계층 1
    정렬이 실패해 분석기 읽기(+교정 표)로 넘어가고 `reading_mismatch`가 늘 수 있다. seed의 492/492 정렬
    성립은 생성 문장에 그대로 옮겨지지 않는다. **ruby 안전성은 유지된다** --- 정렬이 실패하면 설명 읽기를
    쓰지 않고, 분석기 읽기는 결정 3의 검사를 그대로 거친다.
-   **backfill의 대상 확인은 절차 수준이다(`prod_db` 체인).** ADR-020 결정 7의 한계와 같다.
-   **worker 이미지가 약 212M 커진다.**
-   **mypy가 `sudachipy`의 타입을 보지 않는다.** 어댑터 안에서 반환값을 `str`/`int`로 명시해 받는다.

---

## 명세 반영 대상 (spec-sync)

``` text
AGENTS.md                         "MVP 구현 대상이 아님"에서 형태소 분석기만 MVP-02로 해제
spec/02_ARCHITECTURE.md           분석기는 worker 이미지 + 호스트 CLI에만. API 이미지·요청 경로 없음.
                                  새 모듈 app/furigana.py, scripts/backfill_ruby.py
spec/06_LLM_ENGINEERING_PRINCIPLES.md  MVP 제외 목록의 형태소 분석기에 MVP-02 해제 주석
spec/mvp-01-core/04_DB_SPEC.md    sentences.ruby_json (NULL 의미, 모양, provenance, algorithm_version, corrected),
                                  Seed Data 적재 단계, Migration Rule 뒤 backfill 경로(NULL 행만, 종료 코드),
                                  explanation.reading = 문장 속 표면형 읽기 (04 또는 08에 한 줄)
spec/mvp-01-core/05_API_SPEC.md   Sentence Presentation Payload의 render_segments[].ruby, R1~R7, 예시
spec/mvp-01-core/08_LLM_SPEC.md   검증 통과 뒤 저장 단계의 ruby 계산. 검증 항목이 아님, 탈락 사유 추가 없음,
                                  prompt 불변, worker 부팅 검사(분석기 적재)
spec/mvp-01-core/03_UI_UX_SPEC.md Translation/Furigana 규칙(기본 끔, 켤 수 있음, 켜면 문장 속 모든 한자).
                                  **"모든 한자"의 예외**를 규칙 옆에 적는다: 수사와 바로 뒤 조수사(숫자 규칙,
                                  seed 한자 문자의 2.1%), 사전에 읽기가 없는 한자, tappable 경계를 넘는 토큰
spec/mvp-01-core/02_LEARNING_POLICY.md  Auxiliary signal: ruby 표시·토글은 신호 아님
spec/mvp-01-core/11_OBSERVABILITY.md    MVP-02 추가 절: ruby.* 이벤트(explanation_override 포함),
                                  CLI 요약·규칙별 적중, NULL 잔량 조회
spec/mvp-01-core/14_CONFIGURATION.md    reading_default_visible 단락과 "payload에 reading 없음" 서술 정리.
                                  후리가나 교정 표는 학습 정책값이 아니므로 이 파일의 대상이 아니라는 한 줄
spec/mvp-02-onboarding/12_TEST_PLAN.md  정렬 단위(okurigana, 々, 모호, 불일치, 숫자, 재분할, 연탁 비구제),
                                  교정 계층(explanation 정렬 성립/불성립, 불연속 span, 규칙 적중/비적중 조건,
                                  재분할이 교정 읽기와 비교, 두 종류 불일치 보고),
                                  G14 + 런타임 탐침, 저장값 무효 -> ruby []·200, 계산 실패 -> validated·NULL,
                                  backfill(dry-run 무쓰기, 백업 강제, 두 번째 실행 0, 동시 실행,
                                  실패 1건이면 성공분을 쓰고 exit 2, CLI 제어문자 이스케이프),
                                  표시 시점 검증의 읽기 문자 집합과 모양(가타카나·ASCII·제어문자,
                                  spans 비배열·원소 타입 오류 저장값 -> ruby []·200),
                                  런타임 탐침 sudachidict_core, sudachipy·sudachidict-core가
                                  [project.dependencies]에 없음(furigana group에만 있음),
                                  fixture 재생성 일치, Dockerfile 두 명령 고정
spec/mvp-02-onboarding/13_ACCEPTANCE_CRITERIA.md
docs/decisions/ADR-015            계층표 L1에 app/furigana.py, guard 목록에 G14 (이 ADR을 가리키는 한 줄)
infra/DEPLOY.md (Wave 4)          백업 -> 이미지 재빌드 -> db-migrate -> backfill dry-run -> prod_db && --apply
README.md (Wave 4)                기술 스택에 분석기·사전 라이선스 한 줄
```
