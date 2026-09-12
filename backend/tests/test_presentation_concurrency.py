"""같은 세션에 동시 `/next` 2건 (05_API_SPEC.md의 `열린 presentation 불변식`).

불변식 자체의 판정은 `services/presentation.py`의 `SELECT ... LIMIT 1`이다. 잠금이
없으면 두 요청이 각자 "열린 presentation 없음"을 읽고 둘 다 만들 수 있고, 그러면 어느
쪽이 "현재 문장"인지 정의되지 않아 exposure와 context stage 전이가 두 갈래로 갈라진다.
프론트엔드의 단일 비행으로는 막을 수 없다 --- 두 탭과 직접 호출과 재시도가 남는다.

DB의 `uq_study_presentations_open`이 두 번째 INSERT를 거부하지만 거부만으로는 경합에서
진 요청이 500이 된다. 그래서 `/next`는 session 행을 `FOR UPDATE`로 잠근다. 이 파일이
보는 것은 그 둘의 합이다: **두 요청 모두 200이고 같은 문장을 받는다.** 인덱스가 실제로
거부하는지는 `test_db_constraints.py`가 본다.

`committed_db` / `committed_api`를 쓴다. `db_session`은 커넥션 하나 안에서 끝나므로 두
요청이 서로 다른 트랜잭션에 있는 상황 자체를 만들 수 없다(그 fixture의 docstring).
선례는 `test_jobs_queue.py`의 `FOR UPDATE SKIP LOCKED` 테스트다.

경합을 우연에 맡기지 않는다. `select_next`를 barrier로 감싸 **두 요청이 열린
presentation 조회를 끝낸 뒤에야** 만들기로 넘어가게 한다. 감싸는 자리가
`_open_presentation()` **다음**이라는 것이 요점이다 --- 그보다 앞을 막으면 재현하려는
순서가 아니다. 직렬화가 걸려 한쪽만 barrier에 도착하면 `RACE_TIMEOUT_SECONDS` 뒤
`BrokenBarrierError`로 풀린다. 그것이 고쳐진 구현의 정상 경로다.

시계는 `study_clock` 하나이므로 두 요청의 `now`가 같다. 그래서 `touch()`가 세션 행에
아무 UPDATE도 만들지 않고(값이 그대로다) 경합 창이 열린 채로 남는다 --- 요청마다 `now`가
다르면 그 UPDATE가 세션 행 잠금을 먼저 잡아 **우연히** 직렬화한다. 불변식이 벽시계 값이
겹치지 않는다는 우연에 기대면 안 되므로 여기서는 그 우연을 걷어낸 상태를 본다.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime

import httpx2
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.config import LearningConfig
from app.learning.selection import MaterializationGaps, Selection, select_next
from app.models.study import StudyPresentation
from app.models.user import User
from app.services import presentation as presentation_service
from tests import factories
from tests.conftest import StudyApi

pytestmark = pytest.mark.integration

# 상대 스레드를 기다리는 상한. 정책값이 아니라 테스트의 안전장치다 --- 직렬화가 걸린
# 구현에서는 상대가 영영 오지 않으므로 hang 대신 이 시간 뒤에 풀려야 한다.
RACE_TIMEOUT_SECONDS = 2.0

LEMMAS = ("任せる", "預ける", "頼む", "委ねる")


def _open_presentation_ids(db: Session, *, study_session_id: int) -> list[int]:
    return list(
        db.execute(
            sa.select(StudyPresentation.id)
            .where(
                StudyPresentation.study_session_id == study_session_id,
                StudyPresentation.completed_at.is_(None),
            )
            .order_by(StudyPresentation.id)
        )
        .scalars()
        .all()
    )


def _seed_ready_sentences(committed_db: sessionmaker[Session]) -> None:
    """서로 다른 item의 ready 문장 여럿. 후보가 하나면 경합이 후보 고갈로 흐려진다."""
    with committed_db() as setup:
        for lemma in LEMMAS:
            item = factories.make_learning_item(setup, lemma=lemma)
            factories.make_ready_sentence(setup, [item])
        setup.commit()


def _install_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_open_presentation()` 조회와 presentation 생성 사이에서 두 요청을 만나게 한다."""
    barrier = threading.Barrier(2)
    # `app.learning.selection`에서 직접 가져온다. `presentation_service.select_next`를
    # 읽으면 재적용(monkeypatch가 이미 걸린 상태)에서 wrapper를 감싸게 된다.
    real_select_next = select_next

    def racing_select_next(
        db: Session,
        *,
        user: User,
        study_session_id: int,
        now: datetime,
        cfg: LearningConfig,
        gaps: MaterializationGaps | None = None,
    ) -> Selection | None:
        with suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=RACE_TIMEOUT_SECONDS)
        return real_select_next(
            db, user=user, study_session_id=study_session_id, now=now, cfg=cfg, gaps=gaps
        )

    monkeypatch.setattr(presentation_service, "select_next", racing_select_next)


def _post_next_twice(api: StudyApi, session_id: int) -> list[httpx2.Response]:
    """같은 세션에 `/next` 2건을 진짜로 동시에 보낸다."""

    def call() -> httpx2.Response:
        return api.client.post(f"/api/study/session/{session_id}/next")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call), pool.submit(call)]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_next_requests_open_only_one_presentation(
    committed_api: StudyApi,
    committed_db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동시 `/next` 2건은 같은 문장 하나를 받는다. 열린 presentation은 1개다.

    500도 안 된다 --- 경합에서 진 요청에게 그것은 그냥 실패이고, client는 세션이 깨진
    것인지 다시 눌러도 되는지 알 수 없다.
    """
    _seed_ready_sentences(committed_db)

    started = committed_api.client.post("/api/study/session")
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["session_id"]

    _install_race(monkeypatch)
    responses = _post_next_twice(committed_api, session_id)

    for response in responses:
        assert response.status_code == 200, response.text
    presentation_ids = [
        response.json()["presentation"]["presentation_id"] for response in responses
    ]

    with committed_db() as observer:
        open_ids = _open_presentation_ids(observer, study_session_id=session_id)

    assert len(open_ids) == 1, f"한 세션에 열린 presentation이 {len(open_ids)}개다: {open_ids}"
    assert presentation_ids[0] == presentation_ids[1], (
        f"두 요청이 서로 다른 문장을 받았다: {presentation_ids}"
    )
    assert set(presentation_ids) == set(open_ids)
