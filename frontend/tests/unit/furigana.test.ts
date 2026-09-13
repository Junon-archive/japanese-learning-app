/**
 * 후리가나 설정과 토글(`src/ui/furigana.ts`, `furigana.css`). `12_TEST_PLAN.md`의 `후리가나`, 합격 기준 16~19.
 *
 * 갈리는 지점:
 *
 * -   **저장값이 정확히 `{"on": true}`일 때만 켬이다.** 없거나, 형식이 틀리거나, 다른 키가 섞였거나, 읽기가
 *     던지면 끔이다. 저장이 막혀도 그 페이지 안에서는 토글이 동작한다.
 * -   **토글은 문서 class 전환뿐이다.** 문장 노드·표현 버튼·상호작용 영역이 같은 객체로 남고 새 노드를 만들지
 *     않으며 요청이 0건이다. 토글이 문장을 다시 그리게 바꾸면 여기가 빨개진다.
 * -   **CSS의 rt 선택자는 학습 문장 안으로 한정된다.** 설명 시트·probe에 읽기가 퍼지지 않는다.
 *
 * `furigana.ts`는 import 시점에 `localSlot('nc.furigana.v1')`을 만들고 `local-store.ts`는 메모리 기준값을
 * 가지므로 테스트마다 모듈을 새로 불러온다.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Presentation } from '../../src/types'
import type { InteractionOps } from '../../src/ui/interactions'
import type { FakeDocument, FakeElement, FakeNode } from './fake-dom'
import { byClass, createFakeElement, descendants, fakeDocument } from './fake-dom'

type FuriganaModule = typeof import('../../src/ui/furigana')

const KEY = 'nc.furigana.v1'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    data,
    getItem: vi.fn((key: string) => data.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      data.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      data.delete(key)
    }),
  }
}

function throwingStorage() {
  const fail = () => {
    throw new DOMException('denied', 'SecurityError')
  }
  return { getItem: vi.fn(fail), setItem: vi.fn(fail), removeItem: vi.fn(fail) }
}

async function freshFurigana(): Promise<FuriganaModule> {
  vi.resetModules()
  return import('../../src/ui/furigana')
}

let doc: FakeDocument
const fetchMock = vi.fn(() => new Promise<Response>(() => {}))

function isOnClass(): boolean {
  return doc.documentElement.classList.contains('furigana-on')
}

function asFake(element: HTMLElement): FakeElement {
  return element as unknown as FakeElement
}

beforeEach(() => {
  doc = fakeDocument()
  vi.stubGlobal('document', doc)
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('isFuriganaOn', () => {
  it('is off when nothing is stored', async () => {
    vi.stubGlobal('localStorage', memoryStorage())
    const { isFuriganaOn } = await freshFurigana()

    expect(isFuriganaOn()).toBe(false)
  })

  it('is on only for exactly {"on": true}', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ [KEY]: '{"on":true}' }))
    const { isFuriganaOn } = await freshFurigana()

    expect(isFuriganaOn()).toBe(true)
  })

  it.each([
    ['off', '{"on":false}'],
    ['a string flag', '{"on":"true"}'],
    ['a number flag', '{"on":1}'],
    ['another key mixed in', '{"on":true,"size":"large"}'],
    ['a different key', '{"enabled":true}'],
    ['an empty object', '{}'],
    ['a bare true', 'true'],
    ['an array', '[true]'],
    ['null', 'null'],
    ['not JSON', 'on'],
  ])('is off for %s', async (_name, raw) => {
    vi.stubGlobal('localStorage', memoryStorage({ [KEY]: raw }))
    const { isFuriganaOn } = await freshFurigana()

    expect(isFuriganaOn()).toBe(false)
  })

  it('is off when reading the storage throws', async () => {
    const storage = throwingStorage()
    vi.stubGlobal('localStorage', storage)
    const { isFuriganaOn } = await freshFurigana()

    expect(isFuriganaOn()).toBe(false)
    expect(storage.getItem).toHaveBeenCalled()
  })
})

describe('setFuriganaOn', () => {
  it('stores {"on": boolean} under nc.furigana.v1 only and switches the document class', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    const { FURIGANA_ON_CLASS, isFuriganaOn, setFuriganaOn } = await freshFurigana()

    expect(FURIGANA_ON_CLASS).toBe('furigana-on')

    setFuriganaOn(true)
    expect(JSON.parse(storage.data.get(KEY)!)).toEqual({ on: true })
    expect(isOnClass()).toBe(true)
    expect(isFuriganaOn()).toBe(true)

    setFuriganaOn(false)
    expect(JSON.parse(storage.data.get(KEY)!)).toEqual({ on: false })
    expect(isOnClass()).toBe(false)
    expect(isFuriganaOn()).toBe(false)

    expect([...storage.data.keys()]).toEqual([KEY])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps the setting after the module is loaded again (a reload)', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    ;(await freshFurigana()).setFuriganaOn(true)

    const reloaded = await freshFurigana()

    expect(reloaded.isFuriganaOn()).toBe(true)
  })
})

describe('renderFuriganaToggle', () => {
  it('is a 후리가나 button with aria-pressed that applies the stored value to the document when created', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ [KEY]: '{"on":true}' }))
    const { renderFuriganaToggle } = await freshFurigana()

    expect(isOnClass()).toBe(false)
    const toggle = asFake(renderFuriganaToggle())

    expect(toggle.tagName).toBe('BUTTON')
    expect(toggle.type).toBe('button')
    expect(toggle.textContent).toBe('후리가나')
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(isOnClass()).toBe(true)
  })

  it('removes a leftover class when the stored value is off', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ [KEY]: '{"on":false}' }))
    const { renderFuriganaToggle } = await freshFurigana()
    doc.documentElement.classList.add('furigana-on')

    const toggle = asFake(renderFuriganaToggle())

    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(isOnClass()).toBe(false)
  })

  it('flips the setting, the class and aria-pressed on each click, without a request', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    const { isFuriganaOn, renderFuriganaToggle } = await freshFurigana()
    const toggle = asFake(renderFuriganaToggle())

    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(isOnClass()).toBe(false)

    toggle.click()
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(isOnClass()).toBe(true)
    expect(isFuriganaOn()).toBe(true)
    expect(JSON.parse(storage.data.get(KEY)!)).toEqual({ on: true })

    toggle.click()
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(isOnClass()).toBe(false)
    expect(JSON.parse(storage.data.get(KEY)!)).toEqual({ on: false })

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('starts off and still toggles within the page when the storage throws', async () => {
    const storage = throwingStorage()
    vi.stubGlobal('localStorage', storage)
    const { isFuriganaOn, renderFuriganaToggle } = await freshFurigana()

    const toggle = asFake(renderFuriganaToggle())
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(isOnClass()).toBe(false)

    toggle.click()
    expect(storage.setItem).toHaveBeenCalled()
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(isOnClass()).toBe(true)
    expect(isFuriganaOn()).toBe(true)

    toggle.click()
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    expect(isOnClass()).toBe(false)
    expect(isFuriganaOn()).toBe(false)
  })
})

/** 문장 + 상호작용 영역 + 토글이 한 화면에 있을 때 토글이 그 둘을 건드리지 않는다. */
describe('toggling does not re-render', () => {
  const PRESENTATION: Presentation = {
    presentation_id: 4821,
    sentence_id: 1907,
    japanese: '今日は気が乗らなくて家にいた。',
    render_segments: [
      { text: '今日は', sentence_item_id: null, ruby: [{ text: '今日', reading: 'きょう' }, { text: 'は', reading: null }] },
      {
        text: '気が乗らなくて',
        sentence_item_id: 5512,
        ruby: [
          { text: '気', reading: 'き' },
          { text: 'が', reading: null },
          { text: '乗', reading: 'の' },
          { text: 'らなくて', reading: null },
        ],
      },
      { text: '家にいた。', sentence_item_id: null, ruby: [{ text: '家', reading: 'いえ' }, { text: 'にいた。', reading: null }] },
    ],
    presentation_role: 'new',
    review_reason: null,
    context_stage: 'anchor',
    translation_revealed: false,
    tappable_items: [{ sentence_item_id: 5512, learning_item_id: 772 }],
    probe: {
      probe_id: 318,
      learning_item_id: 772,
      prompt: '이 표현을 알고 계세요?',
      expression: '気が乗らない',
      options: ['known', 'uncertain', 'unknown', 'skip'],
    },
  }

  /** 자신을 포함한 모든 노드(텍스트 노드 포함). 같은 객체인지 비교한다. */
  function allNodes(root: FakeNode): FakeNode[] {
    return root.nodeType === 1 ? [root, ...root.childNodes.flatMap(allNodes)] : [root]
  }

  it('keeps the sentence, its buttons and the interaction area as the same nodes and sends nothing', async () => {
    vi.stubGlobal('localStorage', memoryStorage())
    const { renderFuriganaToggle } = await freshFurigana()
    const { renderSentence } = await import('../../src/ui/segments')
    const { createInteractions } = await import('../../src/ui/interactions')

    const calls: string[] = []
    const record =
      (name: string) =>
      async (): Promise<never> => {
        calls.push(name)
        return new Promise<never>(() => {})
      }
    const ops = {
      clickItem: record('click'),
      markExplanationRevealed: record('revealed'),
      revealTranslation: record('translation'),
      selfReport: record('self-report'),
      respondToProbe: record('probe'),
      flagContent: record('flag'),
      reportFailure: () => ({ kind: 'message', text: '실패' }),
    } as unknown as InteractionOps

    const screen = createFakeElement('main')
    const handle = createInteractions(PRESENTATION, ops, {
      signal: new AbortController().signal,
      sheetContainer: screen as unknown as HTMLElement,
    })
    const sentence = asFake(renderSentence(PRESENTATION.render_segments, (id) => handle.tapItem(id)))
    const toggle = asFake(renderFuriganaToggle())
    screen.append(toggle, sentence, asFake(handle.element))

    const token = byClass(sentence, 'token')[0]!
    const before = allNodes(sentence).concat(allNodes(asFake(handle.element)))
    const created = vi.spyOn(doc, 'createElement')

    toggle.click()
    expect(isOnClass()).toBe(true)
    toggle.click()
    expect(isOnClass()).toBe(false)

    expect(created).not.toHaveBeenCalled()
    const after = allNodes(sentence).concat(allNodes(asFake(handle.element)))
    expect(after).toHaveLength(before.length)
    after.forEach((node, index) => expect(node).toBe(before[index]))
    expect(sentence.parentNode).toBe(screen)
    expect(asFake(handle.element).parentNode).toBe(screen)
    expect(byClass(sentence, 'token')[0]).toBe(token)
    expect(descendants(sentence).filter((node) => node.tagName === 'RT')).toHaveLength(4)
    expect(calls).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()

    // 같은 버튼이 그대로 동작한다(handle을 다시 만들지 않았다).
    token.click()
    expect(calls).toEqual(['click'])
  })
})

/**
 * 실제 학습 화면(`mountStudy`)에서. 토글은 상단바에 있고, 켜고 꺼도 화면이 문장을 다시 그리거나 요청을
 * 보내지 않는다. 저장값이 켬이면 학습 화면에 들어올 때 켜져 있다(Demo와 같은 설정 하나).
 */
describe('toggle on the study screen', () => {
  const SESSION = {
    session_id: 7,
    started_at: '2026-09-13T09:00:00Z',
    last_activity_at: '2026-09-13T09:00:00Z',
    ended_at: null,
    active_seconds: 0,
    target_minutes: 12,
    extended_minutes: 0,
  }
  const STUDY_PRESENTATION: Presentation = {
    presentation_id: 11,
    sentence_id: 3,
    japanese: '仕事の気が乗らない。',
    render_segments: [
      { text: '仕事の', sentence_item_id: null, ruby: [{ text: '仕事', reading: 'しごと' }, { text: 'の', reading: null }] },
      {
        text: '気が乗らない',
        sentence_item_id: 21,
        ruby: [
          { text: '気', reading: 'き' },
          { text: 'が', reading: null },
          { text: '乗', reading: 'の' },
          { text: 'らない', reading: null },
        ],
      },
      { text: '。', sentence_item_id: null, ruby: [] },
    ],
    presentation_role: 'new',
    review_reason: null,
    context_stage: 'anchor',
    translation_revealed: false,
    tappable_items: [{ sentence_item_id: 21, learning_item_id: 5 }],
    probe: null,
  }

  function key(url: unknown, init?: RequestInit): string {
    return `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`
  }

  async function settle(): Promise<void> {
    for (let i = 0; i < 3; i += 1) {
      await new Promise((resolve) => {
        setTimeout(resolve, 0)
      })
    }
  }

  async function mountStudyScreen(): Promise<FakeElement> {
    const table: Record<string, () => Response> = {
      'POST /api/study/session': () =>
        new Response(JSON.stringify({ session: SESSION, resumed: false, timed_out_session_id: null }), { status: 200 }),
      'POST /api/study/session/7/next': () =>
        new Response(JSON.stringify({ presentation: STUDY_PRESENTATION }), { status: 200 }),
    }
    fetchMock.mockImplementation(((url: unknown, init?: RequestInit) => {
      const answer = table[key(url, init)]
      return answer === undefined ? new Promise<Response>(() => {}) : Promise.resolve(answer())
    }) as never)
    const { mountStudy } = await import('../../src/ui/study')
    const root = createFakeElement('div')
    const noop = (): void => {}
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, {
      onHome: noop,
      onUnauthenticated: noop,
      onOpenHistory: noop,
      onLoggedOut: noop,
    })
    await settle()
    expect(byClass(root, 'token')).toHaveLength(1)
    return root
  }

  function toggleIn(root: FakeElement): FakeElement {
    const toggles = byClass(byClass(root, 'topbar-actions')[0]!, 'furigana-toggle')
    expect(toggles).toHaveLength(1)
    return toggles[0]!
  }

  it('toggles without redrawing the sentence or the interaction area and without a request', async () => {
    vi.stubGlobal('localStorage', memoryStorage())
    await freshFurigana()
    const root = await mountStudyScreen()
    const toggle = toggleIn(root)
    expect(toggle.getAttribute('aria-pressed')).toBe('false')

    const sentence = byClass(root, 'sentence')[0]!
    const token = byClass(sentence, 'token')[0]!
    const slot = byClass(root, 'interaction-slot')[0]!
    const area = slot.children[0]!
    const rt = descendants(sentence).filter((node) => node.tagName === 'RT')
    expect(rt.map((node) => node.textContent)).toEqual(['しごと', 'き', 'の'])
    const requests = fetchMock.mock.calls.length
    const created = vi.spyOn(doc, 'createElement')

    toggle.click()
    expect(isOnClass()).toBe(true)
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    toggle.click()
    expect(isOnClass()).toBe(false)
    toggle.click()
    expect(isOnClass()).toBe(true)

    expect(created).not.toHaveBeenCalled()
    expect(byClass(root, 'sentence')).toEqual([sentence])
    expect(byClass(root, 'token')).toEqual([token])
    expect(slot.children).toEqual([area])
    expect(slot.children[0]).toBe(area)
    expect(descendants(sentence).filter((node) => node.tagName === 'RT')).toEqual(rt)
    expect(fetchMock.mock.calls.length).toBe(requests)
  })

  it('comes up on when the shared setting is on', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ [KEY]: '{"on":true}' }))
    await freshFurigana()
    const root = await mountStudyScreen()

    expect(toggleIn(root).getAttribute('aria-pressed')).toBe('true')
    expect(isOnClass()).toBe(true)
  })
})

describe('furigana.css', () => {
  const css = readFileSync(fileURLToPath(new URL('../../src/ui/furigana.css', import.meta.url)), 'utf8')
  const rules = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    selectors: match[1]!.split(',').map((selector) => selector.trim().replace(/\s+/g, ' ')),
    body: match[2]!.replace(/\s+/g, ' ').trim(),
  }))

  it('hides rt inside the sentence by default and shows it only under the document class', () => {
    expect(rules).toContainEqual({ selectors: ['.sentence rt'], body: 'display: none;' })
    expect(rules).toContainEqual({ selectors: [':root.furigana-on .sentence rt'], body: 'display: revert;' })
  })

  it('scopes every rt selector to the learning sentence', () => {
    const rtSelectors = rules.flatMap((rule) => rule.selectors).filter((selector) => /(^|[\s>+~])rt\b/.test(selector))

    expect(rtSelectors.length).toBeGreaterThan(0)
    for (const selector of rtSelectors) {
      expect(selector).toMatch(/^(:root\.furigana-on )?\.sentence rt$/)
    }
  })

  it('does not animate the sentence or its readings', () => {
    for (const rule of rules) {
      if (rule.selectors.some((selector) => /\.sentence|\brt\b|\bruby\b/.test(selector))) {
        expect(rule.body).not.toMatch(/transition|animation/)
      }
    }
    expect(css).not.toMatch(/@keyframes/)
  })

  it('is loaded by furigana.ts', () => {
    const source = readFileSync(fileURLToPath(new URL('../../src/ui/furigana.ts', import.meta.url)), 'utf8')
    expect(source).toContain("import './furigana.css'")
  })
})

describe('module boundaries', () => {
  it('imports nothing that reaches the API', () => {
    const source = readFileSync(fileURLToPath(new URL('../../src/ui/furigana.ts', import.meta.url)), 'utf8')
    const specifiers = [...source.matchAll(/(?:from\s*|import\s*\(?\s*)['"]([^'"]+)['"]/g)].map((match) => match[1]!)

    expect(specifiers).toEqual(['../local-store', './furigana.css'])
  })
})
