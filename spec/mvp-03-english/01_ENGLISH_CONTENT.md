# English Content Standard (MVP-03)

영어 seed가 **무엇을 담고 무엇을 담지 않는가**의 canonical 정의다. 결정 배경은 ADR-024이고, 이
문서는 그 결정을 구현 규칙으로 푼다. 자료의 라이선스 취급은 ADR-024 결정 1이 canonical이다.

## 학습자 전제

이 값은 선별과 프롬프트에 **고정 문자열로** 들어간다. 추정으로 바꾸지 않는다.

``` text
한국 정규 교육과정을 마쳤고 수능과 영어 전공 수업 경험이 있다.
TOEIC 700점대 후반, OPIc IM2. 읽기는 되지만 실시간 대화와 미드·팟캐스트 청취가 어렵다.
목표는 시험 점수가 아니라 일상 대화 이해와 미드·팟캐스트 이해다.
```

## 무엇을 가르치는가

**"아는 단어로 되어 있는데 못 알아듣는 것"**이 대상이다. 어려운 단어가 아니다.

``` text
대상이다                                    대상이 아니다
you good?  my bad  I'm down                 ubiquitous  nevertheless  albeit
sort of  kind of  I mean  you see           TOEFL/IELTS 고급 어휘
mind you  might as well  oh well  no wonder 학술 담화 표지 (furthermore, in contrast)
get away with  put up with  run out of      비즈니스 정형구 (as per our discussion)
a bit of a  that sort of thing  and all that 전문 용어
the other day  for good  bother to  can tell 문학·고어
gonna  wanna  kinda  ain't (인식용)          철자 규칙·파닉스
```

-   **난이도의 축이 "단어의 희귀성"이 아니라 "쓰임의 불투명성"이다.** `put up with`의 세 단어는
    전부 최고빈도인데 뜻은 조합으로 나오지 않는다. 그런 항목이 1순위다.
-   **생산(말하기)보다 인식(듣기·읽기)이 먼저다.** `gonna`, `ain't`를 **쓰라고** 가르치지 않는다.
    들었을 때 알아듣는 것이 목표다. 이 구분은 `nuance`가 적는다.
-   **커버리지 퍼센트를 약속하지 않는다.** "3000개면 95%"는 단어족 기준 수치이고(Nation 2006)
    표현 단위 seed에 그대로 적용되지 않는다. 명세·README·UI에 퍼센트를 적지 않는다.

## 1차 규모

``` text
표현(learning_items)   300
문장(sentences)        약 1000   (표현당 3~4)
```

증분 적재로 넓힌다(`mvp-01-core/04_DB_SPEC.md`의 `Seed Data`). 2차 시점과 규모는 정하지 않았다
(`00_SCOPE.md`의 `알려진 공백`).

## 선별 절차

ADR-024 결정 2가 canonical이다. 요약하면 **스크립트가 하는 일과 판단이 드는 일을 분리한다.**

``` text
1 후보 모음 (스크립트)   A PHRASE List 구어 ★★★            314
                         B PHaVE List 구동사 1순위 sense    150
                         C NGSL-Spoken 720 안의 구어 단어
                         D LLM 보완 (상황 목록 고정)        2012년 이후 구어
2 중복 제거 (스크립트)   PHaVE ∩ PHRASE -> PHaVE 쪽. 표면형 중복 -> 고빈도 쪽
3 난이도 분류 (LLM)      already_known / shaky / unknown    학습자 전제를 프롬프트에 싣는다
4 선별 (스크립트)        shaky + unknown 을 빈도 내림차순 상위 300. D 최소 60 보장
5 사람 확인 (사용자)     "이건 이미 안다"를 걷어내고 다음 순위로 채운다
6 frequency_rank         최종 300 안에서 1..300. 작을수록 고빈도
7 예문·설명 (LLM + 검수) 표현당 문장 3~4개, 설명 다섯 필드
```

-   **5단계가 유일한 사실 확인이다.** 3단계의 LLM 분류는 추정이다. 전수 검수를 요구하지 않는다.
-   **잘못 들어간 "이미 아는 표현"의 비용은 작다.** probe가 한 번 묻고 `알고 있었음`으로 끝난다.
    반대로 빠진 표현은 영영 안 나온다. 그래서 **의심스러우면 넣는다.**
-   스크립트는 `data/wordlists/`를 읽고 `seed/en/*.yaml`을 쓴다. 입력은 커밋하지 않고
    스크립트와 출력은 커밋한다(불변식 27).

## `topic_tags` 고정 집합

`learning_items.topic_tags`는 `text[] nullable`이고 DB 제약이 없다. **고정 집합 강제는 seed
loader가 한다** --- CHECK로 배열 원소를 제약하면 집합을 바꿀 때마다 migration이 필요하다.

``` text
언어 성격 (0개 이상)
  phrasal-verb        구동사                          pick up, get away with
  idiom               관용구                          a bit of a, to death
  discourse-marker    담화 표지                       I mean, you see, mind you, by the way
  formulaic           회화 정형구                     you good?, my bad, never mind, oh well
  contraction         축약·구어형 (인식용)            gonna, wanna, kinda, ain't
  colloquial          구어 전용 용법                  sort of, that much, way out
  slang               속어                            no cap
언어 성격이 없는 항목  단일 단어 중 특별한 성격이 없는 것 (bother, decent)

상황 (0개 이상)
  daily  friends  work  travel  food  shopping  health  phone  smalltalk
```

-   **`grammar` 태그를 쓰지 않는다.** 일본어 seed에는 있지만 영어는 그 성격을
    `learning_items.type = grammar`가 이미 표현한다. 두 축에 같은 정보를 두지 않는다.
-   태그는 **두 언어가 공유하지 않는다.** 소비처는 "최근 topic 반복 회피"뿐이고
    (`02_LEARNING_POLICY.md`의 `Topic`) 그 비교는 세션 언어 안에서만 일어난다.
-   집합을 늘리는 것은 loader 상수와 이 문서를 같은 커밋에서 고치는 일이다.

## `type` 배정

`word | grammar | expression` 세 값 그대로다(ADR-024 결정 3). 값을 더하지 않는다.

``` text
word         단일 단어                       afford, bother, decent, whatever(단독)
grammar      문법 구조를 가르치는 항목       used to, had better, be about to, have got to, might as well
expression   그 밖의 덩어리 전부             pick up, to do with, I mean, you good?, a bit of a
```

-   **경계가 애매하면 `expression`이다.** `have got to`는 조동사 구조라 `grammar`이지만
    `might as well`은 어느 쪽으로도 읽힌다. 이럴 때 `expression`을 고른다 --- 소비처가
    "문장당 신규 1\~2개" 계산과 설명 형식이고 둘 다 type으로 갈리지 않는다.

## 필드 규약

### `learning_items`

``` text
seed_id           en_it_0001 식. 영어 전용 이름공간. 번호는 선별 결과 순서이며 frequency_rank와 같다
type              위 type 배정
language          'en'
lemma             표제형(기본형). 소문자로 적는다 (pick up, to do with, you good?)
reading           없다 (YAML에서 생략. DB에 NULL)
default_meaning   한국어 canonical 의미
difficulty_label  beginner | intermediate | advanced
topic_tags        위 고정 집합
frequency_rank    1..300. 작을수록 고빈도
```

-   **`lemma`를 소문자로 적는다.** 외부 자료는 `PICK UP`처럼 대문자로 적지만 그 대문자는 목록의
    표기 관습이고 영어의 표기가 아니다. 문장 속 실제 표면형은
    `sentence_items.surface_form`이 가진다.
-   `?`와 `'`를 `lemma`에 쓸 수 있다(`you good?`, `I'm afraid`). 표현의 일부다.
-   **`canonical_form`은 별도 필드가 아니다.** YAML 키도 DB 컬럼도 아니며, 설명 응답에서
    `lemma`를 그 이름으로 내보내는 것이다(`05_API_SPEC.md`의 Explanation 응답). 활용형은
    `sentence_items.surface_form`이 가지므로 표제형과 기본형을 두 값으로 둘 필요가 없다 ---
    영어 item을 활용형으로 적지 않는다(`picked up`이 아니라 `pick up`).
-   **`metadata_json`에 출처를 기록하지 않는다.** 소비처가 없다(ADR-024 결정 3).

### `sentences`

``` text
seed_id             en_sn_0001 식
language            'en'
text                영어 문장
korean_translation  한국어 번역
ruby_json           없다 (DB CHECK가 NULL을 강제한다)
```

-   **문장에 난이도를 적지 않는다.** `difficulty_label`은 `learning_items`의 필드이고 문장에는
    없다. seed loader의 문장 파싱이 그 키를 읽지 않으므로 적어도 조용히 버려지고, 일본어 seed도
    쓰지 않는다. `sentences.difficulty_json`은 **LLM이 생성한 문장만** 채운다(응답 스키마의
    `difficulty_label`, `08_LLM_SPEC.md`) --- seed 문장에서는 `{}`로 남는다.
-   **난이도 칸을 seed에 되살리지 않는다.** 사람이 매긴 값과 모델이 매긴 값을 같은 컬럼에
    섞으면 둘을 구별할 수 없고, 문장 난이도를 읽는 코드는 생성 경로에만 있다.

### 설명 다섯 필드 --- `nuance`가 핵심이다

``` text
reading              없다 (null)
core_meaning         한국어 핵심 뜻
meaning_in_context   이 문장에서의 뜻
nuance               격식 수준 / 누가 누구에게 / 교과서 영어와 어떻게 다른가 / 비슷한 표현과의 차이
example_sentence     영어 예문. 학습 문장과 다른 문맥
example_translation  한국어 번역
```

**`nuance`에 반드시 들어가야 하는 것:**

``` text
1 격식 수준        친구끼리 / 중립 / 격식 자리에서는 쓰지 않음
2 누가 누구에게    윗사람에게 쓸 수 있는가
3 교과서와의 차이  학교에서 배운 표현 중 무엇을 대체하는가
4 인식 전용 여부   들으면 알아야 하지만 직접 쓸 필요는 없는 것인지
```

위 네 가지 중 **해당하는 것만** 적는다. 해당 없는 항목을 억지로 채우지 않는다.

### 작성 예 1 --- `you good?`

``` yaml
- seed_id: en_it_0007
  type: expression
  lemma: you good?
  default_meaning: 괜찮아?
  difficulty_label: beginner
  topic_tags: [formulaic, friends, health]
  frequency_rank: 7
```

``` yaml
      explanation:
        core_meaning: 괜찮아?
        meaning_in_context: 넘어진 상대에게 다친 데 없냐고 묻는 말이다.
        nuance: >
          Are you okay?를 친구 사이에서 줄인 말이다. 상대가 넘어지거나 당황한 직후에 묻는다.
          격식 자리나 윗사람에게는 쓰지 않는다. 들으면 바로 알아야 하지만 직접 쓸 일은 많지 않다.
        example_sentence: Whoa, you good?
        example_translation: 어, 괜찮아?
```

-   `nuance`가 하는 일을 보라. 사용자가 못 알아들은 것은 `you`도 `good`도 아니라 **"이것이
    `Are you okay?`의 친구용 축약이고 사고 직후에 쓴다"**는 사실 하나다.

### 작성 예 2 --- `sort of` (의미가 둘로 갈리는 경우)

``` text
1차에 넣는 것   "약간, 좀" 의 완화 표현 (It's sort of cold.)
1차에 넣지 않는 것  "뭐랄까" 의 머뭇거림 표지 (It's sort of... why I'm here.)
```

-   **한 표현의 두 용법을 별개 item으로 쪼개지 않는다.** `LearningItem → Sense` 분리는 Future다
    (`spec/03_DOMAIN_MODEL.md`). 대신 **고빈도 용법 하나만 1차에 싣고** 나머지는 증분 적재로
    미룬다. PHaVE의 2순위 sense를 미루는 것과 같은 규칙이다.
-   어느 용법이 1순위인지는 PHaVE가 있으면 그 퍼센트를, 없으면 LLM 판단과 사용자 확인을 쓴다.

### 작성 예 3 --- 구동사의 의미 sense (PHaVE 기반)

``` text
PICK UP   1순위  Get or take SB/STH from a place (70.5%)   -> 1차에 넣는다
COME UP   1순위  (+ with) Bring forth or produce (34%)      -> 1차에 넣는다
          2순위  Be happening soon (27.5%)                  -> 미룬다
TAKE OFF  1순위  Remove STH (41%)                           -> 1차에 넣는다
          2·3순위 Leave suddenly (28.5%) / 이륙 (14%)        -> 미룬다
```

-   **1순위 비율이 40% 미만이면 `nuance`에 "다른 뜻도 있다"를 한 줄 적는다.** `COME UP`은 1순위가
    34%뿐이라 그 뜻만 알고 있으면 세 번 중 두 번은 못 알아듣는다. 나중 적재를 기다리는 동안의
    안전장치다.

## 문장 작성 규칙

``` text
1 구어체다. 드라마 대사나 친구와의 대화에서 실제로 나올 문장을 만든다
2 축약형을 피하지 않는다 (I'm, don't, gonna, wanna). 교과서처럼 풀어 쓰지 않는다
3 길이 상한은 content.max_sentence_length_chars.en (14_CONFIGURATION.md)
4 문장당 target은 1~2개다 (08_LLM_SPEC.md의 validation 5)
5 설명·번역은 한국어다
6 같은 표현의 문장 3~4개는 서로 다른 문맥이어야 한다 (문맥 사다리의 재료)
```

-   **1·2가 일본어 seed 규칙에 없던 조항이다.** 일본어는 `spec/01_PRODUCT_PRINCIPLES.md` 원칙 8이
    같은 뜻을 담고 있으나, 영어는 LLM이 기본적으로 문어체·시험체로 기울기 때문에 명시한다.
-   **6의 "서로 다른 문맥"이 문맥 사다리의 전제다.** 같은 표현의 문장 넷이 모두 비슷하면
    `context_stage`가 `anchor → near_original → varied → new_context`로 올라가도 실제로는 같은
    문맥을 네 번 보는 것이 된다(`07_SRS_SPEC.md`의 `Context Progression`).

## 금지

``` text
외부 자료 원본을 저장소에 커밋하기                 (불변식 27, ADR-024 결정 1)
외부 자료의 예문을 그대로 seed에 복사하기           저작물의 재배포다. 같은 표현으로 새로 쓴다
커버리지 퍼센트를 명세·README·UI에 적기
영어 발음 표기 (IPA · 한글 근사)                    reading은 null이다
영어 형태소 분석기·lemmatizer 도입
item type enum 확장
```

-   **외부 목록의 예문을 베끼지 않는다.** PHaVE·PHRASE의 예문은 저작물이다. 선별 단계에서 "이
    표현이 무엇인지" 판단하는 데는 쓰되, `seed/en/sentences.yaml`의 문장은 새로 만든다. 이것이
    외부 자료를 로컬에만 두는 또 하나의 이유다 --- 베낄 수 있는 자리에 없다.

## 검증

seed loader가 적재 전에 검사한다. 하나라도 실패하면 **아무것도 적재하지 않는다.**

``` text
1  seed_id가 파일 안에서 유일하고 DB의 기존 seed_id와 겹치지 않는다 (증분 적재)
2  language가 'en'이고 reading 키가 없다
3  type이 세 값 중 하나다
4  topic_tags의 모든 원소가 고정 집합 안에 있다
5  frequency_rank가 1 이상의 정수이고 파일 안에서 유일하다
6  문장의 text 길이가 max_sentence_length_chars.en 이하다
7  문장당 target(is_tappable)이 1~2개다
8  모든 tappable item에 explanation이 있고 reading 키가 없다
9  span 좌표가 text의 code point index로 표면형과 정확히 일치한다
10 문장의 item_seed_id가 같은 파일 또는 DB에 이미 있는 item을 가리킨다
11 normalized_hash(en 규칙)가 파일 안에서, 그리고 DB의 기존 문장과 중복되지 않는다
```

-   9·11은 일본어 loader가 이미 하는 검사이며 영어에서도 **같은 함수**를 쓴다. 11의 정규화 규칙만
    언어별로 갈린다(ADR-024 결정 6).
-   **후리가나 계산은 건너뛴다.** `language = 'en'`이면 분석기를 부르지 않는다(불변식 23).
