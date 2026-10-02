/**
 * 브라우저 재생(`src/ui/speech.ts`, ADR-025 결정 4).
 *
 * 단정하는 것:
 *
 * 1.  **`localService === true`이고 `lang`이 `en`으로 시작하는 음성만** 쓰고, 그 안에서 `en-US`를
 *     먼저 고른다. 네트워크 음성(`localService === false`)만 있으면 **버튼이 없다** --- 그 음성은
 *     브라우저가 외부로 요청해 합성하므로 공개 화면의 격리 검사 (f)를 깨뜨린다.
 * 2.  쓸 음성이 없으면 **버튼을 그리지 않는다.** 비활성 버튼도 아니다.
 * 3.  `getVoices()`가 비어 있으면 `voiceschanged`를 **한 번** 기다리고 그때 그린다. 타임아웃이 없다.
 * 4.  같은 버튼을 다시 누르면 멈추고, 새 재생 전에는 항상 `cancel()`이 먼저다(겹치지 않는다).
 *     화면(문장)을 떠나면 멈춘다.
 * 5.  버튼 자리는 **영어** Study Screen의 문장 옆, 설명 시트의 예문 옆, 영어 demo의 같은 두 자리다.
 *     **일본어에는 없다.** 상단바에도 없다.
 * 6.  **재생은 학습 신호가 아니다**(불변식 25). 눌러도 요청 0건, localStorage 쓰기 0건이다.
 *
 * `speechSynthesis`는 Node(이 테스트 환경)에 **없다.** 그래서 두 전역(`speechSynthesis`,
 * `SpeechSynthesisUtterance`)을 `vi.stubGlobal`로 세운다. 세우지 않은 테스트가 곧 "API가 없는
 * 브라우저"다. 모듈 상태(지금 재생 중인 버튼)가 테스트 사이에 남지 않게 매번 새로 불러온다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PublicScreenContext } from '../../src/routes'
import type { Presentation, StudySession, User } from '../../src/types'
import { memoryStorage } from './demo-harness'
import type { MemoryStorage } from './demo-harness'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument } from './fake-dom'

type FakeVoice = { name: string; lang: string; localService: boolean }

/** 이름은 아무 값이다. 코드가 음성 이름을 보지 않는다는 뜻으로 기기 이름을 쓰지 않는다. */
const LOCAL_US: FakeVoice = { name: 'voice-1', lang: 'en-US', localService: true }
const LOCAL_GB: FakeVoice = { name: 'voice-2', lang: 'en-GB', localService: true }
const NETWORK_US: FakeVoice = { name: 'voice-3', lang: 'en-US', localService: false }
const LOCAL_JA: FakeVoice = { name: 'voice-4', lang: 'ja-JP', localService: true }

type FakeUtteranceShape = { text: string; voice: FakeVoice | null; rate?: number; pitch?: number }

class FakeUtterance implements FakeUtteranceShape {
  text: string
  voice: FakeVoice | null = null
  constructor(text: string) {
    this.text = text
  }
}

type FakeSynth = {
  voices: FakeVoice[]
  /** `speak`에 넘어온 utterance 전부. */
  spoken: FakeUtteranceShape[]
  /** `'cancel'` / `'speak'` 호출 순서. 겹침 방지를 보는 단정이다. */
  calls: string[]
  /** 등록된 리스너의 event 종류. */
  listenerTypes: () => string[]
  fireVoicesChanged: () => void
  /** 다 읽었다(`end`). 테스트가 명시적으로 흘린다. */
  finish: () => void
}

function fakeSynth(voices: FakeVoice[]): FakeSynth {
  const listeners: { type: string; listener: () => void; once: boolean }[] = []
  const spoken: FakeUtteranceShape[] = []
  const calls: string[] = []
  let speaking = false

  const synth = {
    voices,
    spoken,
    calls,
    getVoices: () => synth.voices,
    speak(utterance: FakeUtteranceShape) {
      calls.push('speak')
      spoken.push(utterance)
      speaking = true
    },
    cancel() {
      calls.push('cancel')
      speaking = false
    },
    get speaking(): boolean {
      return speaking
    },
    get pending(): boolean {
      return false
    },
    finish() {
      speaking = false
    },
    addEventListener(type: string, listener: () => void, options?: { once?: boolean }) {
      listeners.push({ type, listener, once: options?.once === true })
    },
    listenerTypes: () => listeners.map((entry) => entry.type),
    fireVoicesChanged() {
      for (const entry of [...listeners]) {
        if (entry.type !== 'voiceschanged') continue
        if (entry.once) listeners.splice(listeners.indexOf(entry), 1)
        entry.listener()
      }
    },
  }
  return synth
}

/** 음성 목록을 가진 브라우저. 부르지 않으면 `speechSynthesis`가 없는 브라우저다. */
function install(voices: FakeVoice[]): FakeSynth {
  const synth = fakeSynth(voices)
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  return synth
}

/** 새 페이지. 모듈 상태(지금 재생 중인 버튼)가 테스트 사이에 남지 않는다. */
async function freshSpeech(): Promise<typeof import('../../src/ui/speech')> {
  vi.resetModules()
  return import('../../src/ui/speech')
}

function slot(text: string, signal: AbortSignal, speech: typeof import('../../src/ui/speech')): FakeElement {
  return speech.renderSpeakButton(text, signal) as unknown as FakeElement
}

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

const SENTENCE = 'So, how was your date last night?'

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// 음성 선택
// ---------------------------------------------------------------------------

describe('voice selection', () => {
  it('uses no voice at all when the browser has no Web Speech API', async () => {
    const speech = await freshSpeech()

    expect(speech.isSpeechAvailable()).toBe(false)
    // 던지지 않는다. 알리지도 않는다.
    expect(() => {
      speech.speak(SENTENCE)
    }).not.toThrow()
    expect(buttons(slot(SENTENCE, new AbortController().signal, speech))).toEqual([])
  })

  it('ignores network voices (localService === false) and draws no button for them', async () => {
    const synth = install([NETWORK_US])
    const speech = await freshSpeech()

    expect(speech.isSpeechAvailable()).toBe(false)
    expect(buttons(slot(SENTENCE, new AbortController().signal, speech))).toEqual([])
    speech.speak(SENTENCE)
    expect(synth.spoken).toEqual([])
  })

  it('positive control: the same voice list with localService true is usable', async () => {
    install([{ ...NETWORK_US, localService: true }])
    const speech = await freshSpeech()

    expect(speech.isSpeechAvailable()).toBe(true)
    expect(buttons(slot(SENTENCE, new AbortController().signal, speech))).toHaveLength(1)
  })

  it('ignores local voices whose lang does not start with en', async () => {
    install([LOCAL_JA])
    const speech = await freshSpeech()

    expect(speech.isSpeechAvailable()).toBe(false)
  })

  it('prefers en-US wherever it is in the list', async () => {
    const synth = install([LOCAL_JA, LOCAL_GB, LOCAL_US])
    const speech = await freshSpeech()

    speech.speak(SENTENCE)

    expect(synth.spoken).toHaveLength(1)
    expect(synth.spoken[0]!.voice).toBe(LOCAL_US)
    expect(synth.spoken[0]!.text).toBe(SENTENCE)
  })

  it('falls back to the first en voice in list order when there is no en-US', async () => {
    const synth = install([LOCAL_JA, LOCAL_GB, { ...LOCAL_GB, name: 'voice-5', lang: 'en-AU' }])
    const speech = await freshSpeech()

    speech.speak(SENTENCE)

    expect(synth.spoken[0]!.voice).toBe(LOCAL_GB)
  })

  it('leaves rate and pitch at their defaults', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()

    speech.speak(SENTENCE)

    expect(synth.spoken[0]!.rate).toBeUndefined()
    expect(synth.spoken[0]!.pitch).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// voiceschanged
// ---------------------------------------------------------------------------

describe('an empty voice list', () => {
  it('draws the button only after voiceschanged, and waits for it exactly once', async () => {
    const synth = install([])
    const speech = await freshSpeech()
    const area = new AbortController()
    const node = slot(SENTENCE, area.signal, speech)

    expect(buttons(node)).toEqual([])
    expect(synth.listenerTypes().filter((type) => type === 'voiceschanged')).toHaveLength(1)

    synth.voices = [LOCAL_US]
    synth.fireVoicesChanged()

    expect(buttons(node)).toHaveLength(1)
    // once다. 두 번째 이벤트가 버튼을 하나 더 그리지 않는다.
    synth.fireVoicesChanged()
    expect(buttons(node)).toHaveLength(1)
  })

  it('sets no timer while waiting', async () => {
    install([])
    const speech = await freshSpeech()
    const timeout = vi.spyOn(globalThis, 'setTimeout')
    const interval = vi.spyOn(globalThis, 'setInterval')

    slot(SENTENCE, new AbortController().signal, speech)

    expect(timeout).not.toHaveBeenCalled()
    expect(interval).not.toHaveBeenCalled()
    timeout.mockRestore()
    interval.mockRestore()
  })

  it('draws nothing when voiceschanged brings no usable voice', async () => {
    const synth = install([])
    const speech = await freshSpeech()
    const node = slot(SENTENCE, new AbortController().signal, speech)

    synth.voices = [NETWORK_US, LOCAL_JA]
    synth.fireVoicesChanged()

    expect(buttons(node)).toEqual([])
  })

  it('draws nothing when voiceschanged arrives after the screen was left', async () => {
    const synth = install([])
    const speech = await freshSpeech()
    const area = new AbortController()
    const node = slot(SENTENCE, area.signal, speech)

    area.abort()
    synth.voices = [LOCAL_US]
    synth.fireVoicesChanged()

    expect(buttons(node)).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// 재생과 멈춤
// ---------------------------------------------------------------------------

describe('playing', () => {
  it('cancels before every new utterance', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    button.click()

    expect(synth.calls).toEqual(['cancel', 'speak'])
    expect(synth.spoken.map((utterance) => utterance.text)).toEqual([SENTENCE])
  })

  it('stops when the same button is pressed again, without speaking twice', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    button.click()
    button.click()

    expect(synth.spoken).toHaveLength(1)
    expect(synth.calls[synth.calls.length - 1]).toBe('cancel')
  })

  it('plays again when the button is pressed after the speech ended', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    button.click()
    synth.finish()
    button.click()

    expect(synth.spoken).toHaveLength(2)
  })

  it('does not overlap two buttons: the second cancels the first', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()
    const area = new AbortController()
    const first = buttons(slot(SENTENCE, area.signal, speech))[0]!
    const second = buttons(slot('Another one.', area.signal, speech))[0]!

    first.click()
    second.click()

    expect(synth.spoken.map((utterance) => utterance.text)).toEqual([SENTENCE, 'Another one.'])
    // 재생마다 바로 앞에 cancel이 있다.
    expect(synth.calls).toEqual(['cancel', 'speak', 'cancel', 'speak'])
  })

  it('stops when the screen (or the sentence) is left', async () => {
    const synth = install([LOCAL_US])
    const speech = await freshSpeech()
    const area = new AbortController()
    const button = buttons(slot(SENTENCE, area.signal, speech))[0]!

    button.click()
    area.abort()

    expect(synth.calls[synth.calls.length - 1]).toBe('cancel')
  })
})

/**
 * 접근성 이름과 상태(`03_UI_UX_SPEC.md`의 화면 문구 표 `소리 재생 버튼`과 `소리 재생` > `버튼`).
 * **아이콘 버튼 하나**이고 보이는 글자가 없으므로 이름은 `aria-label`로만 간다. 토글 상태는
 * `aria-pressed`다. 이 단언이 없으면 구현이 텍스트 라벨로 돌아가도 아무도 잡지 못한다 ---
 * 실제로 한 번 그렇게 어긋났다.
 */
describe('the button is an icon button with an accessible name', () => {
  it('names the button 소리 듣기 and starts unpressed', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    expect(button.getAttribute('aria-label')).toBe('소리 듣기')
    expect(button.getAttribute('aria-pressed')).toBe('false')
  })

  it('shows an icon that the screen reader does not read, and no visible label', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!
    const icon = byClass(button, 'speak-icon')[0]!

    expect(icon.getAttribute('aria-hidden')).toBe('true')
    // 버튼 자신에는 글자가 없다(아이콘은 aria-hidden인 자식이다).
    expect(button.textContent ?? '').toBe('')
  })

  it('becomes 멈추기 and pressed while it is reading', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    button.click()

    expect(button.getAttribute('aria-label')).toBe('멈추기')
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })

  it('goes back to 소리 듣기 when it is pressed again', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const button = buttons(slot(SENTENCE, new AbortController().signal, speech))[0]!

    button.click()
    button.click()

    expect(button.getAttribute('aria-label')).toBe('소리 듣기')
    expect(button.getAttribute('aria-pressed')).toBe('false')
  })

  it('goes back to 소리 듣기 when the screen is left', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const area = new AbortController()
    const button = buttons(slot(SENTENCE, area.signal, speech))[0]!

    button.click()
    area.abort()

    expect(button.getAttribute('aria-pressed')).toBe('false')
  })

  it('releases the first button when a second one takes over', async () => {
    install([LOCAL_US])
    const speech = await freshSpeech()
    const area = new AbortController()
    const first = buttons(slot(SENTENCE, area.signal, speech))[0]!
    const second = buttons(slot('Another one.', area.signal, speech))[0]!

    first.click()
    second.click()

    expect(first.getAttribute('aria-pressed')).toBe('false')
    expect(second.getAttribute('aria-pressed')).toBe('true')
  })
})

// ---------------------------------------------------------------------------
// 버튼 자리: 영어 demo
// ---------------------------------------------------------------------------

const fetchMock = vi.fn(() => {
  throw new Error('a public screen must not make requests')
})

type PublicCtx = {
  root: FakeElement
  signal: AbortSignal
  subpath: string
  navigate: (hash: string) => void
  openLogin: () => void
  language: 'ja' | 'en' | null
}

function publicContext(language: 'ja' | 'en' | null, root: FakeElement): PublicCtx {
  return {
    root,
    signal: new AbortController().signal,
    subpath: '',
    navigate: () => {},
    openLogin: () => {},
    language,
  }
}

describe('where the button is (public demo)', () => {
  let root: FakeElement
  let local: MemoryStorage
  let synth: FakeSynth

  async function openDemo(language: 'ja' | 'en'): Promise<void> {
    vi.resetModules()
    const demo =
      language === 'en' ? await import('../../src/demo/en/demo') : await import('../../src/demo/ja/demo')
    demo.mount(publicContext(language, root) as unknown as PublicScreenContext)
  }

  beforeEach(() => {
    root = createFakeElement('div')
    local = memoryStorage()
    fetchMock.mockClear()
    synth = install([LOCAL_US])
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('localStorage', local)
  })

  it('puts it next to the sentence in the en demo and reads the whole sentence', async () => {
    await openDemo('en')

    const box = byClass(root, 'sentence-box')[0]!
    const speak = byClass(box, 'speak')
    expect(speak).toHaveLength(1)
    const sentence = byClass(root, 'sentence')[0]!.getAttribute('aria-label')

    speak[0]!.click()

    expect(synth.spoken.map((utterance) => utterance.text)).toEqual([sentence])
  })

  it('puts it next to the example sentence in the explanation sheet, and reads only that', async () => {
    await openDemo('en')
    const { DEMO_SENTENCES } = await import('../../src/demo/en/fixture')
    const item = DEMO_SENTENCES[0]!.presentation.tappable_items[0]!
    const example = DEMO_SENTENCES[0]!.explanations[item.sentence_item_id]!.example_sentence

    byClass(root, 'token')[0]!.click()
    await flush()

    const panel = byClass(root, 'explain')[0]!
    const speak = byClass(panel, 'speak')
    expect(speak).toHaveLength(1)

    speak[0]!.click()

    expect(synth.spoken.map((utterance) => utterance.text)).toEqual([example])
  })

  it('has no button anywhere in the ja demo, even with a usable voice', async () => {
    await openDemo('ja')

    expect(byClass(root, 'speak')).toEqual([])
    byClass(root, 'token')[0]!.click()
    await flush()
    expect(byClass(root, 'explain')).toHaveLength(1)
    expect(byClass(root, 'speak')).toEqual([])
  })

  it('keeps the button out of the top bar', async () => {
    await openDemo('en')

    const bar = byClass(root, 'topbar')[0]!
    expect(byClass(bar, 'speak')).toEqual([])
  })

  it('stops the speech when the user moves to the next sentence', async () => {
    await openDemo('en')
    byClass(root, 'speak')[0]!.click()
    expect(synth.calls[synth.calls.length - 1]).toBe('speak')

    buttons(root).find((button) => button.textContent === '다음 문장')!.click()
    await flush()

    // 다음 문장의 재생 버튼이 전 문장을 계속 읽지 않는다.
    expect(synth.calls[synth.calls.length - 1]).toBe('cancel')
  })

  it('is not a learning signal: pressing it sends no request and writes nothing', async () => {
    await openDemo('en')
    const before = [...local.writtenKeys]

    byClass(root, 'speak')[0]!.click()
    await flush()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(local.writtenKeys).toEqual(before)
  })
})

// ---------------------------------------------------------------------------
// 버튼 자리: 로그인 영역의 Study Screen
// ---------------------------------------------------------------------------

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'UTC', starting_level: 'beginner' }

const EN_SESSION: StudySession = {
  session_id: 7,
  language: 'en',
  started_at: '2026-10-01T09:00:00Z',
  last_activity_at: '2026-10-01T09:00:00Z',
  ended_at: null,
  active_seconds: 0,
  target_minutes: 12,
  extended_minutes: 0,
}

const EN_PRESENTATION = {
  presentation_id: 11,
  sentence_id: 3,
  text: SENTENCE,
  render_segments: [
    { text: 'So', sentence_item_id: 21, ruby: [] },
    { text: ', how was your date last night?', sentence_item_id: null, ruby: [] },
  ],
  presentation_role: 'new',
  review_reason: null,
  context_stage: 'anchor',
  translation_revealed: false,
  tappable_items: [{ sentence_item_id: 21, learning_item_id: 5 }],
  probe: null,
} as unknown as Presentation

describe('where the button is (study screen)', () => {
  let root: FakeElement
  let synth: FakeSynth
  let studyFetch: ReturnType<typeof vi.fn>

  async function openStudy(language: 'ja' | 'en'): Promise<void> {
    vi.resetModules()
    const { mountStudy } = await import('../../src/ui/study')
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, language, {
      onHome: () => {},
      onUnauthenticated: () => {},
      onOpenHistory: () => {},
      onLoggedOut: () => {},
    })
    for (let i = 0; i < 3; i += 1) await flush()
  }

  beforeEach(() => {
    root = createFakeElement('div')
    synth = install([LOCAL_US])
    studyFetch = vi.fn((url: unknown, init?: RequestInit) => {
      const path = `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`
      const body: Record<string, unknown> = {
        'GET /api/auth/me': USER,
        'POST /api/study/session': { session: EN_SESSION, resumed: false, timed_out_session_id: null },
        'POST /api/study/session/7/next': { presentation: EN_PRESENTATION },
      }
      if (!(path in body)) return new Promise<Response>(() => {})
      return Promise.resolve(new Response(JSON.stringify(body[path]), { status: 200 }))
    })
    vi.stubGlobal('fetch', studyFetch)
  })

  it('puts it next to the English sentence and reads the whole sentence', async () => {
    await openStudy('en')

    const box = byClass(root, 'sentence-box')[0]!
    expect(byClass(box, 'speak')).toHaveLength(1)

    byClass(box, 'speak')[0]!.click()

    expect(synth.spoken.map((utterance) => utterance.text)).toEqual([SENTENCE])
  })

  it('is not a learning signal: pressing it sends no request', async () => {
    await openStudy('en')
    const before = studyFetch.mock.calls.length

    byClass(root, 'speak')[0]!.click()
    await flush()

    expect(studyFetch.mock.calls.length).toBe(before)
  })

  it('has no button on the Japanese study screen', async () => {
    await openStudy('ja')

    expect(byClass(root, 'sentence')).toHaveLength(1)
    expect(byClass(root, 'speak')).toEqual([])
  })

  it('keeps the button out of the top bar', async () => {
    await openStudy('en')

    expect(byClass(byClass(root, 'topbar')[0]!, 'speak')).toEqual([])
  })
})
