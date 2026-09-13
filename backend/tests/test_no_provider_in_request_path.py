"""불변식 #1의 **런타임 증명**: request 경로에서 provider client 호출이 0이다.

ADR-015의 `정적과 런타임의 분담`이 이 파일의 범위를 정한다. 정적 guard
(G4 / G11 / G12 / G13)는 `test_module_boundaries.py`에 있고 **모양**만 본다. 여기서는
"지금 이 요청이 실제로 무엇을 했는가"를 본다.

``` text
no_outbound_network()        요청 중에 바깥으로 소켓을 열면 실패
assert_no_provider_import()  provider SDK가 sys.modules에 있으면 실패
no_provider_module_import()  그 블록이 app.llm.* 를 **새로** 적재하면 실패
raising stub                 app.jobs.runner.run_job 등이 불리면 실패
별도 프로세스                API 프로세스에 그 모듈이 애초에 적재되지 않음
```

**"아무것도 안 해서" 통과하는 것을 막는 장치를 함께 둔다.** pool이 빈 세션이
provider를 부르지 않는 것은 request 경로가 enqueue조차 하지 않아도 참이다. 그래서 각
테스트는 호출 대신 무엇을 했는지(`generation_jobs` row, mastery row, presentation)를
positive 증거로 함께 단정한다.

`test_scenarios.py`의 Scenario E와 `test_core_e2e.py`도 같은 두 헬퍼를 쓴다. 그쪽의
주제는 학습 정책이고 network 단정은 곁들인 것이다 --- 이 파일은 반대로 경계 자체가
주제이며, 위 다섯 수단 중 뒤의 세 가지는 여기에만 있다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never

import httpx2
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.jobs import queue, runner, worker
from app.llm import provider as provider_module
from app.models import GenerationJob, ItemExposure, StudyPresentation, UserMastery
from app.models.enums import ExplicitSignal, JobType, PresentationRole
from app.services.auth import hash_password
from tests import factories
from tests.conftest import (
    STUDY_ORIGIN,
    STUDY_PASSWORD,
    StudyApi,
    assert_no_provider_import,
    no_outbound_network,
    no_provider_module_import,
    override_config,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

# 별도 프로세스가 요청까지 밟은 뒤 "적재되면 안 되는 것"으로 세는 이름. 접두어
# `app.llm`이 구현체 모듈(`app.llm.openai_provider`)과 seam(`app.llm.provider`) 둘 다를
# 덮는다 --- `12_TEST_PLAN.md`는 "실제 구현체 모듈과 provider SDK"를 함께 요구한다.
FORBIDDEN_IN_API_PROCESS = (
    "app.llm",
    "openai",
    "anthropic",
    # MVP-02 불변식 15 (ADR-021 G14 런타임): 형태소 분석기와 그 어댑터. API 이미지에는 설치되지도
    # 않는다. 전이 import(`api/` -> `services/seed_loader.py` -> `app.furigana`)는 정적 guard가
    # 못 잡으므로 여기서 잡는다.
    "app.furigana",
    "sudachipy",
    "sudachidict_core",
)

# 별도 프로세스에서 돌리는 탐침. 부모의 monkeypatch도 이미 적재된 모듈도 없는
# 상태에서 API를 띄우고 요청을 보낸 뒤 `sys.modules`를 보고한다. in-process 검사로는
# "다른 테스트 모듈이 먼저 import했다"와 "이 요청이 import했다"를 구분할 수 없다.
_PROBE = """
import json
import sys

from fastapi.testclient import TestClient

from app.main import create_app

origin, login_id, password = sys.argv[1:4]
app = create_app()
with TestClient(app, base_url="https://testserver", headers={"Origin": origin}) as client:
    login = client.post("/api/auth/login", json={"login_id": login_id, "password": password})
    started = client.post("/api/study/session")
    session_id = started.json()["session"]["session_id"]
    following = client.post("/api/study/session/%d/next" % session_id)

forbidden = json.loads(sys.argv[4])
loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
presentation = following.json()["presentation"]
sys.stdout.write(
    json.dumps(
        {
            "statuses": [login.status_code, started.status_code, following.status_code],
            "loaded": loaded,
            "render_segments": presentation and presentation["render_segments"],
        }
    )
)
"""


def _cfg(**sections: dict[str, Any]) -> AppConfig:
    """주입해서 쓰는 정책값. 기본값에 기대어 숫자를 단정하지 않는다."""
    return override_config(get_config(), **sections)


def _jobs(db: Session) -> list[GenerationJob]:
    return list(db.execute(sa.select(GenerationJob).order_by(GenerationJob.id)).scalars().all())


def _json(response: httpx2.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _explode(*args: object, **kwargs: object) -> Never:
    """worker 코드가 request 경로에서 불리면 그 자리에서 죽는다."""
    raise AssertionError("request 경로가 worker/provider 코드를 실행했다")


# --------------------------------------------------------------------------
# 모든 pool이 빈 세션
# --------------------------------------------------------------------------


def test_all_pools_empty_session_makes_no_outbound_connection(
    study_api: StudyApi, db_session: Session
) -> None:
    """seed도 콘텐츠도 없는 사용자의 `/session` -> `/next`.

    여기서 provider를 부르지 않는 것만 보면 **아무것도 하지 않는 구현도 통과한다.**
    그래서 `generation_jobs`에 role마다 1건이 생겼는지를 함께 단정한다 --- 호출 대신
    enqueue했다는 positive 증거다(Pool Fallback 3단계).
    """
    study_api.use_config(_cfg())

    with no_outbound_network(), no_provider_module_import():
        started = _json(study_api.client.post("/api/study/session"))
        session_id = started["session"]["session_id"]
        response = study_api.client.post(f"/api/study/session/{session_id}/next")

    assert_no_provider_import()
    assert response.status_code == 200, response.text
    assert response.json() == {"presentation": None}

    jobs = _jobs(db_session)
    assert [job.job_type for job in jobs] == [JobType.GENERATE_SENTENCE_BATCH] * len(
        PresentationRole
    ), "빈 pool이 replenishment job을 만들지 않았다 --- 호출도 enqueue도 없다"
    assert {job.payload_json["presentation_role"] for job in jobs} == {
        role.value for role in PresentationRole
    }


# --------------------------------------------------------------------------
# 학습 1회전 전 구간
# --------------------------------------------------------------------------


def test_full_core_flow_makes_no_provider_call(study_api: StudyApi, db_session: Session) -> None:
    """session -> next -> click -> self-report -> complete -> next.

    설명은 precomputed여야 한다(12_TEST_PLAN.md의 4단계 `live LLM 호출 0`). click이
    설명을 **생성**하는 구현이면 여기서 죽는다. positive 증거는 그 한 바퀴가 실제로
    학습 상태를 만들었다는 것(presentation / mastery / exposure)이다.
    """
    cfg = _cfg()
    study_api.use_config(cfg)
    item = factories.make_learning_item(db_session)
    sentence = factories.make_ready_sentence(db_session, [item])

    with no_outbound_network(), no_provider_module_import():
        started = _json(study_api.client.post("/api/study/session"))
        session_id = started["session"]["session_id"]

        shown = _json(study_api.client.post(f"/api/study/session/{session_id}/next"))[
            "presentation"
        ]
        assert shown is not None
        assert shown["sentence_id"] == sentence.id
        presentation_id = shown["presentation_id"]
        (tappable,) = shown["tappable_items"]
        sentence_item_id = tappable["sentence_item_id"]

        explanation = _json(
            study_api.client.post(
                f"/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click",
                json={"client_event_id": str(uuid.uuid4())},
            )
        )
        assert explanation["learning_item_id"] == item.id

        reported = study_api.client.post(
            f"/api/study/presentations/{presentation_id}/self-report",
            json={
                "client_event_id": str(uuid.uuid4()),
                "sentence_item_id": sentence_item_id,
                "value": ExplicitSignal.UNKNOWN.value,
            },
        )
        assert reported.status_code == 204, reported.text

        _json(study_api.client.post(f"/api/study/presentations/{presentation_id}/complete"))

        # `몰랐음`이 이 item을 학습 target으로 올리고 `/complete`가 유효 노출을 남겼으므로
        # 이어진 `/next`는 그 item을 `review` role로 다시 제시한다(ADR-013의 배타적 pool).
        # 그 재선정도 같은 블록 안에서 밟는다 --- 복습 문맥을 동기 생성하는 구현이 걸린다.
        again = _json(study_api.client.post(f"/api/study/session/{session_id}/next"))[
            "presentation"
        ]

    assert_no_provider_import()
    assert again is not None
    assert again["presentation_role"] == PresentationRole.REVIEW.value

    assert (
        db_session.execute(sa.select(sa.func.count()).select_from(StudyPresentation)).scalar_one()
        == 2
    )
    mastery = db_session.execute(
        sa.select(UserMastery).where(
            UserMastery.user_id == study_api.user.id, UserMastery.learning_item_id == item.id
        )
    ).scalar_one()
    assert mastery.evidence_count == 1
    assert (
        db_session.execute(sa.select(sa.func.count()).select_from(ItemExposure)).scalar_one() == 1
    )
    # 보여줄 것이 있었으므로 생성 요청은 없다. 이 한 줄이 없으면 "무엇이든 enqueue하면
    # 통과"가 되어 test_all_pools_empty_session... 쪽의 positive 증거가 무의미해진다.
    assert _jobs(db_session) == []


# --------------------------------------------------------------------------
# worker 코드로 가는 통로 (G4가 못 막는 구멍)
# --------------------------------------------------------------------------


def _study_route_paths(app: FastAPI) -> set[str]:
    """study 라우트의 경로 템플릿 전부. 새 endpoint가 이 검사에서 새지 않게 한다."""
    paths: set[str] = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        path = context.path or ""
        if isinstance(route, APIRoute) and path.startswith("/api/study"):
            paths.add(path)
    return paths


def test_request_path_never_reaches_the_worker_runner(
    study_api: StudyApi, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`app/jobs/`는 `app.llm`을 합법적으로 import한다. 그래서 G4를 통과하는 구멍이 남는다.

    `services/`가 "pool이 비었으니 지금 한 번 돌리자"로 `app.jobs.runner.run_job`을
    부르면 정적 검사에는 아무것도 걸리지 않는다(G12가 import를 막지만, 함수 안에서
    import하면 AST 검사의 대상 모양이 달라진다). 그 통로를 런타임에서 닫는다 ---
    worker 진입점 / claim / provider 생성을 전부 **부르면 죽는 stub**으로 바꾸고 study
    endpoint를 한 번씩 밟는다.

    module 속성을 patch하므로 함수 안에서 `from app.jobs.runner import run_job`을 하는
    구현도 걸린다(그 import는 patch 이후에 평가된다). 최상위 import만 하는 구현은
    G12가 정적으로 잡는다 --- 두 검사가 함께 통로를 덮는다.

    몇몇 endpoint는 4xx로 끝난다(다른 presentation의 `probe_id` 등). 그래도 라우트와
    service 진입까지는 실제로 실행되므로 이 검사의 대상은 밟힌다. 500이 나오면 stub이
    불린 것이므로 `TestClient`가 예외를 그대로 올린다.
    """
    cfg = _cfg()
    study_api.use_config(cfg)
    monkeypatch.setattr(runner, "run_job", _explode)
    monkeypatch.setattr(worker, "run_once", _explode)
    monkeypatch.setattr(worker, "run_worker", _explode)
    monkeypatch.setattr(queue, "claim_next_job", _explode)
    monkeypatch.setattr(provider_module, "build_provider", _explode)

    item = factories.make_learning_item(db_session)
    factories.make_ready_sentence(db_session, [item])

    client = study_api.client
    started = _json(client.post("/api/study/session"))
    session_id = started["session"]["session_id"]
    shown = _json(client.post(f"/api/study/session/{session_id}/next"))["presentation"]
    assert shown is not None
    pid = shown["presentation_id"]
    (tappable,) = shown["tappable_items"]
    item_id = tappable["sentence_item_id"]

    def _event() -> dict[str, object]:
        return {"client_event_id": str(uuid.uuid4())}

    # 경로 템플릿 -> 그 endpoint를 한 번 밟는 호출. 값이 함수인 이유는 순서가 있는
    # 상태 기계이기 때문이다(`/finish`는 마지막).
    walk: list[tuple[str, Callable[[], httpx2.Response]]] = [
        ("/api/study/session", lambda: client.get("/api/study/session")),
        (
            "/api/study/session/{session_id}/next",
            lambda: client.post(f"/api/study/session/{session_id}/next"),
        ),
        (
            "/api/study/presentations/{presentation_id}/items/{sentence_item_id}/click",
            lambda: client.post(
                f"/api/study/presentations/{pid}/items/{item_id}/click", json=_event()
            ),
        ),
        (
            "/api/study/presentations/{presentation_id}"
            "/items/{sentence_item_id}/explanation-revealed",
            lambda: client.post(
                f"/api/study/presentations/{pid}/items/{item_id}/explanation-revealed",
                json=_event(),
            ),
        ),
        (
            "/api/study/presentations/{presentation_id}/translation/reveal",
            lambda: client.post(
                f"/api/study/presentations/{pid}/translation/reveal", json=_event()
            ),
        ),
        (
            "/api/study/presentations/{presentation_id}/probe-response",
            lambda: client.post(
                f"/api/study/presentations/{pid}/probe-response",
                json={**_event(), "probe_id": pid, "value": "known"},
            ),
        ),
        (
            "/api/study/presentations/{presentation_id}/self-report",
            lambda: client.post(
                f"/api/study/presentations/{pid}/self-report",
                json={
                    **_event(),
                    "sentence_item_id": item_id,
                    "value": ExplicitSignal.KNOWN.value,
                },
            ),
        ),
        (
            "/api/study/presentations/{presentation_id}/complete",
            lambda: client.post(f"/api/study/presentations/{pid}/complete"),
        ),
        (
            "/api/study/presentations/{presentation_id}/flag",
            lambda: client.post(
                f"/api/study/presentations/{pid}/flag",
                json={**_event(), "reason": "unnatural"},
            ),
        ),
        (
            "/api/study/session/{session_id}/extend",
            lambda: client.post(f"/api/study/session/{session_id}/extend", json=_event()),
        ),
        (
            "/api/study/session/{session_id}/finish",
            lambda: client.post(f"/api/study/session/{session_id}/finish"),
        ),
        ("/api/study/session", lambda: client.post("/api/study/session")),
    ]

    with no_outbound_network(), no_provider_module_import():
        for path, call in walk:
            response = call()
            assert response.status_code < 500, f"{path} -> {response.status_code} {response.text}"

    assert_no_provider_import()
    covered = {path for path, _call in walk}
    missing = sorted(_study_route_paths(study_api.app) - covered)
    assert missing == [], f"이 검사가 밟지 않은 study endpoint가 있다: {missing}"


# --------------------------------------------------------------------------
# 별도 프로세스: 그 모듈이 애초에 적재되지 않는다
# --------------------------------------------------------------------------


def test_a_fresh_api_process_loads_neither_the_provider_module_nor_the_sdk(
    committed_db: sessionmaker[Session], database_url: URL, tmp_path: Path
) -> None:
    """`12_TEST_PLAN.md`: "실제 구현체 모듈과 provider SDK가 `sys.modules`에 적재되지도 않는다".

    in-process로는 이것을 증명할 수 없다. `test_llm_provider.py`가
    `app.llm.openai_provider`를 최상위에서 import하므로 전체 실행에서는 수집 시점에 이미
    적재되어 있고, 절대 집합 검사는 그 사실 때문에 영영 빨개진다. 그래서 **부모가 아무것도
    적재하지 않은 새 인터프리터**에서 API를 띄우고 요청을 밟은 뒤 `sys.modules`를 본다.

    `openai`는 단일 manifest라 API 이미지에도 설치된다(`pyproject.toml`의 dependencies).
    그러므로 경계를 지키는 것은 설치 여부가 아니라 **import 지점 하나**이며, 그것을
    확인하는 것이 이 테스트다.
    """
    with committed_db() as setup:
        user = factories.make_user(setup)
        user.password_hash = hash_password(STUDY_PASSWORD)
        # `/next`가 저장된 ruby를 실제로 잘라 싣는 경로까지 밟게 한다(MVP-02). 값은 분석기 없이
        # 손으로 넣는다 --- 부모 프로세스가 분석기를 불렀는지와 무관하게 자식이 요청을 밟는다.
        item = factories.make_learning_item(setup)
        sentence = factories.make_ready_sentence(setup, [item], surfaces=["任せる"])
        sentence.ruby_json = {"spans": [[0, 1, "まか"]]}
        setup.commit()
        login_id = user.login_id

    script = tmp_path / "probe_api_process.py"
    script.write_text(_PROBE, encoding="utf-8")
    completed = subprocess.run(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
        [
            sys.executable,
            str(script),
            STUDY_ORIGIN,
            login_id,
            STUDY_PASSWORD,
            json.dumps(FORBIDDEN_IN_API_PROCESS),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(BACKEND_ROOT),
            "DATABASE_URL": database_url.render_as_string(hide_password=False),
            "CORS_ALLOW_ORIGINS": STUDY_ORIGIN,
        },
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    # 요청이 실제로 끝까지 갔는지 먼저 본다. 부팅만 하고 끝난 프로세스는 아무것도
    # 증명하지 않는다.
    assert report["statuses"] == [200, 200, 200], completed.stdout
    # 저장된 ruby가 있는 문장을 실제로 제시했다. ruby를 자르는 경로를 밟지 않은 탐침은 분석기
    # 미적재를 증명하지 않는다.
    assert report["render_segments"] == [
        {
            "text": "任せる",
            "sentence_item_id": report["render_segments"][0]["sentence_item_id"],
            "ruby": [{"text": "任", "reading": "まか"}, {"text": "せる", "reading": None}],
        }
    ], completed.stdout
    assert report["loaded"] == [], f"API 프로세스가 금지 모듈을 적재했다: {report['loaded']}"
