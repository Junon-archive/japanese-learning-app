/**
 * 설명 패널. **데이터 + 콜백만 받는 순수 렌더러다** --- `api.ts`도 `endpoints.ts`도
 * import하지 않는다. 호출이 어디서 일어나는지는 `ui/interactions.ts`가 안다.
 *
 * 내용은 서버가 준 precomputed 설명 그대로다(05_API_SPEC.md의 `Interaction`). 문구를
 * 조립하거나 요약하지 않는다.
 *
 * -   **reading은 여기에만 있다.** 문장에는 furigana를 상시 표시하지 않는다
 *     (03_UI_UX_SPEC.md의 `Translation/Furigana`).
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

export type ExplanationPanelOptions = {
  explanation: Explanation
  /** 이 화면에서 기록한 값. non-null이면 버튼을 잠근다. */
  reported: ExplicitSignal | null
  /** 서버가 이미 이 노출의 evidence를 갖고 있다(409). 재시도할 것이 없다. */
  alreadyRecorded: boolean
  /** 그 패널에 남길 실패 문구. 실패를 성공처럼 보이게 하지 않는다. */
  failure: string | null
  onSelfReport: (value: ExplicitSignal) => void
  onClose: () => void
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
  word.textContent = explanation.canonical_form

  const reading = document.createElement('div')
  reading.className = 'reading'
  reading.lang = 'ja'
  reading.textContent = explanation.reading

  const tag = document.createElement('span')
  tag.className = 'tag'
  // 서버 enum 값 그대로다. 모르는 값이 와도 화면에서 사라지지 않는다.
  tag.textContent = explanation.item_type

  const words = document.createElement('div')
  words.append(word, reading)
  head.append(words, tag)
  panel.append(head)

  panel.append(line('meaning', explanation.core_meaning))
  panel.append(line('meaning-context', explanation.meaning_in_context))
  panel.append(line('nuance', explanation.nuance))
  panel.append(line('example', explanation.example_sentence, 'ja'))
  if (explanation.example_translation !== null) {
    panel.append(line('example-translation', explanation.example_translation))
  }

  const feedback = document.createElement('div')
  feedback.className = 'feedback'
  if (options.reported !== null) {
    const label = SELF_REPORT_CHOICES.find((choice) => choice.value === options.reported)?.label
    feedback.append(line('feedback-done', `기록했습니다: ${label ?? options.reported}`))
  } else if (options.alreadyRecorded) {
    // 어떤 재시도도 성공하지 못한다(ADR-018). 버튼을 다시 주지 않는다.
    feedback.append(line('feedback-done', '이 문장에서는 이미 기록했습니다.'))
  } else {
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

  const close = document.createElement('button')
  close.type = 'button'
  close.className = 'explain-close'
  close.textContent = '설명 닫기'
  close.addEventListener('click', options.onClose)
  panel.append(close)

  return panel
}
