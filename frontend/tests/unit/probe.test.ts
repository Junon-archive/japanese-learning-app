/**
 * Mastery probe UI.
 *
 * 가장 중요한 두 가지는 **payload가 문구와 순서를 정한다**와 **모르는 값을 버리지
 * 않는다**다.
 *
 * -   fixture의 `options` 순서를 서버 선언 순서와 **다르게** 섞어 두었다. 라벨 매핑을
 *     상수 배열로 바꿔 payload를 무시하면 이 테스트가 빨개진다. 순서가 같은 fixture만
 *     쓰면 그 회귀가 통과한다.
 *     -   `prompt`도 같다. 문구를 프론트 상수로 복사하면 fixture의 문구가 화면에 없다.
 * -   fixture에 서버가 나중에 추가할 수 있는 **모르는 값**이 하나 들어 있다. 조용히
 *     버리면 그 버튼이 화면에서 사라지고 아무도 모른다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PROBE_LABELS, renderProbe } from '../../src/ui/probe'
import type { Probe, ProbeResponseValue } from '../../src/types'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, fakeDocument, flatText } from './fake-dom'

/** 서버 선언 순서는 `known, uncertain, unknown, skip`이다. 여기서는 섞여 있다. */
const SHUFFLED_OPTIONS: ProbeResponseValue[] = ['skip', 'unknown', 'known', 'uncertain']

const PROBE: Probe = {
  probe_id: 318,
  learning_item_id: 773,
  prompt: '이 표현을 알고 계세요?',
  expression: '気が乗らない',
  options: SHUFFLED_OPTIONS,
}

function render(
  probe: Probe,
  answered: string | null = null,
  alreadyRecorded = false,
): FakeElement {
  return renderProbe({
    probe,
    answered,
    alreadyRecorded,
    failure: null,
    onRespond: () => {},
  }) as unknown as FakeElement
}

function optionLabels(node: FakeElement): string[] {
  return buttons(node)
    .filter((button) => button.className === 'probe-option')
    .map((button) => button.textContent)
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderProbe', () => {
  it('shows the prompt the server sent, not a copy of it', () => {
    const surprising = { ...PROBE, prompt: '이 표현이 익숙하세요?' }

    expect(flatText(render(surprising))).toContain(surprising.prompt)
    expect(flatText(render(surprising))).not.toContain(PROBE.prompt)
  })

  it('renders the option buttons in the payload order', () => {
    expect(optionLabels(render(PROBE))).toEqual(
      SHUFFLED_OPTIONS.map((value) => PROBE_LABELS[value]),
    )
  })

  it('always offers skip', () => {
    expect(optionLabels(render(PROBE))).toContain('건너뛰기')
  })

  it('shows an unknown option value verbatim instead of dropping it', () => {
    // 서버가 값을 하나 추가한 상황. 버리면 버튼이 사라지고 아무도 모른다.
    const extended = {
      ...PROBE,
      options: [...SHUFFLED_OPTIONS, 'partially_known' as ProbeResponseValue],
    }

    const labels = optionLabels(render(extended))
    expect(labels).toHaveLength(extended.options.length)
    expect(labels.at(-1)).toBe('partially_known')
  })

  it('sends the payload value back, not the label', () => {
    const sent: string[] = []
    const node = renderProbe({
      probe: PROBE,
      answered: null,
      alreadyRecorded: false,
      failure: null,
      onRespond: (value) => sent.push(value),
    }) as unknown as FakeElement

    for (const button of buttons(node).filter((b) => b.className === 'probe-option')) button.click()

    expect(sent).toEqual(SHUFFLED_OPTIONS)
  })

  it('locks the options once answered', () => {
    const node = render(PROBE, 'unknown')

    expect(optionLabels(node)).toEqual([])
    expect(flatText(node)).toContain('몰랐음')
  })

  it('claims no value when the evidence came from somewhere else', () => {
    // 409는 "이 노출에 이미 evidence가 있다"일 뿐이고 무엇으로 기록됐는지는 모른다
    // --- 같은 item의 self-report일 수 있다(ADR-018). 값을 지어내지 않는다.
    const node = render(PROBE, null, true)

    expect(optionLabels(node)).toEqual([])
    expect(flatText(node)).toContain('이미 기록했어요.')
    expect(flatText(node)).not.toContain('알고 있었음')
  })

  it('does not call a skip an answer', () => {
    // skip은 evidence가 아니다. "기록했어요"로 적으면 거짓이다.
    const node = render(PROBE, 'skip')

    expect(flatText(node)).toContain('건너뛰었어요.')
    expect(flatText(node)).not.toContain('기록했어요')
  })
})

describe('probe wording', () => {
  it('has a small eyebrow and the fixed labels', () => {
    const node = render(PROBE, null)

    expect(byClass(node, 'probe-eyebrow')[0]!.textContent).toBe('잠깐 확인해요')
    expect(node.getAttribute('aria-label')).toBe('이해도 확인')
  })

  it('says what was recorded with the chosen label', () => {
    expect(flatText(render(PROBE, 'unknown'))).toContain('기록했어요 · 몰랐음')
  })
})
