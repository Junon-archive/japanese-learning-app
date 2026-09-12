"""같은 노출에 동시 self-report 2건 (07_SRS_SPEC.md의 `노출당 evidence 1건`).

불변식은 "같은 `study_presentation` + 같은 `learning_item` = evidence 최대 1건"이다.
앱의 판정은 `services/interactions.py`의 `_reject_if_evidence_exists()` --- SELECT
하나다. 그 SELECT와 INSERT 사이에 잠금이 없으므로 서로 다른 `client_event_id` 2건이
각자 "evidence 없음"을 읽고 둘 다 기록할 수 있다. 그러면 한 노출이 mastery EMA를 두
번 돌리고 `reps`도 두 번 올린다 --- ADR-018이 막으려던 그 결과이고, 07_SRS_SPEC.md의
`정정은 하지 않는다`에 따라 사후에 되돌릴 수 없다.

프론트엔드의 버튼 잠금으로는 막을 수 없다(ADR-018: 재시도·두 탭·직접 호출). 동시
요청은 그 `두 탭`과 같은 범주다. 그래서 DB의 `uq_learning_events_evidence`가 두 번째
INSERT를 거부하고, 경합에서 진 요청은 **409**를 받는다 --- 500이 아니다. 명세가 2회차에
요구하는 상태 코드가 이미 409이므로(05_API_SPEC.md의 `노출당 evidence 상한`) 경합에서
진 요청에게 그것은 정확히 옳은 응답이다. 인덱스의 형태는
`test_schema_invariants.py`가, 거부 자체는 `test_db_constraints.py`가 본다.

`committed_db` / `committed_api`를 쓴다. `db_session`은 커넥션 하나 안에서 끝나므로
두 요청이 서로 다른 트랜잭션에 있는 상황 자체를 만들 수 없다. 선례는
`test_presentation_concurrency.py`다.

경합을 우연에 맡기지 않는다. `_reject_if_evidence_exists()`를 barrier로 감싸 **두 요청이
상한 판정 SELECT를 끝낸 뒤에야** INSERT로 넘어가게 한다. 감싸는 자리가 그 SELECT
**다음**이라는 것이 요점이다 --- 앞을 막으면 재현하려는 순서가 아니다. 직렬화가 걸려
한쪽만 barrier에 도착하면 `RACE_TIMEOUT_SECONDS` 뒤 `BrokenBarrierError`로 풀린다.

시계는 `study_clock` 하나이므로 두 요청의 `now`가 `/next`가 남긴 `last_activity_at`과
같다. 그래서 `touch()`가 세션 행에 아무 UPDATE도 만들지 않고(값이 그대로다) 경합 창이
열린 채로 남는다 --- 요청마다 `now`가 다르면 그 UPDATE가 세션 행 잠금을 먼저 잡아
**우연히** 직렬화한다. 불변식이 벽시계 값에 기대면 안 되므로 여기서는 그 우연을 걷어낸
상태를 본다(`test_presentation_concurrency.py`와 같은 이유다).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Any

import httpx2
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.learning.mastery import MASTERY_ALGORITHM_VERSION
from app.models.enums import CandidateStatus, PresentationRole
from app.models.learning import ReviewState, UserMastery
from app.models.study import LearningEvent
from app.models.user import User
from app.services import interactions
from app.services.presentation import FSRS_RATING_EVENTS
from app.srs.fsrs_binding import FSRS_PARAMS_VERSION
from tests import factories
from tests.conftest import StudyApi

pytestmark = pytest.mark.integration

# 상대 스레드를 기다리는 상한. 정책값이 아니라 테스트의 안전장치다 --- 직렬화가 걸린
# 구현에서는 상대가 영영 오지 않으므로 hang 대신 이 시간 뒤에 풀려야 한다.
RACE_TIMEOUT_SECONDS = 2.0

LEMMAS = ("任せる", "預ける", "頼む", "委ねる")


def _seed_ready_sentences(committed_db: sessionmaker[Session]) -> None:
    """서로 다른 item의 ready 문장 여럿. 후보가 하나면 선택이 고갈로 흐려진다."""
    with committed_db() as setup:
        for lemma in LEMMAS:
            item = factories.make_learning_item(setup, lemma=lemma)
            factories.make_ready_sentence(setup, [item])
        setup.commit()


def _seed_item_already_in_review(committed_db: sessionmaker[Session], user: User) -> None:
    """이미 복습 중인 item 하나와 그것을 담은 ready 문장.

    `user_mastery` / `user_item_learning_state` / `review_states` 세 행을 미리 둔다.
    그래야 동시 요청 둘이 **둘 다 끝까지 간다** --- 세 행이 없는 item에서는 두 번째
    요청이 그 행들을 만들려다 `uq_user_mastery_user_id_learning_item_id` 같은 남의
    제약에 걸려 넘어지고, 그 롤백이 중복 evidence를 우연히 지워 준다. 그 우연은
    "이 item을 처음 평가한다"에만 있고 **복습 중인 item에는 없다.** 노출당 evidence
    상한이 지켜야 하는 것은 바로 그쪽이다(07_SRS_SPEC.md는 두 경로를 구분하지 않는다).

    candidate를 손으로 둔다. `new` role은 ready candidate를 id 순으로만 고르므로
    (`_select_new`) 어떤 문장이 나오는지가 결정론이다.
    """
    with committed_db() as setup:
        item = factories.make_learning_item(setup, lemma=LEMMAS[0])
        sentence = factories.make_ready_sentence(setup, [item])
        candidate = factories.make_candidate(
            setup,
            user,
            sentence,
            status=CandidateStatus.READY,
            presentation_role=PresentationRole.NEW,
        )
        factories.make_candidate_target(setup, candidate, item)
        factories.make_mastery(
            setup,
            user,
            item,
            comprehension_mastery=0.5,
            algorithm_version=MASTERY_ALGORITHM_VERSION,
        )
        factories.make_learning_state(
            setup,
            user,
            item,
            is_active_learning_target=True,
            anchor_sentence_id=sentence.id,
        )
        review_state = factories.make_review_state(
            setup, user, item, state=2, params_version=FSRS_PARAMS_VERSION
        )
        # FSRS는 `Review` 상태의 `Card`에서 memory state를 요구한다. 아래 값은 그 요구를
        # 채우는 filler이고 이 테스트의 주장과 무관하다(정책값이 아니다).
        review_state.stability = 5.0
        review_state.difficulty = 5.0
        review_state.last_review_at = factories.NOW
        setup.commit()


def _install_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """evidence 조회와 event INSERT 사이에서 두 요청을 만나게 한다.

    감싸는 것이 `_reject_if_evidence_exists()`이고 기다리는 자리가 그 **호출 뒤**다 ---
    상한을 판정하는 SELECT는 이미 끝났고 INSERT는 아직 나가지 않은 지점이 정확히 경합
    창이다. 그 앞에서 기다리면 재현하려는 순서가 아니다.
    """
    barrier = threading.Barrier(2)
    # `interactions`에서 읽지 않고 모듈 attribute를 먼저 떼어 둔다. 재적용에서 wrapper를
    # 다시 감싸지 않기 위해서다.
    real_reject = interactions._reject_if_evidence_exists

    def racing_reject(
        db: Session,
        *,
        user_id: int,
        presentation_id: int,
        learning_item_id: int,
        client_event_id: uuid.UUID,
    ) -> None:
        real_reject(
            db,
            user_id=user_id,
            presentation_id=presentation_id,
            learning_item_id=learning_item_id,
            client_event_id=client_event_id,
        )
        with suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=RACE_TIMEOUT_SECONDS)

    monkeypatch.setattr(interactions, "_reject_if_evidence_exists", racing_reject)


def _self_report_twice(
    api: StudyApi, presentation_id: int, *, sentence_item_id: int
) -> list[httpx2.Response]:
    """같은 노출에 self-report 2건을 진짜로 동시에 보낸다.

    `client_event_id`가 서로 다르다. 같으면 재전송 멱등성이 먼저 판정되어(05_API_SPEC.md의
    `판정 순서` 3 < 4) 상한이 검사 대상이 아니게 된다.

    두 요청의 값은 **같다**(`몰랐음`). 어느 쪽이 경합을 이기는지는 정해지지 않으므로 값이
    다르면 남는 부수효과도 달라져(`알고 있었음`만으로는 FSRS 행이 생기지 않는다) 단정이
    실행마다 흔들린다. 같은 값이면 승자가 누구든 결과가 하나이고, 상한이 없을 때의 피해는
    그대로 두 배로 드러난다.
    """

    def call(value: str) -> httpx2.Response:
        return api.client.post(
            f"/api/study/presentations/{presentation_id}/self-report",
            json={
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": sentence_item_id,
                "value": value,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, "unknown"), pool.submit(call, "unknown")]
        return [future.result(timeout=30) for future in futures]


def _evidence_event_types(db: Session, *, presentation_id: int, learning_item_id: int) -> list[str]:
    rows = db.execute(
        sa.select(LearningEvent.event_type)
        .where(
            LearningEvent.study_presentation_id == presentation_id,
            LearningEvent.learning_item_id == learning_item_id,
            LearningEvent.event_type.in_(FSRS_RATING_EVENTS),
        )
        .order_by(LearningEvent.id)
    )
    return [event_type.value for event_type in rows.scalars()]


def _open_presentation(api: StudyApi) -> Mapping[str, Any]:
    started = api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]
    shown = api.client.post(f"/api/study/session/{session_id}/next")
    assert shown.status_code == 200, shown.text
    payload = shown.json()["presentation"]
    assert isinstance(payload, dict), "ready pool이 비었다"
    return payload


def test_concurrent_self_reports_record_one_evidence(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동시 self-report 2건 중 하나만 기록된다. 다른 하나는 409다.

    500이 아니다 --- 경합에서 진 요청이 받는 응답은 "이미 기록했습니다"이고, 그것이
    2회차 요청에 명세가 요구하는 바로 그 409다.
    """
    _seed_ready_sentences(committed_db)
    payload = _open_presentation(committed_api)
    presentation_id = payload["presentation_id"]
    tappable = payload["tappable_items"][0]

    _install_race(monkeypatch)
    responses = _self_report_twice(
        committed_api, presentation_id, sentence_item_id=tappable["sentence_item_id"]
    )

    with committed_db() as observer:
        recorded = _evidence_event_types(
            observer,
            presentation_id=presentation_id,
            learning_item_id=tappable["learning_item_id"],
        )
        counted = list(observer.execute(sa.select(UserMastery.evidence_count)).scalars())
        reps = list(observer.execute(sa.select(ReviewState.reps)).scalars())

    assert recorded == ["self_report_unknown"], (
        f"한 노출에 evidence가 {len(recorded)}건이다: {recorded}"
    )
    assert sorted(response.status_code for response in responses) == [204, 409], [
        (response.status_code, response.text) for response in responses
    ]
    # evidence 2건의 실제 피해는 event row가 아니라 여기다. EMA는 역함수가 없고
    # `reps`도 되돌릴 수 없다(07_SRS_SPEC.md의 `정정은 하지 않는다`).
    assert counted == [1], f"mastery evidence_count가 {counted}다"
    assert reps == [1], f"FSRS reps가 {reps}다"


def test_concurrent_self_reports_on_an_item_in_review_record_one_evidence(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이미 복습 중인 item에서도 evidence는 1건이다.

    위 테스트와 시나리오가 같고 **전제만 다르다.** 여기서는 `user_mastery`와
    `review_states`가 이미 있으므로 두 요청 중 누구도 남의 제약에 걸려 넘어지지 않는다.
    상한이 DB에 없으면 evidence 2건이 그대로 **커밋된다** --- 그리고 뒤에 도착한 쪽의
    EMA가 앞의 것을 덮어써서 사용자가 답한 두 건 중 하나가 조용히 사라진다. 두 피해 모두
    immutable log와 `review_states`에 남고 되돌릴 수 없다(`정정은 하지 않는다`).
    """
    _seed_item_already_in_review(committed_db, committed_api.user)
    payload = _open_presentation(committed_api)
    presentation_id = payload["presentation_id"]
    tappable = payload["tappable_items"][0]

    _install_race(monkeypatch)
    responses = _self_report_twice(
        committed_api, presentation_id, sentence_item_id=tappable["sentence_item_id"]
    )

    with committed_db() as observer:
        recorded = _evidence_event_types(
            observer,
            presentation_id=presentation_id,
            learning_item_id=tappable["learning_item_id"],
        )

    assert recorded == ["self_report_unknown"], (
        f"한 노출에 evidence가 {len(recorded)}건이다: {recorded}"
    )
    assert sorted(response.status_code for response in responses) == [204, 409], [
        (response.status_code, response.text) for response in responses
    ]
