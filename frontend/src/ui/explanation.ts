/**
 * 설명 시트의 내용. **데이터 + 콜백만 받는 순수 렌더러다** --- `api.ts`도 `endpoints.ts`도
 * import하지 않는다. 호출이 어디서 일어나는지, 시트를 여닫는 것은 `ui/interactions.ts`가 안다.
 *
 * 내용은 서버가 준 precomputed 설명 그대로다(05_API_SPEC.md의 `Interaction`). 문구를
 * 조립하거나 요약하지 않는다.
 *
 * -   **머리는 문장 속 표면형과 그 읽기의 짝이다**(예: `任せ` / `まかせ`). `reading`은 표면형의
 *     읽기이고(05_API_SPEC.md) 그대로 쓴다. 기본형(`canonical_form`)은 따로 적으며 **그 읽기를 화면이
 *     만들지 않는다**(03_UI_UX_SPEC.md의 `Explanation`).
 * -   유형 태그는 표시용 매핑이다. 모르는 값은 원문 그대로 둔다.
 * -   하단 self-report는 **선택이다.** 누르지 않아도 다음 문장으로 갈 수 있으므로 이
 *     패널에 "먼저 고르세요" 같은 요구를 적지 않는다.
 * -   MVP에 audio가 없다. 듣기 버튼을 두지 않는다(00_SCOPE.md).
 */

import type { ExplicitSignal, Explanation } from '../types'

/**
 * self-report 3값의 라벨과 **표시 순서**. 서버는 self-report에 options를 주지 않으므로
 * 이 순서는 화면 결정이다(probe의 options와 다르다 --- 그쪽은 payload가 정한다).
 *
 * `skip`이 없다. self-report는 건너뛸 값이 아니라 **하지 않는 것**이다.
 */
export const SELF_REPORT_CHOICES: readonly { value: ExplicitSignal; label: string }[] = [
  { value: 'known', label: '알고 있었음' },
  { value: 'uncertain', label: '애매함' },
  { value: 'unknown', label: '몰랐음' },
]

/** 유형 태그 라벨. **표시용이며 필터가 아니다.** 모르는 값은 원문 그대로다. */
const ITEM_TYPE_LABELS: Readonly<Record<string, string | undefined>> = {
  word: '단어',
  grammar: '문법',
  expression: '표현',
}

export function itemTypeLabel(itemType: string): string {
  return ITEM_TYPE_LABELS[itemType] ?? itemType
}

export type ExplanationPanelOptions = {
  explanation: Explanation
  /** 이 item의 문장 속 표면형. 해당 `sentence_item_id` segment의 text를 이은 것이다. */
  surface: string
  /** 이 화면에서 기록한 값. non-null이면 버튼을 잠근다. */
  reported: ExplicitSignal | null
  /** 서버가 이미 이 노출의 evidence를 갖고 있다(409). 재시도할 것이 없다. */
  alreadyRecorded: boolean
  /** 그 패널에 남길 실패 문구. 실패를 성공처럼 보이게 하지 않는다. */
  failure: string | null
  onSelfReport: (value: ExplicitSignal) => void
}

/** 설명 칸 이름(03_UI_UX_SPEC.md의 화면 문구 표). 값은 서버 값이다. */
const FIELD_LABELS = {
  meaning: '뜻',
  context: '이 문장에서',
  nuance: '느낌',
  example: '예문',
} as const

const SELF_REPORT_QUESTION = '이 표현, 알고 있었나요?'
/** self-report는 진행을 막지 않는다. */
const SELF_REPORT_OPTIONAL = '고르지 않아도 괜찮아요.'

/** 칸 하나: 이름과 값들. */
function block(label: string, values: HTMLElement[]): HTMLElement {
  const box = document.createElement('div')
  box.className = 'explain-block'
  const name = document.createElement('h3')
  name.className = 'explain-label'
  name.textContent = label
  box.append(name, ...values)
  return box
}

function line(className: string, text: string, lang?: string): HTMLElement {
  const node = document.createElement('p')
  node.className = className
  node.textContent = text
  if (lang !== undefined) node.lang = lang
  return node
}

export function renderExplanationPanel(options: ExplanationPanelOptions): HTMLElement {
  const { explanation } = options

  const panel = document.createElement('section')
  panel.className = 'explain'
  panel.setAttribute('aria-label', '표현 설명')

  const head = document.createElement('div')
  head.className = 'item-head'

  const word = document.createElement('div')
  word.className = 'jp-word'
  word.lang = 'ja'
  word.textContent = options.surface

  const reading = document.createElement('div')
  reading.className = 'reading'
  reading.lang = 'ja'
  reading.textContent = explanation.reading

  const canonical = document.createElement('div')
  canonical.className = 'canonical-form'
  canonical.lang = 'ja'
  canonical.textContent = explanation.canonical_form

  const tag = document.createElement('span')
  tag.className = 'tag'
  tag.textContent = itemTypeLabel(explanation.item_type)

  const words = document.createElement('div')
  words.append(word, reading, canonical)
  head.append(words, tag)
  panel.append(head)

  panel.append(block(FIELD_LABELS.meaning, [line('meaning', explanation.core_meaning)]))
  panel.append(block(FIELD_LABELS.context, [line('meaning-context', explanation.meaning_in_context)]))
  panel.append(block(FIELD_LABELS.nuance, [line('nuance', explanation.nuance)]))
  panel.append(
    block(FIELD_LABELS.example, [
      line('example', explanation.example_sentence, 'ja'),
      ...(explanation.example_translation === null
        ? []
        : [line('example-translation', explanation.example_translation)]),
    ]),
  )

  const feedback = document.createElement('div')
  feedback.className = 'feedback'
  feedback.append(line('feedback-question', SELF_REPORT_QUESTION))
  if (options.reported !== null) {
    const label = SELF_REPORT_CHOICES.find((choice) => choice.value === options.reported)?.label
    feedback.append(line('feedback-done', `기록했어요 · ${label ?? options.reported}`))
  } else if (options.alreadyRecorded) {
    // 어떤 재시도도 성공하지 못한다(ADR-018). 버튼을 다시 주지 않는다.
    feedback.append(line('feedback-done', '이 문장에서는 이미 기록했어요.'))
  } else {
    feedback.append(line('feedback-optional', SELF_REPORT_OPTIONAL))
    for (const choice of SELF_REPORT_CHOICES) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'self-report'
      button.textContent = choice.label
      button.addEventListener('click', () => {
        options.onSelfReport(choice.value)
      })
      feedback.append(button)
    }
  }
  panel.append(feedback)

  if (options.failure !== null) {
    const failure = line('panel-failure', options.failure)
    failure.setAttribute('role', 'alert')
    panel.append(failure)
  }

  return panel
}
