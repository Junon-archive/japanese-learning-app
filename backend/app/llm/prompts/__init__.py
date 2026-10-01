"""Task별 정적 지시문과 그 버전 (`06_LLM_ENGINEERING_PRINCIPLES.md` 6번).

`prompt_versions` 행이 `(task_type, language, version, provider, model)`을 정하고
여기에는 **본문과 version 문자열만** 있다. 두 곳이 갈리면 안 되므로 조회는 항상
`template_for(task_type, language, version)`을 거친다 --- DB의 `active` 행이
가리키는 `(language, version)`에 해당하는 본문이 코드에 없으면 그 job은 재시도해도
결과가 같다.

registry라고 불렀지만 plugin 등록 지점이 아니다. dict 하나이며 값은 이 패키지
안의 상수뿐이다. 동적 등록도, provider별 분기도 없다.

prompt 본문은 언어별 디렉터리에 있다(`backend/app/llm/prompts/<language>/`,
ADR-023 결정 5). 두 언어가 같은 task_type 이름을 쓰지만 본문과 version 문자열은
서로 다르다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.prompts.en import explain_item as en_explain_item
from app.llm.prompts.en import review_context as en_review_context
from app.llm.prompts.en import sentence_gen as en_sentence_gen
from app.llm.prompts.ja import explain_item, review_context, sentence_gen
from app.llm.provider import LlmError
from app.models.enums import Language, LlmTaskType


class UnknownPromptVersionError(LlmError):
    """`prompt_versions.active`가 가리키는 `(language, version)`의 본문이 코드에 없다.

    재시도해도 결과가 같으므로 job queue는 이것을 `dead_letter`로 다룬다.
    """


@dataclass(frozen=True)
class PromptTemplate:
    task_type: LlmTaskType
    language: Language
    version: str
    instructions: str


_TEMPLATES = (
    PromptTemplate(
        task_type=LlmTaskType.GENERATE_SENTENCE_BATCH,
        language=Language.JA,
        version=sentence_gen.VERSION,
        instructions=sentence_gen.INSTRUCTIONS,
    ),
    PromptTemplate(
        task_type=LlmTaskType.GENERATE_REVIEW_CONTEXT,
        language=Language.JA,
        version=review_context.VERSION,
        instructions=review_context.INSTRUCTIONS,
    ),
    PromptTemplate(
        task_type=LlmTaskType.EXPLAIN_ITEM,
        language=Language.JA,
        version=explain_item.VERSION,
        instructions=explain_item.INSTRUCTIONS,
    ),
    PromptTemplate(
        task_type=LlmTaskType.GENERATE_SENTENCE_BATCH,
        language=Language.EN,
        version=en_sentence_gen.VERSION,
        instructions=en_sentence_gen.INSTRUCTIONS,
    ),
    PromptTemplate(
        task_type=LlmTaskType.GENERATE_REVIEW_CONTEXT,
        language=Language.EN,
        version=en_review_context.VERSION,
        instructions=en_review_context.INSTRUCTIONS,
    ),
    PromptTemplate(
        task_type=LlmTaskType.EXPLAIN_ITEM,
        language=Language.EN,
        version=en_explain_item.VERSION,
        instructions=en_explain_item.INSTRUCTIONS,
    ),
)

PROMPT_TEMPLATES: dict[tuple[LlmTaskType, Language, str], PromptTemplate] = {
    (template.task_type, template.language, template.version): template for template in _TEMPLATES
}


def template_for(task_type: LlmTaskType, language: Language, version: str) -> PromptTemplate:
    template = PROMPT_TEMPLATES.get((task_type, language, version))
    if template is None:
        raise UnknownPromptVersionError(
            f"no prompt template for task_type={task_type.value!r} "
            f"language={language.value!r} version={version!r}"
        )
    return template
