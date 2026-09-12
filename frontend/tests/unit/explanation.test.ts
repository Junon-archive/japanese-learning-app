/**
 * 설명 패널.
 *
 * 단정하는 것은 셋이다.
 *
 * 1.  서버가 준 **precomputed 필드를 하나도 빠뜨리지 않는다.** reading은 여기에만
 *     있으므로(문장에 furigana를 상시 표시하지 않는다) 빠지면 화면에서 영구히 사라진다.
 * 2.  self-report는 3값이고 `skip`이 없다.
 * 3.  기록된 뒤에는 **버튼이 없다.** 같은 노출에 두 번째 evidence를 만들 자리를 남기지
 *     않는다(ADR-018).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SELF_REPORT_CHOICES, renderExplanationPanel } from '../../src/ui/explanation'
import type { ExplicitSignal, Explanation } from '../../src/types'
import type { FakeElement } from './fake-dom'
import { buttons, fakeDocument, flatText } from './fake-dom'

/** 05_API_SPEC.md의 explanation 예시 그대로. */
const EXPLANATION: Explanation = {
  sentence_item_id: 5512,
  learning_item_id: 772,
  canonical_form: '気が乗らない',
  reading: 'き が のらない',
  item_type: 'expression',
  core_meaning: '내키지 않다 / 할 마음이 나지 않다',
  meaning_in_context: '연구실에 갈 생각이었지만 마음이 내키지 않았다',
  nuance: '해야 할 이유는 있어도 의욕이 따라주지 않을 때 쓰는 일상 표현',
  example_sentence: '今日はあまり出かける気が乗らない。',
  example_translation: '오늘은 별로 나가고 싶지 않다.',
}

type Overrides = {
  reported?: ExplicitSignal | null
  alreadyRecorded?: boolean
  failure?: string | null
  onSelfReport?: (value: ExplicitSignal) => void
}

function render(overrides: Overrides = {}): FakeElement {
  return renderExplanationPanel({
    explanation: EXPLANATION,
    reported: overrides.reported ?? null,
    alreadyRecorded: overrides.alreadyRecorded ?? false,
    failure: overrides.failure ?? null,
    onSelfReport: overrides.onSelfReport ?? (() => {}),
    onClose: () => {},
  }) as unknown as FakeElement
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderExplanationPanel', () => {
  it('shows every precomputed field the server sent', () => {
    const text = flatText(render())

    for (const value of [
      EXPLANATION.canonical_form,
      EXPLANATION.reading,
      EXPLANATION.item_type,
      EXPLANATION.core_meaning,
      EXPLANATION.meaning_in_context,
      EXPLANATION.nuance,
      EXPLANATION.example_sentence,
      EXPLANATION.example_translation,
    ]) {
      expect(text).toContain(String(value))
    }
  })

  it('omits the example translation when the server has none', () => {
    const panel = renderExplanationPanel({
      explanation: { ...EXPLANATION, example_translation: null },
      reported: null,
      alreadyRecorded: false,
      failure: null,
      onSelfReport: () => {},
      onClose: () => {},
    }) as unknown as FakeElement

    // 빈 노드를 만들지 않는다. 없는 것은 없는 것으로 둔다.
    expect(flatText(panel)).not.toContain(String(EXPLANATION.example_translation))
  })

  it('offers exactly the three self-report values, skip not among them', () => {
    const labels = buttons(render())
      .filter((button) => button.className === 'self-report')
      .map((button) => button.textContent)

    expect(labels).toEqual(SELF_REPORT_CHOICES.map((choice) => choice.label))
    expect(labels).toHaveLength(3)
    expect(labels).not.toContain('건너뛰기')
  })

  it('passes the chosen value back', () => {
    const chosen: ExplicitSignal[] = []
    const panel = render({ onSelfReport: (value) => chosen.push(value) })

    for (const button of buttons(panel).filter((b) => b.className === 'self-report')) button.click()

    expect(chosen).toEqual(SELF_REPORT_CHOICES.map((choice) => choice.value))
  })

  it('locks the buttons away once a value is recorded', () => {
    const panel = render({ reported: 'uncertain' })

    expect(buttons(panel).filter((b) => b.className === 'self-report')).toEqual([])
    expect(flatText(panel)).toContain('애매함')
  })

  it('locks the buttons away when the server already has evidence', () => {
    const panel = render({ alreadyRecorded: true })

    expect(buttons(panel).filter((b) => b.className === 'self-report')).toEqual([])
    expect(flatText(panel)).toContain('이미 기록했습니다')
  })

  it('shows a failure without pretending the report was saved', () => {
    const panel = render({ failure: '저장하지 못했습니다. 다시 시도해 주세요.' })

    expect(flatText(panel)).toContain('저장하지 못했습니다')
    // 실패했으므로 버튼은 그대로 있다 --- 잠그면 사용자가 다시 시도할 수 없다.
    expect(buttons(panel).filter((b) => b.className === 'self-report')).toHaveLength(3)
  })

  it('has no audio control', () => {
    // MVP에 audio가 없다(00_SCOPE.md). 듣기 버튼을 만들지 않는다.
    expect(flatText(render())).not.toMatch(/듣기|🔊/)
  })
})
