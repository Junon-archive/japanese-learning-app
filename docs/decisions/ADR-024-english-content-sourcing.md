# ADR-024 --- 영어 콘텐츠 공급: 자료, 선별, 프롬프트

Status: Accepted

Decision: 영어 seed는 **공개 코퍼스 기반 목록에서 고르고 LLM이 보완**한다. 표현 목록의 뼈대는
PHRASE List(구문 표현 506개)와 PHaVE List(구동사 150개)이고, 빈도 순위는 SUBTLEX-US(영화·드라마
자막 5100만 어절)와 NGSL-Spoken에서 온다. **원본 목록은 저장소에 커밋하지 않는다** --- 라이선스가
서로 다르고 두 개는 CC BY-SA라서 전량 복사가 저장소에 share-alike를 전파한다. 커밋하는 것은 우리가
고른 표현과 자체 `frequency_rank`뿐이다. 1차 규모는 **300표현 / 문장 약 1000**이다. 예문·설명은
`GENERATE_SENTENCE_BATCH` 파이프라인이 아니라 **seed 생성 단계**에서 만들어 YAML에 고정하고 검수한다.

``` text
자료 (data/wordlists/, gitignore)
  PHRASE List   Martinez & Schmitt (2012)  506 구문 표현. 빈도 + 장르 등급 + 예문. 구어 ★★★ 314개
  PHaVE List    Garnier & Schmitt (2015)   구동사 150개. 의미 sense별 출현 비율(%) + 예문
  SUBTLEX-US    Brysbaert & New (2009)     자막 5100만 어절. 74,286 단어의 WF/CD        CC BY-SA
  NGSL 1.01 / NGSL-Spoken 1.2              일반 2,800 / 구어 720 표제어                 CC BY-SA

커밋하는 것   seed/en/*.yaml (우리가 고른 표현, 자체 frequency_rank, LLM 생성 후 검수한 예문·설명)
              scripts/build_en_seed.py (선별 스크립트)
              seed/en/README.md (출처 표기와 라이선스)
커밋하지 않는 것  data/wordlists/ 전부 (원본 목록)

규모          1차 300표현 / 문장 약 1000.  목표 3000은 ADR-023 결정 4의 증분 적재로 넓힌다
프롬프트      backend/app/llm/prompts/en/.  task_type은 그대로 3종, version은 sentence_gen_en_v1 식
```

`spec/`에 반영하기 전까지 구현 근거가 아니다(사용자 결정 2026-10-01).

---

## 맥락

사용자 결정(2026-10-01)의 목표는 시험 점수가 아니라 **원어민 대화와 미드·팟캐스트 이해**다. 사용자
원문: "you가 뭔지도 알고 good이 뭔지도 알지만, 미국 여행갔을 때 외국인이 문제가 생긴 나한테
'you good?'라고 물어봤는데, 뭔 소리인지 몰랐어."

이 진술이 자료 선택을 거의 다 정한다.

-   **단어 빈도 목록만으로는 안 된다.** `you`와 `good`은 어느 목록에서도 최상위인데 `you good?`은
    어느 목록에도 없다. 필요한 것은 **다어절 덩어리(multi-word chunk)**다.
-   **학술·시험 어휘 목록은 쓸 수 없다.** NAWL(학술), TSL(TOEIC), BSL(비즈니스)은 전부 이 목적의
    반대 방향이다.
-   **코퍼스가 구어여야 한다.** 일반 문어 빈도에서 높은 단어와 드라마 대사에서 높은 단어는 다르다.

처음 조사에서 "회화 청크의 공개 목록은 없다"고 판단했으나 **틀렸다.** Martinez & Schmitt (2012)의
PHRASE List가 정확히 그것이고, 저자가 자기 사이트에서 무료로 배포하고 있다. 장르 등급에
**"Spoken general" 열**이 있어 구어 편중 항목을 바로 거를 수 있다.

### 실측: 구어 ★★★에서 뽑은 것

``` text
I MEAN   SORT OF   KIND OF   COME ON   HANG ON   OH WELL   OH NO   THAT'S IT   NO IDEA
YOU SEE  OR SOMETHING   OR WHATEVER   THINK SO   GO AHEAD   ALL RIGHT   HAVE GOT TO
ON ONE'S OWN   TO DO WITH   JUST ABOUT   A BIT OF A   BY NOW   SET TO   HAPPEN TO (BE)
```

사용자가 말한 그 종류다. `you good?` 자체는 2012년 자료라 없고, 그 공백을 LLM이 메운다(`결정 2`의 1-D).

---

## 결정 1 --- 자료와 라이선스

### 쓰는 것

| 자료 | 역할 | 라이선스 | 출처 |
|---|---|---|---|
| PHRASE List (Martinez & Schmitt 2012) | 구문 표현 뼈대 | 저자 사이트 무료 배포. CC 아님 | norbertschmitt.co.uk |
| PHaVE List (Garnier & Schmitt 2015) | 구동사 150개와 의미 sense | 저자 사이트 무료 배포. CC 아님 | norbertschmitt.co.uk |
| SUBTLEX-US (Brysbaert & New 2009) | 단어 빈도(자막 코퍼스) | **CC BY-SA** | lexique.org / UGent |
| NGSL 1.01, NGSL-Spoken 1.2 | 표제어와 난이도 밴드 | **CC BY-SA** | newgeneralservicelist.com |

### 거른 것

``` text
Oxford 3000 / 5000       OUP 저작권. 재배포 불가
COCA 전체 빈도 목록       유료
OpenSubtitles 원본 코퍼스  자막 저작권이 불명확하고, SUBTLEX가 같은 종류 코퍼스의 가공 결과다
```

### 저장소에 넣지 않는 이유

-   **CC BY-SA는 share-alike다.** NGSL·SUBTLEX를 전량 복사해 커밋하면 그 조항이 저장소의 파생물로
    번진다. 이 저장소는 공개다.
-   **PHaVE·PHRASE는 CC가 아니다.** 저자가 교육·연구 목적으로 무료 배포하는 저널 부록이고, 제3자
    재배포 허가가 명시되어 있지 않다.
-   **원본 없이도 결과는 재현된다.** 선별 스크립트와 `seed/en/*.yaml`이 커밋되므로, 같은 원본을 받은
    사람은 같은 결과를 얻는다. 받지 않은 사람도 완성된 seed를 그대로 쓴다.
-   `data/wordlists/`를 `.gitignore`에 넣는다. `seed/en/README.md`에 출처·저자·연도·라이선스와
    받는 곳을 적는다(인용은 share-alike를 트리거하지 않는다).

### 받는 주체

**Claude가 받는다**(사용자 결정 2026-10-01). "OpenAI·Cloudflare 연결은 사용자가 직접"이라는 기존
경계는 **계정·API 키·결제·DNS·도메인**에 대한 것이고 공개 학술 자료 다운로드는 그 범주가 아니다.
이 경계는 바뀌지 않는다.

---

## 결정 2 --- 1차 300표현을 고르는 절차

**결정론적 단계와 판단이 드는 단계를 분리한다.** 스크립트가 하는 일과 사람·LLM이 하는 일을 섞지
않는다.

### 1. 후보 모으기 (스크립트)

``` text
A  PHRASE List   Spoken general = ★★★ 인 항목                                   314
B  PHaVE List    구동사 150개. 각 구동사의 1순위 의미 sense만 쓴다                150
C  SUBTLEX-US    상위 구어 빈도 단어 중 NGSL-Spoken 720에 있는 것                720
D  LLM 보완      2012년 이후 구어·미드 표현. 상황별로 뽑는다 (아래)               수백
```

-   **B의 2순위 이하 sense는 1차에서 빼고 증분 적재로 미룬다.** `WORK OUT`의 "운동하다"(23%)는
    "계획하다"(33%)를 배운 뒤에 와야 문맥 사다리가 성립한다. 한 번에 넣으면 같은 표면형의 두 item이
    첫 세션부터 경쟁한다.
-   **C는 단어이고 A·B는 덩어리다.** C가 필요한 이유는 영어 문장을 만들려면 tappable이 될 만한
    기본 어휘가 DB에 있어야 하기 때문이다. 다만 C 단독으로는 "이미 아는 단어"가 대부분이라 4단계가
    대부분 걷어낸다.
-   **D의 상황 목록은 고정한다**(스크립트가 프롬프트에 그대로 싣는다).

    ``` text
    맞장구와 반응        되묻기와 확인       부탁과 거절       약속과 일정 조율
    식당·카페 주문       길 찾기와 교통      상점과 결제       숙소와 체크인
    몸 상태와 사고       사과와 양해         감정 표현         잡담 시작과 마무리
    전화와 메시지        미드에서 흔한 축약·구어형(gonna, wanna, kinda, ain't, y'all 류)
    ```

### 2. 중복 제거 (스크립트)

``` text
PHaVE와 PHRASE에 겹치는 구동사(GO ON, PICK UP, COME BACK ...)  -> PHaVE 쪽을 쓴다 (의미 sense 정보가 있다)
표면형이 같은 항목                                              -> 빈도가 높은 쪽 하나만
```

### 3. 난이도 분류 (LLM)

학습자 프로필을 **고정 문자열**로 프롬프트에 싣고 후보를 3분류한다.

``` text
프로필   한국 정규 교육과정을 마쳤고 수능과 영어 전공 수업 경험이 있다.
         TOEIC 700점대 후반, OPIc IM2. 읽기는 되지만 실시간 대화와 미드 청취가 어렵다.
         목표는 시험이 아니라 일상 대화 이해와 미드·팟캐스트 이해다.

분류     already_known   이 학습자는 이미 안다 (have to, of course, a lot ...)
         shaky           뜻은 짐작하지만 실제 쓰임·뉘앙스를 모른다 (sort of, to do with, set to ...)
         unknown         모를 가능성이 높다 (all but, put it, happen to be ...)
```

### 4. 선별 (스크립트)

``` text
shaky + unknown 을 출처 빈도 내림차순으로 정렬해 상위 300
단, 1-D(LLM 보완)에서 온 항목이 최소 60개는 들어가도록 보장한다
```

-   **D의 하한을 두는 이유:** 빈도만으로 자르면 코퍼스 빈도값이 없는 D 항목이 전부 밀려난다.
    그런데 `you good?` 류는 **D에만 있다.** 사용자가 든 바로 그 예가 빠지는 선별은 목적을 배신한다.
-   하한값 60은 승인값이고 실사용 후 바뀔 수 있다. 명세가 아니라 선별 스크립트의 인자로 둔다.

### 5. 사람 확인 (사용자)

사용자가 최종 300개 목록을 보고 **"이건 이미 안다"를 걷어낸다.** 걷어낸 자리는 4단계의 다음 순위로
채운다. 3단계의 LLM 분류는 추정이고 이 단계가 유일한 사실 확인이다.

### 6. `frequency_rank` 매기기 (스크립트)

``` text
최종 300개 안에서 1부터 300까지. 출처 빈도의 상대 순위를 보존한다
출처 빈도가 없는 항목(1-D)은 LLM이 추정한 빈도대의 중앙값 자리에 넣는다
```

-   일본어 seed의 `frequency_rank`와 **같은 의미**다: 작을수록 고빈도이며 코퍼스 기반 절대값이 아니다
    (`seed/items.yaml` 머리 주석). 소비처는 exploration 정렬이다(`06_LEARNING_ENGINE.md`).
-   **두 언어의 `frequency_rank`를 서로 비교하지 않는다.** exploration은 세션 언어 범위 안에서만
    정렬하므로(ADR-023 결정 7) 비교할 일이 없다.

### 7. 예문·설명 생성과 검수 (LLM + 사용자)

-   표현당 seed 문장 **3~4개**를 LLM이 만들고 설명 다섯 필드를 채운다. 300표현 × 3.3 ≈ 1000문장.
-   **seed 생성 단계에서 만들어 YAML에 고정한다.** 운영 `GENERATE_SENTENCE_BATCH`로 만들지 않는다.
    seed는 cold start의 재료라서 계정이 없는 시점에 이미 있어야 하고, 검수를 거친 고정 콘텐츠여야
    한다(일본어 seed와 같은 취급).
-   생성 결과는 `08_LLM_SPEC.md`의 **deterministic validation을 그대로 통과해야** 한다. seed라고
    검증을 건너뛰지 않는다. span 좌표 검증이 특히 그렇다.
-   사용자가 표본을 검수한다. 전수 검수는 요구하지 않는다.

---

## 결정 3 --- 영어 item을 기존 모델에 어떻게 싣는가

### type은 기존 3종 그대로다

사용자 결정(2026-10-01). `word | grammar | expression`에 값을 더하지 않는다.

``` text
word         단일 단어. SUBTLEX/NGSL에서 온 것 (afford, bother, decent ...)
grammar      문법 구조를 가르치는 항목 (used to, had better, be about to, have got to)
expression   그 밖의 덩어리 전부 — 구동사, 관용구, 담화표지, 회화 정형구
             (pick up, to do with, I mean, you good?, my bad)
```

-   **구동사·관용구·슬랭을 위한 타입을 만들지 않는다.** 경계가 실제로 애매하다 --- `gonna`는 슬랭인가
    축약형인가, `have got to`는 grammar인가 expression인가. enum을 늘리면 그 판정을 매번 해야 하고
    UI·검증·프롬프트에 분기가 생긴다.
-   성격은 `topic_tags`로 적는다. **태그는 자유 문자열이 아니라 고정 집합이다.**

    ``` text
    언어 성격   phrasal-verb  idiom  discourse-marker  formulaic  contraction  colloquial  slang
    상황        daily  friends  work  travel  food  shopping  health  phone  smalltalk
    ```

    `topic_tags`는 이미 `text[] nullable`이고 제약이 없다. **고정 집합 강제는 seed loader가 한다**
    --- DB CHECK로 배열 원소를 제약하면 집합을 바꿀 때마다 migration이 필요하다.
-   일본어 seed의 태그(`daily`, `work`, `grammar` ...)는 그대로 둔다. 두 언어가 같은 태그 공간을
    공유할 필요가 없고, 태그의 소비처는 "최근 topic 반복 회피"뿐이라 언어를 넘지 않는다.

### 필드 대응

``` text
lemma            표제형.  pick up / to do with / you good? / afford
canonical_form   기본형.  대개 lemma와 같다. 활용하는 것만 다르다 (picked up -> pick up)
reading          NULL     (ADR-023 결정 3)
default_meaning  한국어 canonical 의미
difficulty_label beginner | intermediate | advanced  — 기존 3단계 그대로
metadata_json    frequency_rank, seed_order  — 기존 규약 그대로
                 영어 전용 키를 더하지 않는다
seed_id          en_it_0001 식 (ADR-023 결정 4)
```

-   **`metadata_json`에 출처(PHRASE/PHaVE/SUBTLEX)를 기록하지 않는다.** 소비처가 없다. 출처별
    집계가 필요해지면 선별 스크립트의 중간 산출물을 보면 되고, 그것은 DB에 둘 값이 아니다.
-   **`'s`·대소문자 같은 표면 변이는 span이 흡수한다.** `sentence_items.surface_form`과
    `sentence_item_spans`가 이미 문장 속 실제 표면형과 좌표를 가진다. 영어에서 달라지는 것이 없다.

### 설명 다섯 필드에서 영어가 실제로 하는 일

``` text
reading              NULL
core_meaning         한국어 핵심 뜻
meaning_in_context   이 문장에서의 뜻
nuance               **여기가 핵심이다.** 격식 수준, 누가 누구에게 쓰는가,
                     교과서 영어와 어떻게 다른가, 비슷한 표현과의 차이
example_sentence     영어 예문 (학습 문장과 다른 문맥)
example_translation  한국어 번역
```

-   `you good?`의 `nuance`가 담아야 하는 것: *"`Are you okay?`를 친구 사이에서 줄인 말. 상대가
    넘어지거나 당황한 직후에 묻는다. 격식 자리나 윗사람에게는 쓰지 않는다."* 사용자가 못 알아들은
    것은 단어가 아니라 **이 정보**다.
-   일본어의 `nuance`가 하던 일(`任せる`와 `頼む`의 차이)과 같은 자리이며, 영어에서는 **격식
    수준과 구어성**이 그 자리의 주 내용이 된다. 프롬프트가 이것을 명시적으로 요구한다(`결정 5`).

---

## 결정 4 --- seed 파일 배치

``` text
현재          seed/items.yaml   seed/sentences.yaml   seed/README.md
바뀜          seed/ja/items.yaml  seed/ja/sentences.yaml
              seed/en/items.yaml  seed/en/sentences.yaml  seed/en/README.md
              seed/README.md  (공통 규약)
```

-   **`git mv`로 옮긴다.** 내용은 바뀌지 않으므로 이력이 이어진다.
-   loader는 `--language` 인자로 디렉터리를 고른다. 두 언어를 한 번에 적재하지 않는다 --- 한
    트랜잭션에 섞으면 한쪽 실패가 다른 쪽을 되돌린다.
-   파일 형식은 일본어와 **같다.** 키 이름도 같다(`seed_id`, `type`, `lemma`, `reading`,
    `default_meaning`, `difficulty_label`, `topic_tags`, `frequency_rank`). `reading`은 영어에서
    생략하고, loader가 `language = 'en'`이면 생략을 허용한다.
-   문장 파일의 `japanese:` 키는 **`text:`로 바꾼다**(ADR-023 결정 2). 일본어 파일도 함께 바꾼다.
    바꾸지 않으면 두 언어의 seed 형식이 갈라진다.

---

## 결정 5 --- 영어 프롬프트

### 배치와 version

``` text
backend/app/llm/prompts/ja/     기존 본문을 옮긴다 (내용 변경은 필드 이름 japanese -> text 하나)
backend/app/llm/prompts/en/     신규
version   sentence_gen_v2 / review_context_v2 / explain_item_v2        (ja. 필드 이름 변경으로 +1)
          sentence_gen_en_v1 / review_context_en_v1 / explain_item_en_v1
active 유일성  (task_type, language)                                    ADR-023 결정 5
```

### 영어 프롬프트가 일본어와 다르게 요구하는 것

``` text
1  구어체를 쓴다. 문어·학술·시험 영어를 쓰지 않는다.
   드라마 대사나 친구와의 대화에서 실제로 나올 문장을 만든다
2  축약형을 피하지 않는다 (I'm, don't, gonna, wanna). 교과서처럼 풀어 쓰지 않는다
3  nuance에 **격식 수준과 누가 누구에게 쓰는가**를 반드시 적는다.
   이 학습자가 막히는 지점은 단어 뜻이 아니라 이것이다
4  reading 필드를 만들지 않는다 (응답 스키마에서 영어는 null)
5  문장 길이 상한은 content.max_sentence_length_chars.en 이다 (결정 6)
6  설명·번역은 한국어다
```

-   **1·2가 일본어 프롬프트에 없는 조항이다.** 일본어 쪽은 `spec/01_PRODUCT_PRINCIPLES.md` 원칙 8
    (Real/Natural Spoken)이 이미 같은 뜻을 담고 있으나, 영어는 LLM이 기본적으로 문어체·시험체로
    기울기 때문에 프롬프트에 명시적으로 적는다.
-   응답 스키마는 **두 언어가 같다**(ADR-023 결정 2로 `text` 필드가 공통이 된 뒤). 영어는
    `explanation.reading`에 `null`을 넣는다. 스키마에서 이미 `null`을 허용하는 필드는
    `explanation`과 `example_translation`뿐이었으므로, **`reading`도 nullable로 바꾼다.**
-   `learner_level`(`users.starting_level`)은 계정에 하나뿐이라 두 언어에 같은 값이 간다. 알려진
    공백이다(ADR-023 결정 8).

---

## 결정 6 --- 언어별 정규화와 길이 상한

### `max_sentence_length_chars`를 언어별로 나눈다

``` text
현재   content.max_sentence_length_chars: 60
바뀜   content.max_sentence_length_chars:
         ja: 60
         en: 120
```

-   **60자는 일본어에 맞춘 값이다.** 영어는 같은 내용에 2배 가까운 문자가 든다. `01_USER_FLOW.md`의
    예시 문장을 영어로 옮기면 85자이고, 60자 상한은 자연스러운 구어 문장을 거의 다 떨어뜨린다.
-   120은 승인값이고 실사용 후 바뀐다. `14_CONFIGURATION.md`에 둔다.
-   config 로더는 "누락 키와 모르는 키를 모두 거부"하므로 **스칼라에서 맵으로 바꾸는 것은 로더
    변경이다.** production override 파일(전체 사본)도 함께 갱신해야 한다 --- 안 하면 기동이 실패하고,
    그것은 시끄러운 실패라 받아들인다(`14_CONFIGURATION.md`의 `전체 사본이 만드는 두 가지 실패`).

### `normalized_hash`를 언어별로 나눈다

``` text
ja   NFKC -> 모든 Unicode whitespace 제거                                (바뀌지 않는다)
en   NFKC -> casefold -> 연속 whitespace를 공백 하나로 -> 앞뒤 strip
```

-   **일본어 규칙은 한 글자도 바꾸지 않는다.** 바꾸면 적재된 765 문장의 해시가 새 값과 달라져
    duplicate 검사가 seed를 못 본다(`08_LLM_SPEC.md`의 `normalized_hash`).
-   **영어에 casefold가 필요하다.** `Come on.`과 `come on.`은 같은 문장인데 NFKC는 대소문자를 접지
    않는다. 접지 않으면 생성이 같은 문장을 대문자만 바꿔 계속 통과시킨다.
-   **영어에서 공백을 전부 지우지 않는다.** 일본어는 공백을 의미 있게 쓰지 않지만 영어는 단어
    경계다. 전부 지우면 서로 다른 문장이 같은 문자열로 접힐 수 있고, `difflib` 유사도의 의미도
    흐려진다.
-   함수 signature가 `normalized_sentence_text(text, language)`가 된다. **분기는 이 함수 하나에만
    있다.** seed loader와 worker가 계속 같은 함수를 부른다는 성질이 이 변경의 전제다.
-   `duplicate_similarity_threshold`(0.90)는 두 언어가 **같은 값**을 쓴다. 영어에 다른 값이 필요한지
    실측한 적이 없고, 근거 없는 두 번째 숫자를 지금 만들지 않는다.

---

## 결과

### 신규 파일

``` text
seed/en/items.yaml  seed/en/sentences.yaml  seed/en/README.md
scripts/build_en_seed.py                     1~6단계 중 스크립트 몫
backend/app/llm/prompts/en/                  영어 prompt 본문
data/wordlists/                              외부 원본 (gitignore)
```

### 이동

``` text
seed/items.yaml -> seed/ja/items.yaml           (git mv)
seed/sentences.yaml -> seed/ja/sentences.yaml   (git mv. japanese: 키를 text:로)
backend/app/llm/prompts/*.* -> prompts/ja/      (git mv)
```

### 바뀌는 문서

``` text
spec/mvp-01-core/04_DB_SPEC.md       Seed Data: 언어별 디렉터리, 영어 seed 규모, 증분 적재
spec/mvp-01-core/08_LLM_SPEC.md      언어별 prompt, 영어 프롬프트 요구, reading nullable, 언어별 정규화
spec/mvp-01-core/14_CONFIGURATION.md max_sentence_length_chars를 언어별 맵으로
spec/mvp-03-english/00_SCOPE.md      범위
spec/mvp-03-english/01_ENGLISH_CONTENT.md  선별 절차와 태그 집합의 canonical 정의
```

### 알려진 한계

-   **PHRASE List는 2012년 자료다.** 그 뒤에 퍼진 구어(`you good?`, `my bad`, `I'm down`,
    `no cap`)가 없다. 1-D의 LLM 보완과 최소 60개 하한이 이 공백을 메우지만, 그 60개의 "실제 빈도"는
    추정이다.
-   **PHaVE의 의미 sense 비율은 COCA 기준이다.** COCA는 구어를 포함하지만 드라마 대사만은 아니다.
    `WORK OUT`의 실제 드라마 내 1순위가 "운동하다"일 수 있다. 1차에서는 PHaVE 순위를 그대로 쓰고,
    실사용에서 어긋나면 그때 2순위 sense를 증분 적재한다.
-   **3단계의 LLM 난이도 분류는 추정이다.** 5단계의 사용자 확인이 유일한 사실 확인이고, 그것도
    전수가 아니다. 틀리면 "이미 아는 표현"이 seed에 남는데, 그 비용은 probe가 한 번 묻고
    `알고 있었음`으로 끝나는 것이다 --- 작다.
-   **커버리지 주장을 하지 않는다.** "3000개면 95%"는 Nation (2006)의 단어족 기준 수치이고, 우리
    seed는 단어족이 아니라 표현 단위라서 그 수치를 그대로 가져다 쓸 수 없다. 명세와 README에
    커버리지 퍼센트를 적지 않는다.
