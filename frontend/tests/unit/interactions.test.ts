/**
 * 상호작용 네 가지의 **흐름**. 어떤 호출이 어떤 순서로 나가는지가 여기서 고정된다.
 *
 * 화면에서는 전부 정상으로 보이기 때문에 코드로 막는 것들:
 *
 * -   번역은 reveal **응답을 받은 뒤에** 노드가 생긴다. 미리 만들어 두고 감추는 구조로
 *     바꾸면 `renders no translation node before the reveal`이 빨개진다. 그 구조에서는
 *     번역 문자열이 이미 DOM에 있으므로 `translation_revealed` event가 "사용자가 번역을
 *     봤다"를 뜻하지 못한다.
 * -   `explanation-revealed`는 설명이 **시트에 삽입된 직후에** 나가고(`transitionend`를 기다리지 않는다),
 *     `click`이 실패했거나 응답 전에 화면을 떠난(`signal` abort) 경로에서는 **나가지 않는다.** 하나로
 *     합치거나 tap과 동시에 보내면 "탭했지만 표시되지 않은 경우"가 관측되지 않는다(05_API_SPEC.md).
 * -   시트를 닫고 다시 여는 것은 event가 아니다. `/click`도 `explanation-revealed`도 presentation +
 *     item당 1회다. UI 조작 횟수가 raw history에 쌓이면 안 된다.
 * -   번역은 시트가 아니라 상호작용 영역 안의 인라인 노드다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createInteractions } from '../../src/ui/interactions'
import type { InteractionFailure, InteractionOps } from '../../src/ui/interactions'
import type { Explanation, Presentation } from '../../src/types'
import type { FakeDocument, FakeElement } from './fake-dom'
import { byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const KOREAN = '연구실에 갈 생각이었지만 왠지 마음이 내키지 않아 집에 있었다.'

const EXPLANATION: Explanation = {
  sentence_item_id: 5512,
  learning_item_id: 772,
  canonical_form: '気が乗らない',
  reading: 'き が のらない',
  item_type: 'expression',
  core_meaning: '내키지 않다 / 할 마음이 나지 않다',
  meaning_in_context: '연구실에 갈 생각이었지만 마음이 내키지 않았다',
  nuance: '의욕이 따라주지 않을 때 쓰는 일상 표현',
  example_sentence: '今日はあまり出かける気が乗らない。',
  example_translation: '오늘은 별로 나가고 싶지 않다.',
}

/** `korean_translation`이 **없다.** 서버 payload에 그 필드가 없기 때문이다. */
const PRESENTATION: Presentation = {
  presentation_id: 4821,
  sentence_id: 1907,
  japanese: '今日は研究室に行くつもりだったけど、なんとなく気が乗らなくて家にいた。',
  render_segments: [
    { text: '今日は', sentence_item_id: null },
    { text: 'なんとなく', sentence_item_id: 5511 },
    { text: '気が乗らなくて', sentence_item_id: 5512 },
    { text: '家にいた。', sentence_item_id: null },
  ],
  presentation_role: 'review',
  review_reason: 'fsrs_due',
  context_stage: 'near_original',
  translation_revealed: false,
  tappable_items: [
    { sentence_item_id: 5511, learning_item_id: 771 },
    { sentence_item_id: 5512, learning_item_id: 772 },
  ],
  probe: {
    probe_id: 318,
    learning_item_id: 773,
    prompt: '이 표현을 알고 계세요?',
    expression: '気が乗らない',
    options: ['known', 'uncertain', 'unknown', 'skip'],
  },
}

/** microtask + timer 큐를 비운다. 상호작용은 전부 `void perform(...)`으로 돈다. */
function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

type Failures = Partial<Record<keyof InteractionOps, unknown>>

function setup(
  failures: Failures = {},
  failure: InteractionFailure = { kind: 'message', text: '저장하지 못했습니다.' },
  clickItem?: (sentenceItemId: number) => Promise<Explanation>,
) {
  const calls: string[] = []
  /** 렌더 상태를 호출 시점에 기록한다. "렌더된 뒤에 보냈는가"를 단정하려면 필요하다. */
  const seenAtCall: Record<string, string> = {}
  /** 호출부(실제 화면에서는 세션 재획득/로그인 이동)가 불린 횟수. */
  const reported: unknown[] = []

  const reject = (name: keyof InteractionOps): boolean => name in failures

  const ops: InteractionOps = {
    clickItem: async (sentenceItemId) => {
      calls.push(`click:${sentenceItemId}`)
      if (reject('clickItem')) throw failures['clickItem']
      if (clickItem !== undefined) return clickItem(sentenceItemId)
      return { ...EXPLANATION, sentence_item_id: sentenceItemId }
    },
    markExplanationRevealed: async (sentenceItemId) => {
      calls.push(`revealed:${sentenceItemId}`)
      seenAtCall[`revealed:${sentenceItemId}`] = flatText(screen)
      if (reject('markExplanationRevealed')) throw failures['markExplanationRevealed']
    },
    revealTranslation: async () => {
      calls.push('translation')
      if (reject('revealTranslation')) throw failures['revealTranslation']
      return KOREAN
    },
    selfReport: async (sentenceItemId, value) => {
      calls.push(`self-report:${sentenceItemId}:${value}`)
      if (reject('selfReport')) throw failures['selfReport']
    },
    respondToProbe: async (probeId, value) => {
      calls.push(`probe:${probeId}:${value}`)
      if (reject('respondToProbe')) throw failures['respondToProbe']
      return value
    },
    flagContent: async (reason, note) => {
      calls.push(`flag:${reason}:${note ?? '-'}`)
      if (reject('flagContent')) throw failures['flagContent']
    },
    reportFailure: (error: unknown) => {
      reported.push(error)
      return failure
    },
  }

  /** 실제 화면처럼 상호작용 영역을 담은 화면 요소. 설명 시트가 여기에 붙는다. */
  const screen = createFakeElement('main')
  const controller = new AbortController()
  const handle = createInteractions(PRESENTATION, ops, {
    signal: controller.signal,
    sheetContainer: screen as unknown as HTMLElement,
  })
  const box = handle.element as unknown as FakeElement
  screen.append(box)
  return {
    handle,
    /** 화면 전체(상호작용 영역 + 시트). */
    element: screen,
    box,
    controller,
    calls,
    seenAtCall,
    reported,
    text: () => flatText(screen),
  }
}

function closeSheet(screen: FakeElement): void {
  byClass(screen, 'sheet-close')[0]!.click()
}

let doc: FakeDocument

beforeEach(() => {
  doc = fakeDocument()
  vi.stubGlobal('document', doc)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('translation reveal', () => {
  it('renders no translation node before the reveal', () => {
    const { element, calls, text } = setup()

    // 노드도 없고 문자열도 없다. 숨겨 둔 노드를 토글하는 구조면 앞의 단정이 깨진다.
    expect(byClass(element, 'translation')).toEqual([])
    expect(text()).not.toContain(KOREAN)
    // 화면을 그리는 것만으로 event가 나가지 않는다.
    expect(calls).toEqual([])
  })

  it('creates the node from the reveal response', async () => {
    const { element, calls, text } = setup()

    byClass(element, 'reveal-translation')[0]?.click()
    await flush()

    expect(calls).toEqual(['translation'])
    expect(byClass(element, 'translation')).toHaveLength(1)
    expect(text()).toContain(KOREAN)
  })

  it('shows the translation inline in the interaction area, not in a sheet', async () => {
    const { element, box } = setup()

    byClass(element, 'reveal-translation')[0]?.click()
    await flush()

    expect(byClass(element, 'sheet')).toEqual([])
    expect(byClass(box, 'translation')).toHaveLength(1)
    expect(byClass(box, 'translation')[0]!.classList.contains('inline-expand')).toBe(true)
  })

  it('says it failed instead of showing an empty translation', async () => {
    const { element, text } = setup({ revealTranslation: new Error('boom') })

    byClass(element, 'reveal-translation')[0]?.click()
    await flush()

    expect(byClass(element, 'translation')).toEqual([])
    expect(text()).toContain('문장 뜻을 표시하지 못했습니다')
    // 버튼이 남아 있어 사용자가 다시 누를 수 있다. 무한 spinner를 만들지 않는다.
    expect(byClass(element, 'reveal-translation')).toHaveLength(1)
  })

  it('does not reveal twice', async () => {
    const { element, calls } = setup()

    byClass(element, 'reveal-translation')[0]?.click()
    byClass(element, 'reveal-translation')[0]?.click()
    await flush()

    expect(calls).toEqual(['translation'])
  })
})

describe('item tap', () => {
  it('sends explanation-revealed right after the explanation is in the sheet, without transitionend', async () => {
    const { handle, element, calls, seenAtCall } = setup()

    handle.tapItem(5512)
    await flush()

    expect(calls).toEqual(['click:5512', 'revealed:5512'])
    // 그 시점의 화면(시트 안)에 설명이 이미 있었다 --- "표시된 뒤에 보낸다"가 참이다. 이 스텁에서는
    // transitionend가 오지 않는다.
    expect(seenAtCall['revealed:5512']).toContain(EXPLANATION.core_meaning)
    const sheet = byClass(element, 'sheet')
    expect(sheet).toHaveLength(1)
    expect(sheet[0]!.getAttribute('role')).toBe('dialog')
    expect(flatText(sheet[0]!)).toContain(EXPLANATION.core_meaning)
  })

  it('draws nothing and sends no explanation-revealed when the screen was left before the response', async () => {
    let answer: (explanation: Explanation) => void = () => {}
    const { handle, element, controller, calls, text } = setup({}, undefined, () =>
      new Promise<Explanation>((resolve) => {
        answer = resolve
      }),
    )

    handle.tapItem(5512)
    await flush()
    controller.abort()
    answer(EXPLANATION)
    await flush()

    // `item_clicked`만 남는다.
    expect(calls).toEqual(['click:5512'])
    expect(byClass(element, 'sheet')).toEqual([])
    expect(text()).not.toContain(EXPLANATION.core_meaning)
  })

  it('closes an open sheet when the signal is aborted', async () => {
    const { handle, element, controller } = setup()

    handle.tapItem(5512)
    await flush()
    controller.abort()

    expect(byClass(element, 'sheet-scrim')[0]!.classList.contains('is-closing')).toBe(true)
  })

  it('sends no explanation-revealed when the click fails', async () => {
    const { handle, calls, text } = setup({ clickItem: new Error('500') })

    handle.tapItem(5512)
    await flush()

    // `item_clicked`만 남는다. 그 구간을 관측할 수 있어야 한다(05_API_SPEC.md).
    expect(calls).toEqual(['click:5512'])
    expect(text()).toContain('저장하지 못했습니다')
    expect(text()).not.toContain(EXPLANATION.core_meaning)
  })

  it('keeps the explanation when the auxiliary event fails', async () => {
    // `explanation_revealed`는 auxiliary signal이다 --- 보내지 않아도 학습 진행을 막지
    // 않는다(05_API_SPEC.md). click과 한 task에 두면 이 실패가 click의 실패 처리를 타고,
    // 게이트 409일 때 세션 재획득이 시작되어 **정상 렌더된 문장이 치워진다.**
    const { handle, calls, text, reported } = setup(
      { markExplanationRevealed: new Error('409') },
      { kind: 'handled' },
    )

    handle.tapItem(5512)
    await flush()

    expect(calls).toEqual(['click:5512', 'revealed:5512'])
    // (a) 설명이 그대로 있다.
    expect(text()).toContain(EXPLANATION.core_meaning)
    // (b) 실패 문구가 없다. 사용자가 할 일이 없는 실패다.
    expect(text()).not.toContain('저장하지 못했습니다')
    // (c) 호출부의 복구(세션 재획득/로그인 이동)를 부르지 않았다.
    expect(reported).toEqual([])
  })

  it('does not retry an explanation_revealed that failed', async () => {
    // presentation당 1회를 **시도 기준**으로 센다(보수적 선택). 닫았다 다시 열어도 보내지
    // 않는다 --- 실패한 event는 영구 부재이고 auxiliary라 학습을 막지 않는다.
    const { handle, element, calls } = setup({ markExplanationRevealed: new Error('409') })

    handle.tapItem(5512)
    await flush()
    closeSheet(element)
    handle.tapItem(5512)
    closeSheet(element)
    handle.tapItem(5512)
    await flush()

    expect(calls).toEqual(['click:5512', 'revealed:5512'])
  })

  it('closes the sheet and reopens it from the cache without sending anything', async () => {
    const { handle, element, calls } = setup()

    handle.tapItem(5512)
    await flush()
    const first = byClass(element, 'explain')[0]
    closeSheet(element)
    expect(byClass(element, 'sheet-scrim').every((scrim) => scrim.classList.contains('is-closing'))).toBe(true)

    handle.tapItem(5512) // 다시 탭
    await flush()

    const open = byClass(element, 'sheet-scrim').filter((scrim) => !scrim.classList.contains('is-closing'))
    expect(open).toHaveLength(1)
    expect(flatText(open[0]!)).toContain(EXPLANATION.core_meaning)
    // 내용은 다시 만든 것이다. 숨겨 둔 노드를 재사용하지 않는다.
    expect(byClass(open[0]!, 'explain')[0]).not.toBe(first)
    expect(calls).toEqual(['click:5512', 'revealed:5512'])
  })

  it('retries the first click when it failed, since that is not a reopen', async () => {
    const failures: Failures = { clickItem: new Error('503') }
    const { handle, element, calls } = setup(failures)

    handle.tapItem(5512)
    await flush()
    delete failures.clickItem
    handle.tapItem(5512)
    await flush()

    expect(calls).toEqual(['click:5512', 'click:5512', 'revealed:5512'])
    expect(byClass(element, 'sheet')).toHaveLength(1)
  })

  it('returns focus to the tapped expression when the sheet closes', async () => {
    const { handle, element } = setup()
    const token = createFakeElement('button')
    element.append(token)
    token.focus()

    handle.tapItem(5512)
    await flush()
    expect(doc.activeElement).not.toBe(token)
    closeSheet(element)

    expect(doc.activeElement).toBe(token)
  })

  it('treats a double tap as one click', async () => {
    const { handle, calls } = setup()

    handle.tapItem(5511)
    handle.tapItem(5511)
    await flush()

    expect(calls).toEqual(['click:5511', 'revealed:5511'])
  })

  it('keeps each item separate', async () => {
    const { handle, element, calls } = setup()

    handle.tapItem(5511)
    await flush()
    closeSheet(element)
    handle.tapItem(5512)
    await flush()

    expect(calls).toEqual(['click:5511', 'revealed:5511', 'click:5512', 'revealed:5512'])
  })
})

describe('self-report', () => {
  it('locks the buttons for that item once recorded', async () => {
    const { handle, element, calls, text } = setup()

    handle.tapItem(5512)
    await flush()
    byClass(element, 'self-report')[1]?.click()
    await flush()

    expect(calls).toEqual(['click:5512', 'revealed:5512', 'self-report:5512:uncertain'])
    expect(byClass(element, 'self-report')).toEqual([])
    expect(text()).toContain('기록했습니다')
  })

  it('survives a refresh that re-enables every button', async () => {
    const { handle, element } = setup()

    handle.tapItem(5512)
    await flush()
    byClass(element, 'self-report')[0]?.click()
    await flush()
    handle.refresh()

    expect(byClass(element, 'self-report')).toEqual([])
  })

  it('ends a 409 "already recorded" with a notice, not a retry', async () => {
    const { handle, element, calls, text } = setup(
      { selfReport: new Error('409') },
      { kind: 'alreadyRecorded' },
    )

    handle.tapItem(5512)
    await flush()
    byClass(element, 'self-report')[0]?.click()
    await flush()

    expect(calls).toEqual(['click:5512', 'revealed:5512', 'self-report:5512:known'])
    expect(text()).toContain('이미 기록했습니다')
    // 어떤 재시도도 성공하지 못한다(ADR-018). 버튼을 다시 주지 않는다.
    expect(byClass(element, 'self-report')).toEqual([])
  })

  it('leaves the buttons usable after a transient failure', async () => {
    const { handle, element, text } = setup({ selfReport: new Error('503') })

    handle.tapItem(5512)
    await flush()
    byClass(element, 'self-report')[0]?.click()
    await flush()

    expect(text()).toContain('저장하지 못했습니다')
    expect(byClass(element, 'self-report')).toHaveLength(3)
  })

  it('is optional: nothing about it blocks the rest of the screen', async () => {
    const { handle, element, calls } = setup()

    // 자가보고 없이 번역과 probe를 쓸 수 있다.
    handle.tapItem(5512)
    await flush()
    byClass(element, 'reveal-translation')[0]?.click()
    await flush()

    expect(calls).toContain('translation')
    expect(byClass(element, 'self-report')).toHaveLength(3)
  })
})

describe('probe', () => {
  it('records the value the server confirms and locks the area', async () => {
    const { element, calls, text } = setup()

    byClass(element, 'probe-option')[2]?.click()
    await flush()

    expect(calls).toEqual(['probe:318:unknown'])
    expect(byClass(element, 'probe-option')).toEqual([])
    expect(text()).toContain('몰랐음')
  })

  it('lets skip through immediately without blocking anything else', async () => {
    const { element, calls, text } = setup()

    byClass(element, 'probe-option')[3]?.click()
    await flush()

    expect(calls).toEqual(['probe:318:skip'])
    expect(text()).toContain('건너뛰었습니다')
    // 건너뛴 뒤에도 문장 상호작용은 그대로 열려 있다.
    expect(byClass(element, 'reveal-translation')).toHaveLength(1)
  })

  it('locks without claiming a value when the exposure already has evidence', async () => {
    const { element, calls, text } = setup(
      { respondToProbe: new Error('409') },
      { kind: 'alreadyRecorded' },
    )

    byClass(element, 'probe-option')[0]?.click()
    await flush()

    expect(calls).toEqual(['probe:318:known'])
    expect(byClass(element, 'probe-option')).toEqual([])
    expect(text()).toContain('이미 기록했습니다')
    expect(text()).not.toContain('기록했습니다: 알고 있었음')
  })

  it('answers once even on a double tap', async () => {
    const { element, calls } = setup()

    byClass(element, 'probe-option')[0]?.click()
    byClass(element, 'probe-option')[1]?.click()
    await flush()

    expect(calls).toEqual(['probe:318:known'])
  })

  it('is absent when the payload has no probe', () => {
    const handle = createInteractions({ ...PRESENTATION, probe: null }, quietOps(), {
      signal: new AbortController().signal,
      sheetContainer: createFakeElement('main') as unknown as HTMLElement,
    })
    const element = handle.element as unknown as FakeElement

    expect(byClass(element, 'probe')).toEqual([])
    expect(byClass(element, 'reveal-translation')).toHaveLength(1)
  })
})

describe('content flag', () => {
  it('files the current sentence with the note and says it is quarantined', async () => {
    const { element, calls, text } = setup()

    byClass(element, 'flag-open')[0]?.click()
    const note = byClass(element, 'flag-note')[0]!
    note.value = '앞뒤가 이어지지 않는다'
    note.fire('input')
    byClass(element, 'flag-reason')[1]?.click()
    await flush()

    expect(calls).toEqual(['flag:wrong:앞뒤가 이어지지 않는다'])
    expect(text()).toContain('학습에 사용되지 않습니다')
    expect(byClass(element, 'flag-reason')).toEqual([])
  })

  it('sends null when the note is empty', async () => {
    const { element, calls } = setup()

    byClass(element, 'flag-open')[0]?.click()
    byClass(element, 'flag-reason')[4]?.click()
    await flush()

    expect(calls).toEqual(['flag:other:-'])
  })

  it('offers no way to flag a previous sentence', () => {
    const { element } = setup()

    // MVP UI는 현재 문장에서만 flag를 제공한다. 목록·이력 진입점을 두지 않는다.
    expect(flatText(element)).not.toMatch(/지난 문장|이전 문장|신고 목록/)
  })
})

/** probe가 없는 presentation용 최소 ops. 호출을 기록하지 않는다. */
function quietOps(): InteractionOps {
  return {
    clickItem: async () => EXPLANATION,
    markExplanationRevealed: async () => {},
    revealTranslation: async () => KOREAN,
    selfReport: async () => {},
    respondToProbe: async (_probeId, value) => value,
    flagContent: async () => {},
    reportFailure: () => ({ kind: 'message', text: '저장하지 못했습니다.' }),
  }
}

describe('module boundaries', () => {
  it('keeps the renderers free of api and endpoint imports', async () => {
    const { readFileSync } = await import('node:fs')
    const { fileURLToPath } = await import('node:url')
    const ui = fileURLToPath(new URL('../../src/ui', import.meta.url))

    const offenders = ['interactions.ts', 'explanation.ts', 'probe.ts', 'flag.ts'].filter((name) =>
      /from '\.\.\/(api|endpoints)'/.test(readFileSync(`${ui}/${name}`, 'utf8')),
    )

    // 호출은 주입받는다. 그래서 이 테스트가 fetch를 흉내내지 않고 순서를 단정할 수 있다.
    expect(offenders).toEqual([])
  })
})
