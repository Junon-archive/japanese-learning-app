# ADR-007 --- Wave 2 모듈 경계와 시각 주입

Status: Accepted

Decision:

1.  `learning/`과 `srs/`는 **서로를 import하지 않는** 평평한 정책 계층이다.
    트랜잭션과 event 기록은 `services/`, HTTP는 `api/`가 한다.
2.  시각은 **요청당 한 번 읽고 `now: datetime` 값으로 전달한다.** clock
    객체나 Protocol을 넘기지 않는다.
3.  모든 `created_at`을 애플리케이션이 채운다. DB `server_default now()`를
    제거한다.

구현 지시서 §4의 불변식 #1 #2 #3은 코드 구조로만 지켜진다. Wave 1에서
확인한 대로 주석은 지켜지지 않고 **구조로 강제하고 테스트로 고정한 것**만
지켜진다(`app/api/router.py`의 fail-closed). 아래 규칙은 전부
`backend/tests/test_module_boundaries.py`가 실패시킨다.

## 계층

``` text
L0  models  config  settings  clock  db      app 내부 의존 없음
    render  normalization                   app.* 를 아예 import하지 않는다
L1  srs/*        learning/*                  L0만. 서로 import 금지
L2  services/*   jobs/*                      L0 + L1 + L2
L3  api/*                                    L0 + L2 + schemas. L1 금지
```

-   **import 금지는 불변식 #3의 절반만 준다.** 양쪽 다 `models`를 보므로
    `learning/`이 `review_states.stability`에 대입하는 경로는 남는다.
    나머지 절반은 아래 G5의 **컬럼 쓰기 소유권**이 막는다. 둘을 같이
    걸어야 "mastery 갱신이 FSRS를 건드릴" 경로가 사라진다.
-   **읽기는 막지 않는다.** review ordering은 `next_review_at`을 봐야 한다.
    금지되는 것은 쓰기와 교차 import뿐이다.
-   정책 모듈은 세션에 붙은 ORM 인스턴스를 **변경할 수 있고 commit하지
    않는다.** "정책은 값만 반환하고 services가 대입한다"는 안은 버렸다.
    모든 컬럼을 DTO로 미러링해야 하고, 그러면 쓰기가 `services/` 한곳에
    모여 소유권 규칙 자체가 성립하지 않는다.
-   G2는 Wave 1의 `api/auth.py` ↔ `services/auth.py`와 같은 경계다.
-   `render.py`와 `normalization.py`는 Wave 3에서 L0로 올라왔다. span 검증과
    문장 정규화를 `app/llm/`(L1)이 재사용하는데, 그것들이 `services/`에 남아
    있으면 L1이 L2를 import해야 한다. 규칙과 guard 번호는 ADR-015의 G11(b)다.

## 정적 guard

``` text
G1   app.srs ↔ app.learning 상호 import 금지
G2   app.api.* 는 app.learning / app.srs 를 import하지 않는다
G3   fsrs 패키지 import는 app/srs/ 에서만
G4   app.llm import는 app/llm/ 과 app/jobs/ 에서만.
     httpx / openai / anthropic / requests 도 app/llm/ 에서만        (#1)
G5   쓰기 소유권 (속성 대입 + 생성자·values() 키워드):
       app/srs/*            stability difficulty state step
                            last_review_at next_review_at reps lapses
                            deferred_until fsrs_params_version        (#3)
       app/learning/mastery.py
                            comprehension_mastery evidence_count
                            mastery_algorithm_version last_updated_at
G6   listening_mastery 식별자는 backend/app/ 안에서
     models/learning.py(컬럼 선언)에만 나타난다
G7   commit / rollback 은 app/learning/, app/srs/ 에 없다.
     app/api/ 에서는 ALLOWLIST(auth login·logout, deps.get_current_user)만
G8   datetime.now / utcnow / time.time / date.today 는 app/clock.py 에만
G9   clock.utc_now() 호출은 api/deps.py의 get_now 와 app/jobs/ 진입점에만
G10  SQL now() / CURRENT_TIMESTAMP 는 backend/app/ 어디에도 없다
```

allowlist는 `APPROVED_UNVERIFIABLE_ROUTES`처럼 guard 모듈 상단의 상수로
두고, 늘리려면 이 ADR을 먼저 고친다.

`review_states.meaningful_exposure_count`는 FSRS 값이 아니라
`item_exposures`의 캐시이므로 exposure를 기록하는 service가 소유한다.

**불변식 #2는 정적 guard로 완전히 잡히지 않는다.** rating 계산 함수가
`EventType`이 아니라 explicit signal 3값(known/uncertain/unknown)만 받는
타입을 갖게 해서 no-click을 **표현 불가능**하게 만들고, 나머지는 Scenario
테스트가 고정한다. 그 3값 enum은 `models/enums.py`에 둔다. 계획자가 제안한
별도 `signals` 모듈은 만들지 않는다 --- enum 하나를 위한 최상위 모듈이고,
signal→Rating과 signal→observation 매핑이 한 파일에 모이면 #3이 지키려는
분리가 다시 흐려진다. 매핑은 각각 `srs/`와 `learning/`에 둔다.

## 시각 주입

``` text
app/clock.py              utc_now()   프로세스에서 시각을 읽는 유일한 지점
app/api/deps.py           get_now()   요청당 1회 (FastAPI dependency cache)
services/ learning/ srs/  def f(..., *, now: datetime)
```

-   **값으로 넘긴다.** clock 객체를 넘기면 호출부가 `clock.now()`를 여러 번
    부를 수 있고 한 요청 안에서 시각이 갈린다. 값은 갈릴 수가 없다.
    `deferred_until`, `next_review_at`, due 판정, `exploration_recent_days`,
    probe cooldown, idle timeout, `active_seconds`가 전부 같은 순간을 본다.
-   비용은 시그니처마다 `now`가 붙는 것이다. 정당하다: 누락을 mypy가 잡고,
    대안인 ContextVar/모듈 전역은 암묵 의존이라 누락이 **조용히** 통과한다.
-   테스트는 정책 함수에 `now=`를 직접 주고, API 테스트는
    `app.dependency_overrides[get_now]`로 시각을 옮긴다. freezegun이나
    `datetime` monkeypatch를 쓰지 않는다.
-   Wave 1의 직접 호출부(`services/auth.py` 3곳, `services/seed_loader.py`,
    `api/health.py`)를 Wave 2가 변환한다. 기계적인 치환이다. allowlist를
    만들지 않는다 --- 예외를 한 번 허용하면 G8이 무의미해진다.

## created_at --- 이중 시계 제거

`item_exposures` / `learning_events`의 `created_at`이 DB wall clock인데
`exploration_recent_days`와 probe cooldown은 주입된 `now`를 본다. 두 시계가
갈리면 테스트가 거짓 통과한다.

-   `created_at_column()`에서 `server_default now()`를 **제거한다.**
    애플리케이션이 주입된 `now`로 채우고, 빠뜨리면 NOT NULL 위반으로 즉시
    실패한다. server_default를 안전망으로 남기는 안은 반대로 간다 --- 빠뜨린
    값이 조용히 DB 시계로 대체되는 것이 바로 막으려는 실패다.
-   문제가 되는 두 테이블만 고치지 않는다. 규칙이 둘이 되면 나중에 다른
    테이블의 `created_at`을 정책이 읽는 순간 이중 시계가 조용히 돌아온다.
    규칙이 하나면 G10 grep 하나로 전수 검증된다.
-   배포된 DB가 없으므로 `0001_initial_schema.py`를 그 자리에서 고친다.
-   비용: 모든 INSERT와 test factory가 `now`를 나른다.

## 트랜잭션 경계

-   요청 1개 = 세션 1개(`get_db`) = **service 함수 안에서 commit 1회.**
    `api/study.py`는 commit하지 않는다(G7).
-   `get_current_user`의 `last_used_at` commit은 handler 본문 전에 끝난다.
    학습 트랜잭션과 분리돼 있고 롤백돼도 무해하다.
-   job enqueue는 같은 트랜잭션의 INSERT다. 롤백된 학습 상태에 대한 job이
    남지 않는다. provider 호출은 worker에만 있다(G4, 불변식 #1).

## 한계

G5 / G6은 식별자 기반이라 `setattr(state, name, value)` 같은 동적 대입을
잡지 못한다. Scenario A~H 테스트가 그 자리를 메운다.
