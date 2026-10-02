"""MVP-03 영어 표현 후보 선별 (ADR-024 결정 2).

`data/wordlists/`의 공개 빈도 자료를 읽어 1차 300개 후보를 뽑는다. 원본 자료는 저장소에
커밋하지 않는다(불변식 27, 라이선스 때문) — 이 스크립트와 그 출력(`seed/en/*.yaml`)만
커밋한다.

절차 (spec/mvp-03-english/01_ENGLISH_CONTENT.md의 "선별 절차"):
    1 후보 모음 (스크립트)   A PHRASE List 구어 ★★★
                             B PHaVE List 구동사 1순위 sense
                             C NGSL-Spoken 720 안의 구어 단어
                             D 에이전트 작성 보완 (상황 목록 고정, 2012년 이후 구어)
    2 중복 제거 (스크립트)   PHaVE ∩ PHRASE -> PHaVE 쪽. 표면형 중복 -> 고빈도 쪽
    3 난이도 분류 (사람/LLM 판단, 이 스크립트에 상수로 고정)
                             already_known / shaky·unknown
    4 선별 (스크립트)        shaky+unknown 을 빈도 내림차순 상위 300. D 최소 60 보장
    5 사람 확인             (이 스크립트 밖. 사용자에게 후보 목록을 보여주고 진행한다)
    6 frequency_rank        최종 300 안에서 1..300
    7 예문·설명             (이 스크립트 밖. 에이전트가 직접 작성 -> build_english_seed.py)

3단계의 "이미 아는 표현" 판단은 학습자 전제(수능/전공 영어 이수, TOEIC 700대, OPIc IM2)를
기준으로 한 사람의 판단이며, 아래 EXCLUDE_* 상수에 그 판단을 그대로 남겨둔다 — 다시
실행해도 같은 300개가 나오게 하기 위해서다(재현성). 상수를 못 넘기는 경계 사례는
5단계(사람 확인)가 거른다.

사용법:
    uv run python scripts/select_english_candidates.py
    uv run python scripts/select_english_candidates.py --json-out /tmp/candidates.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
WORDLISTS = REPO_ROOT / "data" / "wordlists"

TARGET = 300
D_MIN = 60

# --------------------------------------------------------------------------
# 1. 후보 모음
# --------------------------------------------------------------------------


def load_pool_a_phrase() -> list[dict[str, Any]]:
    """PHRASE List에서 Spoken general이 '* * *'(구어 최고빈도)인 항목만 뽑는다."""
    path = WORDLISTS / "PHRASE_List.tsv"
    pool = []
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader)  # header
        for row in reader:
            if len(row) < 7:
                continue
            rank, phrase, freq, spoken, *_rest = row[:7]
            if spoken.strip() == "* * *":
                pool.append(
                    {
                        "lemma": phrase.strip().lower(),
                        "integrated_rank": int(rank),
                        "freq_per_100m": int(freq),
                    }
                )
    return pool


def load_pool_b_phave() -> list[dict[str, Any]]:
    """PHaVE List에서 구동사마다 1순위(가장 흔한) sense만 뽑는다."""
    path = WORDLISTS / "phave_list.txt"
    raw_lines = [line.rstrip("\n") for line in path.open(encoding="utf-8")]

    # 1순위 sense 설명이 줄바꿈으로 wrap되는 경우를 논리 줄로 합친다.
    logical: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        starts_new = bool(re.match(r"^\d+\.\s+\S", stripped))
        if starts_new or not logical:
            logical.append(stripped)
        else:
            logical[-1] = logical[-1].rstrip() + " " + stripped

    verb_re = re.compile(r"^(\d+)\.\s+([A-Z][A-Z \-']+?)\s*$")
    sense_re = re.compile(r"^1\.\s+(.*?)\s*\(([\d.]+)\s*%\)")

    pool: list[dict[str, Any]] = []
    current_verb: str | None = None
    got_first_sense: set[str] = set()
    for logline in logical:
        verb_match = verb_re.match(logline)
        if verb_match:
            current_verb = verb_match.group(2).strip()
            continue
        sense_match = sense_re.match(logline)
        if sense_match and current_verb and current_verb not in got_first_sense:
            pool.append(
                {
                    "lemma": current_verb.lower(),
                    "sense_pct": float(sense_match.group(2)),
                }
            )
            got_first_sense.add(current_verb)
    return pool


def load_pool_c_ngsl_spoken() -> list[dict[str, Any]]:
    """NGSL-Spoken 전체를 반환한다(순위 = 파일 내 줄 순서).

    주의: 이 파일에는 코퍼스 전사(transcript) 주석이 "단어"처럼 섞여 있다
    ([pause]/[unclear]/[laugh]/[laughter]가 원문에 pause/unclear/laugh/laughter로
    등장한다). 실제 어휘가 아니므로 CORPUS_ARTIFACTS로 걸러낸다.
    """
    path = WORDLISTS / "NGSL-Spoken_1.2.txt"
    pool = []
    for idx, line in enumerate(path.open(encoding="utf-8"), start=1):
        word = line.strip().lower()
        if word and word not in CORPUS_ARTIFACTS:
            pool.append({"lemma": word, "spoken_rank": idx})
    return pool


CORPUS_ARTIFACTS = {"pause", "unclear", "laugh", "laughter"}


# --------------------------------------------------------------------------
# 2단계에서 쓸 lemma 정규화 (PHRASE List 원본의 괄호 주석 제거)
# --------------------------------------------------------------------------


def normalize_lemma(lemma: str) -> str:
    text = lemma.lower()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[‘’'\"?!.,]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# PHRASE List 원본 표기를 실제 학습 lemma로 정리한다(주석은 참고용으로만 썼다).
LEMMA_CLEANUP = {
    "have got (+np)": "have got",
    "that is (rephrasing)": "that is",
    "after all (adv.)": "after all",
    "may well ('could')": "may well",
    "all over ('everywhere')": "all over",
    "something like (‘around’)": "something like",
    "or something ('perhaps')": "or something",
    "put it ('say')": "put it",
    "up to (decisions)": "up to",
    "happen to (be)": "happen to",
    "but then (again)": "but then again",
    "get to ('opportunity')": "get to",
    "to me ('in my opinion')": "to me",
    "a good (‘at least’)": "a good",
    "for all ('considering')": "for all",
    "a go (‘attempt’)": "a go",
    "as good as ('like')": "as good as",
    "to go (‘remaining’)": "to go",
}


# --------------------------------------------------------------------------
# 3단계: 난이도 분류 (학습자 전제 기준 사람 판단, 재현을 위해 상수로 고정)
# --------------------------------------------------------------------------
# 아래 EXCLUDE 집합에 없는 PHRASE/PHaVE/NGSL-Spoken 항목은 전부 "shaky 또는
# unknown"으로 간주해 후보에 남긴다(spec의 "의심스러우면 넣는다" 원칙).

EXCLUDE_PHRASE_ALREADY_KNOWN = {
    "have to",
    "there is/are",
    "going to (future)",
    "of course",
    "a few",
    "at least",
    "such a(n)",
    "a lot",
    "rather than",
    "so that",
    "a little",
    "a bit (of)",
    "as well as",
    "in fact",
    "(be) likely to",
    "at all",
    "used to (past)",
    "not only",
    "deal with",
    "as well",
    "take place",
    "tend to",
    "due to",
    "fail to",
    "each other",
    "in terms of",
    "no one",
    "up to (maximum)",
    "a single (‘any’)",
    "look for",
    "last night",
    "work on",
    "think about",
    "too much",
    "a couple of",
    "instead of",
    "come back",
    "look like",
    "find out",
    "point out",
    "apart from",
    "manage to",
    "be expected to",
    "long term",
    "even though",
    "a range of",
    "make sure",
    "take over",
    "as soon as",
    "at the time ('when this happened')",
    "on the other hand",
    "on one's own",
    "in front of ('before')",
    "a good/great deal ('much')",
    "on the way",
    "as long as",
    "so far ('until now')",
    "at the moment",
    "in (the sense) that",
    "as far as",
    "about to",
    "and so on",
    "look after",
    "at first",
    "in favour",
    "give up",
    "get to ('arrive at')",
    "get up",
    "go back",
    "it takes",
    "get on/off (trans)",
    "by the time",
    "lots of",
    "once again",
    "all the time",
    "rely on",
    "what about",
    "in other words",
    "not even",
    "in touch (with)",
    "in the end",
    "out of ('using')",
    "next to",
    "used to (accustomed)",
    "full time",
    "over there",
    "oh no",
    "in mind",
    "too many",
    "short term",
    "in case",
    "more and more",
    "believe in",
    "these days",
    "in charge",
    "feel like",
    "up to (until)",
    "heard of",
    "part time",
    "turn on",
    "this stage",
    "rid of",
    "in any case",
    "thanks to",
    "go away",
    "turn into",
    "by now",
    "think so",
    "at times",
    "afford to",
    "in advance",
    "take advantage",
    "over the years",
    "switch on",
    "could hardly",
    "in common",
    "no matter",
    "hand over",
    "in return (for)",
    "to some extent",
    "a long way",
    "for long",
    "right now",
    "nothing but",
    "out of (‘due to’)",
    "next door",
    "on the one hand",
    "bear in mind",
    "old fashioned",
    "most likely",
    "even so",
    "first of all",
    "worth of",
    "act on",
    "except that",
    "day to day",
    "as usual",
    "long before",
    "long ago",
    "up to date",
    "quite a lot",
    "on the whole",
    "make use of",
    "when it comes to",
    "a question of",
    "for life",
    "in the meantime",
    "would you like",
    "take for granted",
    "for the moment",
    "shut up",
    "as of",
    "would appear",
    "in theory",
    "thought of (as)",
    "common sense",
    "take care of",
    "the whole thing",
    "head to",
    "what if",
    "the bulk of",
    "a handful of",
    "(at) the outset",
    "by far",
    "in one’s own right",
    "a case of",
    "more so",
    "no sign of",
    "just as (‘when’)",
    "for the sake of",
    "in a position to",
    "to come (future)",
    "at best",
    "fond of",
    "well being",
    "how about",
    "straight away",
    "the lot",
    "make up one’s mind",
}

EXCLUDE_PHAVE_ALREADY_KNOWN_OR_TAUGHT = {
    "come back",
    "go back",
    "find out",
    "point out",
    "grow up",
    "set up",
    "come in",
    "give up",
    "figure out",
    "sit down",
    "get up",
    "take out",
    "go down",
    "stand up",
    "come down",
    "go up",
    "wake up",
    "carry out",
    "take over",
    "pull out",
    "turn around",
    "look up",
    "look down",
    "bring back",
    "bring in",
    "check out",
    "look around",
    "go in",
    "get off",
    "put down",
    "reach out",
    "cut off",
    "turn back",
    "clean up",
    "shut down",
    "slow down",
    "line up",
    "pull back",
    "build up",
    "put on",
    "move in",
    "sit up",
    "put back",
    "send out",
    "get in",
    "shut up",
    "turn off",
    "bring about",
    "lay down",
    "stand out",
    "write down",
    "move back",
    "fill out",
    "move up",
    "pick out",
    "give back",
    "hand over",
    "sum up",
    "move out",
    "set down",
    "follow up",
    "give out",
    "close down",
    "put in",
    "set about",
}

INCLUDE_NGSL_SPOKEN_SHAKY = {
    "well",
    "right",
    "thing",
    "stuff",
    "actually",
    "guess",
    "whatever",
    "guy",
    "deal",
    "totally",
    "fine",
    "cool",
    "basically",
    "anyway",
    "exactly",
    "bet",
    "matter",
    "real",
    "kid",
    "man",
    "wait",
    "true",
    "business",
    "stand",
    "fair",
    "worth",
    "purpose",
    "wonder",
    "funny",
    "pretty",
    "quite",
    "point",
    "catch",
    "like",
    "so",
    "just",
    "look",
    "listen",
}

# 4. (D) 에이전트가 직접 쓰는 2012년 이후·현대 구어 보완 목록. (lemma, type, topic_tags)
POOL_D_SUPPLEMENT: list[tuple[str, str, list[str]]] = [
    ("gonna", "word", ["contraction", "daily"]),
    ("wanna", "word", ["contraction", "daily"]),
    ("gotta", "word", ["contraction", "daily"]),
    ("kinda", "word", ["contraction", "daily"]),
    ("outta", "word", ["contraction", "daily"]),
    ("lemme", "word", ["contraction", "daily"]),
    ("gimme", "word", ["contraction", "daily"]),
    ("ain't", "word", ["contraction", "daily"]),
    ("y'all", "word", ["contraction", "colloquial", "daily"]),
    ("dunno", "word", ["contraction", "daily"]),
    ("you good?", "expression", ["formulaic", "friends", "health"]),
    ("my bad", "expression", ["formulaic", "friends"]),
    ("i'm down", "expression", ["formulaic", "friends"]),
    ("i'm good", "expression", ["formulaic", "friends", "food"]),
    ("no biggie", "expression", ["formulaic", "friends"]),
    ("it's all good", "expression", ["formulaic", "friends"]),
    ("sounds good", "expression", ["formulaic", "work", "friends"]),
    ("works for me", "expression", ["formulaic", "work", "friends"]),
    ("i feel you", "expression", ["formulaic", "friends"]),
    ("i hear you", "expression", ["formulaic", "friends", "work"]),
    ("for real", "expression", ["formulaic", "colloquial", "friends"]),
    ("to be honest", "expression", ["discourse-marker", "friends", "work"]),
    ("catch you later", "expression", ["formulaic", "friends"]),
    ("hang in there", "expression", ["formulaic", "friends"]),
    ("take it easy", "expression", ["formulaic", "friends"]),
    ("hit me up", "expression", ["formulaic", "slang", "friends", "phone"]),
    ("keep in touch", "expression", ["formulaic", "friends"]),
    ("long time no see", "expression", ["formulaic", "friends", "smalltalk"]),
    ("speak of the devil", "expression", ["idiom", "friends", "smalltalk"]),
    ("give it a shot", "expression", ["idiom", "work", "friends"]),
    ("give it a rest", "expression", ["idiom", "friends"]),
    ("cut it out", "expression", ["idiom", "friends"]),
    ("knock it off", "expression", ["idiom", "friends"]),
    ("chill out", "expression", ["phrasal-verb", "friends"]),
    ("freak out", "expression", ["phrasal-verb", "friends", "daily"]),
    ("zone out", "expression", ["phrasal-verb", "daily", "work"]),
    ("space out", "expression", ["phrasal-verb", "daily", "work"]),
    ("stick around", "expression", ["phrasal-verb", "friends", "daily"]),
    ("drop by", "expression", ["phrasal-verb", "friends", "travel"]),
    ("swing by", "expression", ["phrasal-verb", "friends", "travel"]),
    ("break a leg", "expression", ["idiom", "work", "smalltalk"]),
    ("piece of cake", "expression", ["idiom", "work", "daily"]),
    ("what's up", "expression", ["formulaic", "friends", "smalltalk"]),
    ("what's good", "expression", ["formulaic", "slang", "friends"]),
    ("not gonna lie", "expression", ["formulaic", "colloquial", "friends"]),
    ("low-key", "word", ["slang", "friends"]),
    ("no cap", "expression", ["slang", "friends"]),
    ("fair enough", "expression", ["formulaic", "work", "friends"]),
    ("tell me about it", "expression", ["idiom", "friends", "smalltalk"]),
    ("you're telling me", "expression", ["idiom", "friends", "smalltalk"]),
    ("i can't even", "expression", ["formulaic", "slang", "friends"]),
    ("that's on me", "expression", ["formulaic", "friends", "food"]),
    ("my treat", "expression", ["formulaic", "friends", "food"]),
    ("let's split it", "expression", ["formulaic", "friends", "food", "shopping"]),
    ("keep the change", "expression", ["formulaic", "shopping", "food"]),
    ("for here or to go", "expression", ["formulaic", "food"]),
    ("can i get a...", "expression", ["formulaic", "food", "shopping"]),
    ("check, please", "expression", ["formulaic", "food"]),
    ("suit yourself", "expression", ["formulaic", "friends"]),
    ("your call", "expression", ["idiom", "friends", "work"]),
    ("no pressure", "expression", ["formulaic", "friends", "work"]),
    ("take your time", "expression", ["formulaic", "friends", "work"]),
    ("my pleasure", "expression", ["formulaic", "work", "smalltalk"]),
    ("don't mention it", "expression", ["formulaic", "smalltalk"]),
    ("i owe you one", "expression", ["idiom", "friends"]),
    ("we're even", "expression", ["idiom", "friends"]),
    ("i got this", "expression", ["formulaic", "friends", "work"]),
    ("bring it on", "expression", ["formulaic", "friends", "work"]),
    ("i'm beat", "expression", ["idiom", "daily", "health"]),
    ("under the weather", "expression", ["idiom", "health"]),
    ("come down with", "expression", ["phrasal-verb", "health"]),
    ("out of it", "expression", ["idiom", "health", "daily"]),
    ("burnt out", "expression", ["idiom", "work", "health"]),
    ("called in sick", "expression", ["formulaic", "work", "health"]),
    ("running late", "expression", ["formulaic", "daily", "work", "travel"]),
    ("get the picture", "expression", ["idiom", "friends", "work"]),
    ("make it up to you", "expression", ["idiom", "friends"]),
    ("ghosting", "word", ["slang", "friends"]),
    ("binge-watch", "word", ["slang", "daily", "smalltalk"]),
]

GRAMMAR_LEMMAS = {
    "ought to",
    "had better",
    "might as well",
    "supposed to",
    "bound to",
    "let alone",
    "could hardly",
    "may well",
    "have got to",
    "have got",
}

DISCOURSE_MARKER_LEMMAS = {
    "i mean",
    "you see",
    "oh well",
    "mind you",
    "never mind",
    "by the way",
    "well",
    "actually",
    "right",
    "basically",
    "so",
    "just",
    "like",
    "anyway",
    "exactly",
    "to me",
    "that is",
    "put it",
    "look",
    "listen",
    "guess",
}

HEDGE_COLLOQUIAL_LEMMAS = {
    "sort of",
    "kind of",
    "or something",
    "or anything",
    "all sorts of",
    "that sort of thing",
    "and all that",
    "something like that",
    "things like that",
    "something like",
    "or whatever",
    "more or less",
    "just about",
    "a bit of a",
    "some kind of",
    "something about",
    "something of a",
}


def classify_pool_a(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for entry in raw:
        if entry["lemma"] in EXCLUDE_PHRASE_ALREADY_KNOWN:
            continue
        lemma = LEMMA_CLEANUP.get(entry["lemma"], entry["lemma"])
        out.append({**entry, "lemma": lemma, "source": "A_PHRASE"})
    return out


def classify_pool_b(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**entry, "source": "B_PHAVE"}
        for entry in raw
        if entry["lemma"] not in EXCLUDE_PHAVE_ALREADY_KNOWN_OR_TAUGHT
    ]


def classify_pool_c(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**entry, "source": "C_NGSL_SPOKEN"}
        for entry in raw
        if entry["lemma"] in INCLUDE_NGSL_SPOKEN_SHAKY
    ]


def build_pool_d() -> list[dict[str, Any]]:
    return [
        {"lemma": lemma, "type": type_, "topic_tags": tags, "source": "D_AGENT"}
        for lemma, type_, tags in POOL_D_SUPPLEMENT
    ]


def classify_type_and_tags(lemma: str, source: str, raw: dict[str, Any]) -> tuple[str, list[str]]:
    if source == "D_AGENT":
        return raw["type"], list(raw["topic_tags"])
    if source == "C_NGSL_SPOKEN":
        tag = "discourse-marker" if lemma in DISCOURSE_MARKER_LEMMAS else "colloquial"
        return "word", [tag, "daily"]
    if source == "B_PHAVE":
        return "expression", ["phrasal-verb", "daily"]
    # A_PHRASE
    if lemma in GRAMMAR_LEMMAS:
        return "grammar", ["daily"]
    if lemma in DISCOURSE_MARKER_LEMMAS:
        return "expression", ["discourse-marker", "daily"]
    if lemma in HEDGE_COLLOQUIAL_LEMMAS:
        return "expression", ["colloquial", "daily"]
    return "expression", ["idiom", "daily"]


MODERN_SLANG_INTERMEDIATE = {"not gonna lie", "low-key", "no cap", "what's good"}


def difficulty_for(lemma: str, item_type: str, source: str) -> str:
    if item_type == "grammar":
        return "advanced"
    if item_type == "word":
        return "beginner"
    if source == "D_AGENT":
        return "intermediate" if lemma in MODERN_SLANG_INTERMEDIATE else "beginner"
    return "intermediate"


# --------------------------------------------------------------------------
# 2단계: 중복 제거, 4단계: 최종 선별
# --------------------------------------------------------------------------


def select_candidates() -> list[dict[str, Any]]:
    pool_a = classify_pool_a(load_pool_a_phrase())
    pool_b = classify_pool_b(load_pool_b_phave())
    pool_c = classify_pool_c(load_pool_c_ngsl_spoken())
    pool_d = build_pool_d()

    # A ∩ B -> PHaVE(B) 쪽을 남긴다.
    b_keys = {normalize_lemma(e["lemma"]) for e in pool_b}
    pool_a = [e for e in pool_a if normalize_lemma(e["lemma"]) not in b_keys]

    # 공개 목록(A+B+C) 안에서 percentile 정규화 -> 고빈도일수록 작은 값
    def add_scored(
        pool: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any], reverse: bool
    ) -> list[tuple[float, dict[str, Any]]]:
        ordered = sorted(pool, key=key, reverse=reverse)
        n = max(len(ordered) - 1, 1)
        return [(i / n, e) for i, e in enumerate(ordered)]

    scored = []
    scored += add_scored(pool_a, key=lambda e: e["integrated_rank"], reverse=False)
    scored += add_scored(pool_b, key=lambda e: e["sense_pct"], reverse=True)
    scored += add_scored(pool_c, key=lambda e: e["spoken_rank"], reverse=False)

    seen: dict[str, tuple[float, dict[str, Any]]] = {}
    for score, entry in scored:
        key = normalize_lemma(entry["lemma"])
        if key not in seen or score < seen[key][0]:
            seen[key] = (score, entry)
    natural = sorted(seen.values(), key=lambda pair: pair[0])
    natural_keys = {normalize_lemma(e["lemma"]) for _, e in natural}

    pool_d = [e for e in pool_d if normalize_lemma(e["lemma"]) not in natural_keys]

    take_natural = min(len(natural), TARGET - D_MIN)
    selected = [e for _, e in natural[:take_natural]]
    remaining = TARGET - len(selected)
    selected += pool_d[:remaining]

    result = []
    for rank, entry in enumerate(selected, start=1):
        item_type, tags = classify_type_and_tags(entry["lemma"], entry["source"], entry)
        result.append(
            {
                "seed_id": f"en_it_{rank:04d}",
                "frequency_rank": rank,
                "lemma": entry["lemma"],
                "source": entry["source"],
                "type": item_type,
                "topic_tags": tags,
                "difficulty_label": difficulty_for(entry["lemma"], item_type, entry["source"]),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out", type=Path, default=None, help="후보 목록을 JSON으로 저장할 경로"
    )
    args = parser.parse_args()

    if not WORDLISTS.is_dir():
        print(f"data/wordlists/를 찾을 수 없다: {WORDLISTS}", file=sys.stderr)
        print(
            "PHRASE List, PHaVE List, NGSL-Spoken 원본을 그 디렉터리에 두고 다시 실행해라.",
            file=sys.stderr,
        )
        return 1

    candidates = select_candidates()
    by_source: dict[str, int] = {}
    for c in candidates:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1

    print(f"선별된 후보: {len(candidates)}개")
    print(f"출처별: {by_source}")
    for c in candidates:
        print(f"{c['frequency_rank']:3d}. [{c['source']:14s}] {c['lemma']}")

    if args.json_out:
        args.json_out.write_text(
            json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nJSON 저장: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
