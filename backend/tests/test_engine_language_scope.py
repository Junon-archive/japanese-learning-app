"""엔진의 언어 범위 (불변식 22, MVP-03, 06_LEARNING_ENGINE.md의 `언어 범위`).

**엔진은 언어를 모른다. 언어는 조회 범위로만 들어온다.** 이 파일은 그 범위가 실제로
걸리는지를 Ready Pool / materialization / exploration / backlog / probe 다섯 자리에서
검증한다. 다른 언어의 content를 만들어 두고, 그것이 반대 언어 세션에 전혀 새지
않는다는 **부재**를 단언한다.

`user_sentence_candidates`에는 `language` 컬럼이 없으므로(불변식 21) 이 테스트는
`sentences`를 거쳐 범위를 확인한다. `learning_items` 기준 조회(exploration 후보)는
`learning_items.language`로 직접 확인한다.

candidate는 손으로 INSERT하지 않고 `materialize_candidates`를 실제로 호출해서 Ready
Pool을 만든다(06_LEARNING_ENGINE.md의 `테스트에서의 candidate 구성`).
"""

from __future__ import annotations

from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_config
from app.learning.probe import select_probe_target
from app.learning.selection import choose_ratios, count_backlog, materialize_candidates, select_next
from app.models import (
    LearningItem,
    Sentence,
    User,
    UserSentenceCandidate,
    UserSentenceCandidateTarget,
)
from app.models.enums import Language, PresentationRole
from tests import factories
from tests.clock import MutableClock
from tests.conftest import override_config

pytestmark = pytest.mark.integration


def _fresh_item_with_ready_sentence(
    db: Session, *, language: Language, lemma: str
) -> tuple[LearningItem, Sentence]:
    """mastery도 learning state도 없는 item 하나 + Ready invariant를 만족하는 문장.

    후보 조건(1. mastery NULL, 2. is_active_learning_target 없음, 3. 최근 미노출)을
    전부 만족하므로 cold start의 exploration 후보가 된다(06_LEARNING_ENGINE.md의
    `Exploration Item 선정`).
    """
    item = factories.make_learning_item(db, language=language, lemma=lemma)
    sentence = factories.make_ready_sentence(db, [item], language=language, surfaces=[lemma])
    return item, sentence


def _candidate_sentence_languages(db: Session, *, user_id: int) -> set[Language]:
    rows = db.execute(
        sa.select(Sentence.language)
        .join(UserSentenceCandidate, UserSentenceCandidate.sentence_id == Sentence.id)
        .where(UserSentenceCandidate.user_id == user_id)
        .distinct()
    ).scalars()
    return set(rows)


def _candidate_target_item_ids(db: Session, *, user_id: int) -> set[int]:
    rows = db.execute(
        sa.select(UserSentenceCandidateTarget.learning_item_id)
        .join(
            UserSentenceCandidate,
            UserSentenceCandidate.id == UserSentenceCandidateTarget.candidate_id,
        )
        .where(UserSentenceCandidate.user_id == user_id)
        .distinct()
    ).scalars()
    return set(rows)


@pytest.mark.parametrize(
    ("session_language", "other_language"),
    [
        pytest.param(Language.JA, Language.EN, id="ja_session"),
        pytest.param(Language.EN, Language.JA, id="en_session"),
    ],
)
def test_materialization_and_ready_pool_never_cross_into_the_other_language(
    db_session: Session, session_language: Language, other_language: Language
) -> None:
    """materialization이 다른 언어로 candidate를 만들지 않고, Ready Pool에도 섞이지 않는다.

    같은 사용자에게 두 언어의 콘텐츠를 모두 준비한 뒤, 이 세션 언어로
    `materialize_candidates`를 한 번 실행한다. 결과 Ready Pool의 모든 candidate는
    그 문장도, 그 target item도 전부 이 세션의 언어여야 한다.
    """
    cfg = get_config()
    clock = MutableClock()
    user = factories.make_user(db_session)
    session_item, _session_sentence = _fresh_item_with_ready_sentence(
        db_session, language=session_language, lemma="このご session"
    )
    other_item, other_sentence = _fresh_item_with_ready_sentence(
        db_session, language=other_language, lemma="that other"
    )

    created = materialize_candidates(
        db_session, user=user, now=clock.now(), cfg=cfg.learning, language=session_language
    )

    assert created >= 1, (
        "이 언어의 exploration candidate가 하나도 안 만들어지면 테스트 자체가 무의미하다"
    )

    # Ready Pool에 다른 언어의 문장이 전혀 없다.
    assert _candidate_sentence_languages(db_session, user_id=user.id) == {session_language}

    # materialization이 다른 언어의 문장으로 candidate를 만들지 않았다.
    other_candidate_count = db_session.execute(
        sa.select(sa.func.count())
        .select_from(UserSentenceCandidate)
        .where(
            UserSentenceCandidate.user_id == user.id,
            UserSentenceCandidate.sentence_id == other_sentence.id,
        )
    ).scalar_one()
    assert other_candidate_count == 0

    # exploration 후보(target item)에 다른 언어의 item이 없다.
    target_ids = _candidate_target_item_ids(db_session, user_id=user.id)
    assert session_item.id in target_ids
    assert other_item.id not in target_ids


@pytest.mark.parametrize(
    ("session_language", "other_language"),
    [
        pytest.param(Language.JA, Language.EN, id="ja_session"),
        pytest.param(Language.EN, Language.JA, id="en_session"),
    ],
)
def test_select_next_never_returns_the_other_languages_item_as_a_probe_target(
    db_session: Session, session_language: Language, other_language: Language
) -> None:
    """select_next의 target_item_ids가 probe 후보의 재료다. 거기에 다른 언어 item이 없다.

    probe 대상 선정(`app/learning/probe.py`)은 그 자체로는 언어를 모른다 --- 호출부가
    건네는 `target_item_ids`만 본다. 그 재료가 이미 세션 언어로 거를러져 있어야
    probe도 안전하다. 이 테스트는 실제 presentation 재료(`select_next`)로 그것을
    증명한다. 다른 언어 item도 probe 우선순위(mastery 증거 없음)를 동일하게
    만족하도록 만들어서, 걸러지는 것이 우연이 아님을 보장한다.
    """
    cfg = get_config()
    clock = MutableClock()
    user = factories.make_user(db_session)
    study_session = factories.make_study_session(
        db_session,
        user,
        target_minutes=cfg.learning.default_session_minutes,
        language=session_language,
    )
    session_item, _ = _fresh_item_with_ready_sentence(
        db_session, language=session_language, lemma="このご probe"
    )
    other_item, _ = _fresh_item_with_ready_sentence(
        db_session, language=other_language, lemma="other probe"
    )

    selection = select_next(
        db_session,
        user=user,
        study_session_id=study_session.id,
        now=clock.now(),
        cfg=cfg.learning,
        language=session_language,
    )

    assert selection is not None
    assert other_item.id not in selection.target_item_ids
    assert session_item.id in selection.target_item_ids

    probe_target = select_probe_target(
        db_session,
        user_id=user.id,
        study_session_id=study_session.id,
        target_item_ids=selection.target_item_ids,
        now=clock.now(),
        config=cfg,
    )

    # 두 item 모두 probe 우선순위를 만족하므로(mastery 증거 없음), 후보 자체에
    # 다른 언어 item이 없다는 사실만으로 걸러진다 --- probe.py가 언어를 알아서가
    # 아니다.
    assert probe_target is not None
    assert probe_target.learning_item_id == session_item.id


def test_backlog_in_one_language_does_not_flip_the_other_languages_session_into_backlog_mode(
    db_session: Session,
) -> None:
    """불변식 22의 핵심: 영어 복습 적체가 일본어 세션의 Category Mix를 바꾸지 않는다.

    영어 due item을 `backlog_threshold`보다 훨씬 많이 쌓아 영어 자신은 backlog
    모드로 들어가게 만든 뒤(그래서 이 설정이 실제로 의미가 있다는 것을 증명한다),
    같은 사용자의 일본어 backlog 수는 threshold 밑에 그대로 있고, 일본어 세션의
    ratio는 평상시 세트 그대로임을 확인한다.
    """
    cfg = override_config(get_config(), learning={"backlog_threshold": 3})
    clock = MutableClock()
    user = factories.make_user(db_session)

    (ja_due_item,) = [
        factories.make_learning_item(db_session, language=Language.JA, lemma="ja_due")
    ]
    _due_review_state(db_session, user, ja_due_item, now=clock.now())

    en_due_items = [
        factories.make_learning_item(db_session, language=Language.EN, lemma=f"en_due_{i}")
        for i in range(cfg.learning.backlog_threshold + 2)
    ]
    for item in en_due_items:
        _due_review_state(db_session, user, item, now=clock.now())

    ja_backlog = count_backlog(db_session, user_id=user.id, language=Language.JA, now=clock.now())
    en_backlog = count_backlog(db_session, user_id=user.id, language=Language.EN, now=clock.now())

    assert ja_backlog == 1
    assert en_backlog == len(en_due_items)
    assert en_backlog >= cfg.learning.backlog_threshold, (
        "이 설정 자체가 영어를 backlog로 몰아넣지 못하면 테스트가 무의미하다"
    )
    assert ja_backlog < cfg.learning.backlog_threshold

    normal_ratios = {
        PresentationRole.REVIEW: cfg.learning.review_ratio,
        PresentationRole.NEW: cfg.learning.new_ratio,
        PresentationRole.EXPLORATION: cfg.learning.exploration_ratio,
    }
    backlog_ratios = {
        PresentationRole.REVIEW: cfg.learning.backlog_review_ratio,
        PresentationRole.NEW: cfg.learning.backlog_new_ratio,
        PresentationRole.EXPLORATION: cfg.learning.backlog_exploration_ratio,
    }

    assert choose_ratios(ja_backlog, cfg.learning) == normal_ratios, (
        "영어 backlog가 일본어 세션의 mix를 backlog 모드로 바꿨다"
    )
    assert choose_ratios(en_backlog, cfg.learning) == backlog_ratios


def _due_review_state(db: Session, user: User, item: LearningItem, *, now: datetime) -> None:
    state = factories.make_review_state(db, user, item, state=1, params_version="scope-test")
    state.next_review_at = now
    db.flush()
