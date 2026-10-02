"""저장소 위생 --- 외부 어휘 자료 원본이 저장소에 없다 (불변식 27, ADR-024 결정 1).

`spec/mvp-03-english/12_TEST_PLAN.md`의 `저장소 위생 (불변식 27)` 절과
`13_ACCEPTANCE_CRITERIA.md`의 29번이 요구하는 검사다. 보는 것은 네 가지다.

``` text
1 data/wordlists/ 가 .gitignore에 있고 git이 추적·기록한 적이 없다
2 git이 추적하는 파일 중 외부 자료 원본 데이터가 하나도 없다
3 seed/en/README.md 가 네 자료의 출처·저자·연도·라이선스를 적는다
4 seed/en 의 예문이 외부 자료의 예문과 같지 않다   (원본이 로컬에 있을 때만)
```

## 무엇을 금지하고 무엇을 허용하는가 (2번)

금지하는 것은 **원본 데이터가 커밋되는 것**이다. 파일 이름을 입에 올리는 것은 금지하지
않는다 --- `seed/en/README.md`의 출처 표기와 `scripts/select_english_candidates.py`가 그
파일을 **읽는** 코드는 둘 다 ADR-024 결정 1이 "커밋하는 것"으로 명시한 것이고, 인용은
share-alike를 트리거하지 않는다(`seed/en/README.md`의 `왜 원본을 커밋하지 않는가`).
그래서 검사는 두 축이다.

``` text
경로   wordlists 디렉터리 안의 파일, 원본 파일명 그대로인 데이터 파일(.tsv/.csv/...)  -> 금지
내용   원본 파일의 데이터 줄이 추적 파일 안에 그대로 있다                             -> 금지
언급   .md / .py / .yaml 이 자료 이름·파일명을 글로 적거나 경로로 조립한다            -> 허용
```

## DB를 쓰지 않는다

파일과 git만 본다. 그래서 `pytest.mark.integration`이 필요 없다
(`test_marker_hygiene.py`가 과잉 마킹도 실패로 잡는다).

## git이 없으면 skip이 아니라 실패다

`test_git_hygiene.py`의 모듈 docstring과 같은 이유다. 이 검사가 도는 곳에는 `.git`이 있다.

## 여기서 보지 않는 것

-   `items.yaml`에 `reading` 키가 없다 --- loader가 거부하고(`test_seed_reading_language_rule.py`
    의 `test_en_with_reading_is_rejected`) 실제 `seed/en/`이 그 loader를 통과한다
    (`test_seed_en_loads.py`의 `test_seed_en_items_have_no_reading_and_sentences_have_no_ruby`).
-   `frequency_rank`가 1..N 유일 --- `test_seed_en_loads.py`의
    `test_seed_en_frequency_rank_is_1_to_300`.
-   seed 적재 자체의 유효성(span, 중복, explanation 필수) --- `test_seed_en_loads.py`.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

SEED_EN_DIR = REPO_ROOT / "seed" / "en"
SEED_EN_README = SEED_EN_DIR / "README.md"
SEED_EN_ITEMS = SEED_EN_DIR / "items.yaml"
SEED_EN_SENTENCES = SEED_EN_DIR / "sentences.yaml"

CONTENT_SPEC = REPO_ROOT / "spec" / "mvp-03-english" / "01_ENGLISH_CONTENT.md"

# gitignore된 로컬 전용 디렉터리. CI와 다른 사람 머신에는 없다.
LOCAL_WORDLISTS = REPO_ROOT / "data" / "wordlists"
WORDLISTS_IGNORE_LINE = "data/wordlists/"

_GIT_TIMEOUT_SECONDS = 60

# ---------------------------------------------------------------------------
# 1 / 2. git
# ---------------------------------------------------------------------------

# 디렉터리 이름이 어디에 나와도 금지다. `data/wordlists/`만 보면 `backend/tests/data/
# wordlists/`로 옮겨 커밋하는 길이 열린다.
WORDLISTS_DIR_SEGMENT = "wordlists"

# `scripts/select_english_candidates.py`가 읽는 파일 + ADR-024 결정 1의 자료가 배포되는
# 파일명. 이름이 같은 데이터 파일은 어느 디렉터리에 있어도 원본으로 본다.
EXTERNAL_DATA_FILENAMES = frozenset(
    {
        "PHRASE_List.tsv",
        "PHRASE_List.doc",
        "PHRASE_List.html",
        "PHRASE_List_UsersGuide.doc",
        "phave_list.txt",
        "NGSL-Spoken_1.2.txt",
        "NGSL-Spoken_1.2_en.csv",
        "NGSL-1.01.csv",
        "NGSL-1.01_Supplemental.csv",
        "SUBTLEXus74286wordstextversion.tsv",
    }
)

# 이름을 조금 바꿔 커밋하는 길을 막는다. 자료 이름으로 **시작하는 데이터 파일**만
# 금지다 --- 문서(.md)·코드(.py)·우리 seed(.yaml)는 이름을 적어도 된다.
EXTERNAL_NAME_PREFIXES = ("phrase_list", "phave", "ngsl", "subtlex")
DATA_SUFFIXES = (".tsv", ".csv", ".txt", ".doc", ".docx", ".pdf", ".html", ".xls", ".xlsx")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None, "git이 PATH에 없다. 이 검사는 git 없이 통과할 수 없다(모듈 docstring)"
    return subprocess.run(  # noqa: S603  (인자를 우리가 만든다. 셸을 거치지 않는다)
        [git, "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def tracked_files() -> list[PurePosixPath]:
    completed = _git("ls-files", "-z")
    assert completed.returncode == 0, completed.stderr
    return [PurePosixPath(name) for name in completed.stdout.split("\0") if name]


def forbidden_as_external_data(path: PurePosixPath) -> str | None:
    """추적되면 안 되는 이유. 괜찮으면 None. 금지/허용 경계는 모듈 docstring을 본다."""
    if WORDLISTS_DIR_SEGMENT in path.parts[:-1]:
        return "외부 자료 디렉터리"
    if path.name in EXTERNAL_DATA_FILENAMES:
        return "외부 자료 원본 파일명"
    lowered = path.name.lower()
    if lowered.startswith(EXTERNAL_NAME_PREFIXES) and lowered.endswith(DATA_SUFFIXES):
        return "외부 자료 이름으로 시작하는 데이터 파일"
    return None


def test_the_repository_is_a_git_work_tree() -> None:
    """아래 git 검사들의 전제. 저장소 밖에서 돌면 빈 목록으로 조용히 통과한다."""
    completed = _git("rev-parse", "--show-toplevel")
    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()).resolve() == REPO_ROOT
    assert tracked_files(), "추적 파일이 하나도 없다"


def test_the_path_rule_recognizes_what_it_is_meant_to_block() -> None:
    """양성 대조군. 조건을 잘못 적은 규칙은 빈 결과로 통과한다.

    `allowed` 쪽이 이 검사의 핵심이다 --- 자료 이름을 **적는** 파일까지 막으면 출처
    표기(`seed/en/README.md`)와 선별 스크립트가 걸린다.
    """
    blocked = [
        "data/wordlists/PHRASE_List.tsv",
        "data/wordlists/README.md",
        "backend/tests/data/wordlists/sample.csv",
        "PHRASE_List.tsv",
        "docs/phave_list.txt",
        "seed/en/NGSL-Spoken_1.2.txt",
        "SUBTLEXus74286wordstextversion.tsv",
        "data/subtlex-us-full.csv",
    ]
    allowed = [
        "seed/en/README.md",
        "seed/en/items.yaml",
        "seed/en/sentences.yaml",
        "scripts/select_english_candidates.py",
        "scripts/build_english_seed.py",
        "docs/decisions/ADR-024-english-content-sourcing.md",
        "spec/mvp-03-english/01_ENGLISH_CONTENT.md",
        "backend/tests/test_repo_hygiene.py",
        ".gitignore",
    ]
    assert [p for p in blocked if forbidden_as_external_data(PurePosixPath(p)) is None] == []
    assert [p for p in allowed if forbidden_as_external_data(PurePosixPath(p)) is not None] == []


def test_no_external_wordlist_file_is_tracked() -> None:
    offenders = sorted(
        f"{path} ({reason})"
        for path in tracked_files()
        if (reason := forbidden_as_external_data(path)) is not None
    )
    assert offenders == [], f"외부 어휘 자료 원본이 추적되고 있다: {offenders}"


def test_the_wordlists_directory_was_never_committed() -> None:
    """index만 보면 "한 번 커밋했다가 지웠다"를 놓친다. 지운 커밋에도 원본은 남는다."""
    completed = _git("log", "--all", "--format=%H", "--", "data/wordlists")
    assert completed.returncode == 0, completed.stderr
    commits = completed.stdout.split()
    assert commits == [], f"data/wordlists/를 건드린 커밋이 있다: {commits}"


def test_gitignore_lists_the_wordlists_directory() -> None:
    """`.gitignore`에 그 경로가 **등록되어 있다**(합격 기준 29의 문장)."""
    lines = [
        line.strip() for line in Path(REPO_ROOT / ".gitignore").read_text("utf-8").splitlines()
    ]
    assert WORDLISTS_IGNORE_LINE in lines, f"{WORDLISTS_IGNORE_LINE}가 .gitignore에 없다"


def _is_ignored(relative_path: str) -> bool:
    """git이 실제로 무시하는가. 줄이 존재하는지가 아니라 동작을 본다(부정 패턴, 순서)."""
    completed = _git("check-ignore", "-q", "--no-index", "--", relative_path)
    # 0 = 무시한다, 1 = 무시하지 않는다, 그 밖 = 오류. 오류를 "무시한다"로 읽으면 안 된다.
    assert completed.returncode in (0, 1), completed.stderr
    return completed.returncode == 0


def test_git_actually_ignores_the_wordlists_directory() -> None:
    """양성 대조군을 같은 검사 안에 둔다 --- `check-ignore`가 아무것이나 무시한다고 답하면
    위 단언이 의미가 없다. 커밋해야 하는 산출물은 무시되지 **않아야** 한다."""
    ignored = [
        "data/wordlists/PHRASE_List.tsv",
        "data/wordlists/anything-at-all.csv",
        "data/wordlists/nested/deep.txt",
    ]
    not_ignored = [
        "seed/en/items.yaml",
        "seed/en/README.md",
        "scripts/select_english_candidates.py",
    ]
    assert [p for p in ignored if not _is_ignored(p)] == []
    assert [p for p in not_ignored if _is_ignored(p)] == []


# ---------------------------------------------------------------------------
# 2. 내용 --- 원본 데이터 줄이 추적 파일 안에 있는지
# ---------------------------------------------------------------------------

_SAMPLES_PER_FILE = 12
_MIN_SAMPLE_LENGTH = 40
_MAX_SAMPLE_LENGTH = 400


def _index_contains(patterns: list[str]) -> list[str]:
    """index의 텍스트 파일 중 주어진 문자열(고정 문자열)을 가진 파일 경로."""
    if not patterns:
        return []
    args = ["grep", "--cached", "-I", "-F", "-l"]
    for pattern in patterns:
        args += ["-e", pattern]
    completed = _git(*args)
    # 0 = 찾음, 1 = 없음, 그 밖 = 오류.
    assert completed.returncode in (0, 1), completed.stderr
    return completed.stdout.split()


def _sample_data_lines(path: Path) -> list[str]:
    """원본에서 "이 파일의 데이터"라고 할 만한 줄을 고르게 뽑는다. 못 읽으면 빈 목록."""
    try:
        raw = path.read_text("utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # PDF·.doc 같은 바이너리. 경로 검사가 맡는다.
    usable = [
        line
        for line in (line.strip() for line in raw.splitlines())
        if _MIN_SAMPLE_LENGTH <= len(line) <= _MAX_SAMPLE_LENGTH and line.isprintable()
    ]
    if not usable:
        return []
    step = max(1, len(usable) // _SAMPLES_PER_FILE)
    return usable[::step][:_SAMPLES_PER_FILE]


def test_the_index_grep_helper_finds_content_that_is_really_there() -> None:
    """양성 대조군. 커밋된 파일에서 가져온 줄은 반드시 찾아야 한다 --- 못 찾으면 아래
    검사가 "원본 데이터가 없다"가 아니라 "grep이 아무것도 못 본다"로 통과한다."""
    known = next(
        line.strip()
        for line in SEED_EN_README.read_text("utf-8").splitlines()
        if len(line.strip()) >= _MIN_SAMPLE_LENGTH
    )
    assert "seed/en/README.md" in _index_contains([known])


def test_no_tracked_file_contains_external_wordlist_data() -> None:
    """원본이 로컬에 있을 때만 돈다 --- 없으면 대조할 것이 없다.

    경로 검사(`test_no_external_wordlist_file_is_tracked`)는 이름을 보고, 이 검사는
    이름을 바꿔 커밋한 경우를 본다.
    """
    if not LOCAL_WORDLISTS.is_dir():
        pytest.skip(
            f"{LOCAL_WORDLISTS}가 없다. 원본은 gitignore라서(불변식 27) CI와 다른 머신에는 "
            "없는 것이 정상이고, 부재를 실패로 만들면 그 환경에서 늘 깨진다."
        )
    offenders: list[str] = []
    checked = 0
    for source in sorted(LOCAL_WORDLISTS.iterdir()):
        if not source.is_file():
            continue
        samples = _sample_data_lines(source)
        if not samples:
            continue
        checked += 1
        offenders += [
            f"{source.name} 의 데이터가 {path}에 있다" for path in _index_contains(samples)
        ]
    assert checked, f"{LOCAL_WORDLISTS}에서 텍스트로 읽을 수 있는 원본이 하나도 없었다"
    assert offenders == [], f"외부 자료 원본 데이터가 커밋되어 있다: {offenders}"


# ---------------------------------------------------------------------------
# 3. seed/en/README.md 의 출처 표기
# ---------------------------------------------------------------------------

# 자료마다 (이름, 저자, 연도 또는 버전, 라이선스, 출처) 키워드. 검사 수준은
# `12_TEST_PLAN.md`가 정한 "키워드 존재 확인 수준"이다. 단 문서 전체가 아니라 **그 자료
# 이름이 나오는 줄들** 안에서 찾는다 --- 문서 어딘가에 "CC BY-SA"가 있다는 것만으로는
# 어느 자료의 라이선스인지 알 수 없다.
#
# NGSL만 연도 자리에 버전(1.2)을 둔다. README와 ADR-024 결정 1이 둘 다 NGSL에 연도를 적지
# 않는다(버전으로 식별되는 자료다) --- 연도를 요구하면 명세의 배경 문서보다 엄격해진다.
# 그래서 이 한 자료의 연도/버전 칸은 사실상 이름(`NGSL-Spoken 1.2`)이 메우며, 독립적인
# 검사가 아니다. 연도 표기를 요구하기로 정하면 이 줄을 "2013"으로 바꾸면 된다.
README_SOURCES: tuple[tuple[str, str, str, str, str], ...] = (
    ("PHRASE List", "Martinez", "2012", "무료 배포", "norbertschmitt"),
    ("PHaVE List", "Garnier", "2015", "무료 배포", "norbertschmitt"),
    ("NGSL-Spoken", "Browne", "1.2", "CC BY-SA", "newgeneralservicelist"),
    ("SUBTLEX-US", "Brysbaert", "2009", "CC BY-SA", "lexique"),
)

_FIELD_LABELS = ("저자", "연도/버전", "라이선스", "출처")


def missing_source_fields(readme_text: str) -> list[str]:
    """출처 표기에서 빠진 `자료: 항목`. 전부 있으면 빈 목록."""
    lines = readme_text.splitlines()
    missing: list[str] = []
    for name, *fields in README_SOURCES:
        rows = [line for line in lines if name in line]
        if not rows:
            missing.append(f"{name}: 자료 이름 자체")
            continue
        for label, keyword in zip(_FIELD_LABELS, fields, strict=True):
            if not any(keyword in row for row in rows):
                missing.append(f"{name}: {label}({keyword})")
    return missing


def test_the_readme_rule_recognizes_an_incomplete_citation() -> None:
    """양성 대조군. 합성 README로 검사가 실제로 빈 칸을 잡는지 본다."""
    complete = "\n".join(
        f"| {name} | {author}, {year} | {license_} | {origin} |"
        for name, author, year, license_, origin in README_SOURCES
    )
    assert missing_source_fields(complete) == []

    no_license = complete.replace("CC BY-SA", "(미정)").replace("무료 배포", "(미정)")
    assert [m for m in missing_source_fields(no_license) if "라이선스" in m]

    without_ngsl = "\n".join(line for line in complete.splitlines() if "NGSL" not in line)
    assert "NGSL-Spoken: 자료 이름 자체" in missing_source_fields(without_ngsl)


def test_seed_en_readme_cites_all_four_sources() -> None:
    assert SEED_EN_README.is_file(), f"{SEED_EN_README}가 없다"
    missing = missing_source_fields(SEED_EN_README.read_text("utf-8"))
    assert missing == [], f"출처 표기에서 빠진 것: {missing}"


# ---------------------------------------------------------------------------
# 4. seed/en 의 예문이 외부 자료의 예문과 같지 않다
# ---------------------------------------------------------------------------

PHRASE_LIST_TSV = LOCAL_WORDLISTS / "PHRASE_List.tsv"
PHAVE_LIST_TXT = LOCAL_WORDLISTS / "phave_list.txt"

# PHaVE 원본은 sense 설명 아래에 예문을 깊게 들여써서 적는다. 들여쓰기가 예문의 표시다.
_PHAVE_EXAMPLE_INDENT = "     "


def normalized_sentence(text: str) -> str:
    """문장 동일성 비교용 정규화. 따옴표·대소문자·공백 차이로 베낀 것이 숨지 않게 한다.

    원본은 curly apostrophe(U+2019)를 쓰고 우리 YAML은 ASCII를 쓴다 --- 그 차이만으로
    "다른 문장"이 되면 이 검사가 아무것도 못 잡는다.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def external_examples() -> dict[str, tuple[str, str]]:
    """정규화한 예문 -> (자료, 원문). 예문 열을 가진 두 자료만 본다."""
    examples: dict[str, tuple[str, str]] = {}

    with PHRASE_LIST_TSV.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = [column.strip() for column in next(reader)]
        # 열 위치가 바뀌면 조용히 빈 목록이 되는 것을 막는다.
        assert header[6] == "Example", f"PHRASE List의 열 구성이 예상과 다르다: {header}"
        for row in reader:
            if len(row) >= 7 and row[6].strip():
                examples.setdefault(normalized_sentence(row[6]), ("PHRASE List", row[6].strip()))

    for line in PHAVE_LIST_TXT.read_text("utf-8").splitlines():
        if line.startswith(_PHAVE_EXAMPLE_INDENT) and line.strip():
            examples.setdefault(normalized_sentence(line), ("PHaVE List", line.strip()))

    examples.pop("", None)
    return examples


def seed_en_english_texts() -> list[tuple[str, str, str]]:
    """`(seed_id, 필드, 영어 원문)`. 문장과 설명의 `example_sentence` 둘 다 본다."""
    sentences: list[dict[str, Any]] = yaml.safe_load(SEED_EN_SENTENCES.read_text("utf-8"))
    rows: list[tuple[str, str, str]] = []
    for sentence in sentences:
        rows.append((sentence["seed_id"], "text", sentence["text"]))
        for item in sentence["items"]:
            explanation = item.get("explanation")
            if explanation and explanation.get("example_sentence"):
                rows.append(
                    (
                        sentence["seed_id"],
                        "explanation.example_sentence",
                        explanation["example_sentence"],
                    )
                )
    return rows


def copied_examples(
    ours: list[tuple[str, str, str]], external: dict[str, tuple[str, str]]
) -> list[str]:
    """외부 예문과 같은 우리 문장. 같은 것이 없으면 빈 목록."""
    offenders: list[str] = []
    for seed_id, field, text in ours:
        found = external.get(normalized_sentence(text))
        if found is not None:
            source, raw = found
            offenders.append(f"{seed_id}.{field} {text!r} == {source} {raw!r}")
    return offenders


def test_the_copy_detector_catches_a_copied_example() -> None:
    """양성 대조군. 외부 자료 없이 돈다 --- 비교 함수 자체를 합성 입력으로 검증한다."""
    # 원본이 쓰는 curly apostrophe(U+2019)를 `chr`로 만든다 --- 리터럴로 적으면 ruff
    # RUF001(ambiguous unicode)이 막는다.
    external_raw = f"I didn{chr(0x2019)}t go, but I was supposed to."
    external = {normalized_sentence(external_raw): ("sample", external_raw)}
    copied = [("en_sn_0001", "text", "I didn't go, but I was supposed to.")]
    reworded = [("en_sn_0001", "text", "I was supposed to call her, but I forgot.")]

    assert copied_examples(copied, external), "따옴표·대소문자만 다른 복사를 잡지 못한다"
    assert copied_examples(reworded, external) == []


def test_seed_en_examples_are_not_copied_from_external_sources() -> None:
    """원본이 로컬에 있을 때만 돈다(`01_ENGLISH_CONTENT.md`의 `금지`).

    전수 대조는 원본이 저장소에 없으므로 불가능하다. 할 수 있는 것은 예문 열을 가진 두
    자료(PHRASE List, PHaVE List)와의 대조다 --- NGSL·SUBTLEX는 예문이 없다.
    """
    missing = [path.name for path in (PHRASE_LIST_TSV, PHAVE_LIST_TXT) if not path.is_file()]
    if missing:
        pytest.skip(
            f"{LOCAL_WORDLISTS}에 {missing}가 없다. 원본은 gitignore라서(불변식 27) CI와 "
            "다른 머신에는 없는 것이 정상이고, 부재를 실패로 만들면 그 환경에서 늘 깨진다."
        )

    external = external_examples()
    assert len(external) > 100, f"외부 예문을 {len(external)}개만 읽었다. 파싱이 깨졌다"
    ours = seed_en_english_texts()
    assert ours, "seed/en/sentences.yaml에서 영어 문장을 하나도 읽지 못했다"

    offenders = copied_examples(ours, external)
    assert offenders == [], (
        f"외부 자료의 예문을 그대로 쓴 문장이 {len(offenders)}개 있다 "
        f"(`01_ENGLISH_CONTENT.md`의 `금지`, 합격 기준 29): {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. 영어 seed의 구조적 위생 --- 다른 테스트가 보지 않는 것만
# ---------------------------------------------------------------------------

# `01_ENGLISH_CONTENT.md`의 `topic_tags 고정 집합`. 그 문서는 "고정 집합 강제는 seed
# loader가 한다"고 적지만 `app/services/seed_loader.py`의 `_tags`는 "비어 있지 않은
# 문자열의 리스트"까지만 본다 --- 그래서 지금 이 집합을 보는 것은 이 검사뿐이다.
TOPIC_TAGS = frozenset(
    {
        "phrasal-verb",
        "idiom",
        "discourse-marker",
        "formulaic",
        "contraction",
        "colloquial",
        "slang",
        "daily",
        "friends",
        "work",
        "travel",
        "food",
        "shopping",
        "health",
        "phone",
        "smalltalk",
    }
)

# `01_ENGLISH_CONTENT.md`의 `type 배정`. loader는 `LearningItemType` enum으로만 검사하므로
# enum이 넓어지면 loader는 통과시킨다 --- 그래서 문서의 세 값으로 따로 본다
# (`금지` 목록의 `item type enum 확장`).
ITEM_TYPES = frozenset({"word", "grammar", "expression"})


def seed_en_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = yaml.safe_load(SEED_EN_ITEMS.read_text("utf-8"))
    return items


def tag_and_type_violations(items: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    for item in items:
        if item.get("type") not in ITEM_TYPES:
            violations.append(f"{item.get('seed_id')}: type={item.get('type')!r}")
        for tag in item.get("topic_tags") or []:
            if tag not in TOPIC_TAGS:
                violations.append(f"{item.get('seed_id')}: topic_tag={tag!r}")
    return violations


def test_the_tag_and_type_rule_recognizes_what_it_is_meant_to_block() -> None:
    """양성 대조군."""
    good = [{"seed_id": "en_it_0001", "type": "expression", "topic_tags": ["idiom", "daily"]}]
    assert tag_and_type_violations(good) == []

    bad = [
        {"seed_id": "en_it_0002", "type": "phrase", "topic_tags": ["daily"]},
        {"seed_id": "en_it_0003", "type": "word", "topic_tags": ["grammar"]},
    ]
    assert len(tag_and_type_violations(bad)) == 2


def test_seed_en_items_use_only_the_fixed_tags_and_three_types() -> None:
    violations = tag_and_type_violations(seed_en_items())
    assert violations == [], f"고정 집합 밖의 topic_tag / type: {violations}"


def test_the_fixed_tag_set_still_matches_the_spec_document() -> None:
    """위 상수가 명세와 갈라지는 것을 막는다. 역방향(명세에 있는데 상수에 없는 태그)은
    markdown 표를 파싱해야 해서 보지 않는다 --- 집합을 넓히는 커밋이 이 상수를 고치지
    않으면 `seed/en`이 그 태그를 쓰는 순간 위 검사가 실패한다."""
    spec_text = CONTENT_SPEC.read_text("utf-8")
    absent = sorted(tag for tag in TOPIC_TAGS if tag not in spec_text)
    assert absent == [], f"명세에 없는 태그가 상수에 있다: {absent}"
    assert all(value in spec_text for value in ITEM_TYPES)
