# 영어 seed 출처 (MVP-03)

`items.yaml`/`sentences.yaml`의 표현 300개를 고르는 데 참고한 공개 빈도 자료의 출처다. 원본
파일 자체는 저장소에 커밋하지 않는다(`.gitignore`의 `data/wordlists/`, 불변식 27). 커밋하는
것은 이 README, 선별 스크립트(`scripts/select_english_candidates.py`), 조립 스크립트
(`scripts/build_english_seed.py`), 그 결과물(`items.yaml`/`sentences.yaml`)뿐이다.
자세한 결정 배경은 `docs/decisions/ADR-024-english-content-sourcing.md`를 본다.

## 참고한 자료

| 자료 | 저자/연도 | 역할 | 라이선스 | 출처 |
|---|---|---|---|---|
| PHRASE List | Martinez & Schmitt, 2012 | 구어 빈도 상위 구문(phrase) 뼈대 | 저자 사이트 무료 배포. CC 아님 | norbertschmitt.co.uk |
| PHaVE List | Garnier & Schmitt, 2015 | 구동사 150개와 1순위 의미(sense) | 저자 사이트 무료 배포. CC 아님 | norbertschmitt.co.uk |
| NGSL-Spoken 1.2 | Browne, Culligan & Phillips | 구어 상위 빈도 단어 목록 | CC BY-SA | newgeneralservicelist.com |
| NGSL 1.01 (+ Supplemental) | Browne, Culligan & Phillips | 참고용 표제어 빈도 (1차 선별에는 NGSL-Spoken만 실제로 썼다) | CC BY-SA | newgeneralservicelist.com |
| SUBTLEX-US | Brysbaert & New, 2009 | 참고용 자막 코퍼스 빈도 (1차 선별 결과에는 반영되지 않았다) | CC BY-SA | lexique.org / UGent |

## 왜 원본을 커밋하지 않는가

- **NGSL·NGSL-Spoken·SUBTLEX-US는 CC BY-SA(share-alike)다.** 전량 복사해 커밋하면 그 조항이
  이 공개 저장소의 파생물로 번진다.
- **PHRASE List·PHaVE List는 CC가 아니다.** 저자가 교육·연구 목적으로 무료 배포하는 저널
  부록이고, 제3자 재배포 허가가 명시돼 있지 않다.
- 인용(출처 표기)은 share-alike를 트리거하지 않는다 — 그래서 이 README는 존재해도 된다.
- 원본이 없어도 결과는 재현된다: 같은 원본을 받으면 `scripts/select_english_candidates.py`가
  **같은 300개를 같은 순서로** 다시 만든다(검증 완료). 원본을 받지 않은 사람도 완성된
  `items.yaml`/`sentences.yaml`을 그대로 쓸 수 있다.

## 선별 절차 요약

1. **후보 모으기** — PHRASE List의 Spoken general `★★★`(314개) + PHaVE List 구동사 1순위
   sense(150개) + NGSL-Spoken 상위 빈도 단어 중 구어 특유의 뜻을 가진 것(38개, 수작업 선별) +
   에이전트가 직접 뽑은 2012년 이후 구어·미드 표현(79개 작성 → 중복 제거 후 74개 채택).
2. **중복 제거** — PHRASE List와 PHaVE List에 같은 표현이 있으면 PHaVE 쪽(의미 sense가 더
   정밀하다)을 남긴다. 그 밖의 표면형 중복은 더 고빈도인 출처를 남긴다.
3. **난이도 분류** — 학습자 전제(수능·전공 영어 이수, TOEIC 700점대 후반, OPIc IM2)를 기준으로
   "이미 알 것"을 제외한다. 판단 결과는 `scripts/select_english_candidates.py`의
   `EXCLUDE_PHRASE_ALREADY_KNOWN`/`EXCLUDE_PHAVE_ALREADY_KNOWN_OR_TAUGHT`/
   `INCLUDE_NGSL_SPOKEN_SHAKY` 상수에 그대로 남아 있다(재현성을 위해 상수로 고정했다).
4. **선별** — 남은 후보를 공개 목록 우선으로 정렬해 226개를 채우고, 나머지 74개를 에이전트
   작성분(D)으로 채운다(최소 60개 보장 조건을 넘긴다). 공개 목록 226 : 에이전트 보완 74 ≈
   75:25.
5. **사람 확인** — 선별된 300개 후보를 사용자에게 보여주고 "이미 아는 표현"을 확인받았다
   (2026-10-02, 전부 진행하기로 결정).
6. **frequency_rank** — 확정된 300개 안에서 1..300을 매겼다(작을수록 고빈도).
7. **예문·설명** — 에이전트가 직접 썼다(`GENERATE_SENTENCE_BATCH` LLM 파이프라인이나 OpenAI API를
   호출하지 않았다). 외부 자료의 예문은 참고만 하고 그대로 베끼지 않았다 — 전부 새로 쓴 문장이다.

## 알아 둘 것 — NGSL-Spoken 원본의 전사(transcript) 잡음

NGSL-Spoken 원본 목록에는 `pause`, `unclear`, `laugh`, `laughter` 같은 항목이 "단어"처럼 섞여
있다. 이 목록이 만들어진 음성 코퍼스의 전사 주석([pause], [laughter] 등)이 그대로 빈도 집계에
들어간 것으로 보인다 — 실제 어휘가 아니므로 후보에서 제외했다
(`scripts/select_english_candidates.py`의 `CORPUS_ARTIFACTS`).

## 커버리지 퍼센트를 적지 않는 이유

"3000개 단어족이 일상 대화의 95%를 커버한다"(Nation 2006) 같은 수치는 **단어족** 기준이고 이
seed처럼 **표현(phrase) 단위**로 고른 집합에는 그대로 적용되지 않는다. 그래서 이 README와
명세, UI 어디에도 퍼센트를 적지 않는다(`01_ENGLISH_CONTENT.md`).

## 2차 확장을 하려면

1. `data/wordlists/`에 같은 원본(과 필요하면 SUBTLEX-US 전체)을 받아 둔다.
2. `scripts/select_english_candidates.py`의 `EXCLUDE_*`/`INCLUDE_*` 상수에 다음 순위 후보를
   더 추가하거나, `TARGET`을 늘려 다시 실행한다.
3. 새 후보에 대해 3~7단계(난이도 분류 → 사람 확인 → 예문·설명 작성)를 반복한다.
4. `scripts/build_english_seed.py`로 `seed/en/items.yaml`/`sentences.yaml`에 **증분**
   적재한다(`scripts/load_seed.py --incremental --language en`) — 기존 300개의 `seed_id`는
   바뀌지 않는다.
