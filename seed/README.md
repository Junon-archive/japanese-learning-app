# starter seed

초급 사용자의 첫 세션을 가능하게 하는 **작은 version-controlled starter
set**이다(`spec/mvp-01-core/04_DB_SPEC.md`의 Seed Data). 지금 들어 있는
분량은 포맷을 보여주고 첫 세션이 도는지 확인하기 위한 최소량이며, 본격적인
일본어 starter set 작성은 이후 작업이다.

적재:

```
export DATABASE_URL=...        # 예: $(make db-up-local)
make db-reset ARGS=--yes
make seed
```

## 파일

- `items.yaml` --- `learning_items`. **배열 순서가 곧 적재 순서다.**
- `sentences.yaml` --- `sentences` + `sentence_items` +
  `sentence_item_spans` + `sentence_item_explanations`.

YAML을 쓰는 이유는 중첩된 span/explanation 구조와 여러 줄 일본어/한국어
텍스트, 출처 주석이 필요하기 때문이다.

## 규약

- `seed_id`는 안정 키다. 파일 안에서 유일해야 하고,
  `sentences.yaml`은 `item_seed_id`로 이것을 참조한다.
  `sentences.source_id`에 sentence의 `seed_id`가 그대로 들어간다.
- `frequency_rank`(선택, 작을수록 고빈도)는
  `learning_items.metadata_json.frequency_rank`로 들어간다.
  frequency 전용 컬럼은 만들지 않는다(`06_LEARNING_ENGINE.md`).
- `seed_order`는 파일에 적지 않는다. loader가 파일명 오름차순 -> 파일 내
  행 순서로 **1부터 1씩** 매겨 `metadata_json.seed_order`에 넣는다.
  learning item이 `items.yaml` 한 파일에만 있으므로 실질적으로는 이 파일의
  행 순서다. 새 item은 **끝에 추가**한다. 중간에 끼워 넣으면 뒤쪽 item의
  `seed_order`가 전부 밀린다.
- `frequency_rank`가 없어도 `seed_order`를 `frequency_rank`로
  승격시키지 않는다. 하나는 언어 빈도이고 다른 하나는 파일 위치다.
- `start_codepoint` / `end_codepoint`는 `japanese`의 **Unicode code point
  index**이고 반열린 구간 `[start, end)`다. byte offset도 UTF-16 code
  unit도 아니다. loader가 실제 문자열과 대조하며, 어긋나면 적재 전체가
  실패하고 DB에는 아무것도 남지 않는다.
- `span_order`는 0부터 빠짐없이 증가한다. 불연속 표현
  (`気が全然乗らない`)은 span을 여러 개 두고, 그것을 `span_order` 순으로
  이어 붙인 결과가 `surface_form`과 같아야 한다.
- **`explanation`은 필수다.** 설명이 없는 item이 든 문장은 Ready Pool에
  들어가면 tap 시 보여줄 데이터가 없다. loader가 거부한다.

## 재적재

지원하지 않는다. `origin = seed` 행이 이미 있으면 loader가 거부한다.
seed를 고쳤으면 `make db-reset ARGS=--yes && make seed`로 다시 만든다.
(재적재 의미론은 명세에 아직 없다. upsert를 임의로 만들지 않았다.)

## 테스트 fixture와의 관계

테스트는 이 디렉터리가 아니라 `backend/tests/data/`의 최소 fixture를
쓴다. 여기 실 데이터를 통째로 교체해도 테스트가 깨지지 않게 하기
위해서다. 다만 `test_seed_loader.py`는 이 디렉터리도 한 번 적재해 보므로
포맷 오류는 테스트에서 잡힌다.
