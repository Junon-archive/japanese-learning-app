/**
 * 학습 화면(`src/ui/study.ts`)과 로그인 영역 안의 화면 전환(`src/private.ts`)에서 **떠난 화면의 늦은 응답.**
 *
 * 갈리는 지점(05_API_SPEC.md의 `explanation_revealed를 언제 보내는가`, 04_SECURITY_AND_DATA.md의 `모듈 경계`):
 *
 * -   상단바 `학습 기록`으로 떠나면 학습 화면의 signal이 abort된다. 늦게 온 `/click` 응답은 시트를 열지 않고
 *     `explanation-revealed`를 보내지 않는다.
 * -   세션 시작 응답 전에 떠나면 늦은 응답이 토스트도 `/next`도 만들지 않는다.
 * -   `오늘 학습 완료` 뒤 늦게 온 `/click` 응답도 시트를 열지 않는다.
 * -   떠난 뒤 늦게 온 409(닫힌 session / 완료된 presentation)는 study session을 새로 시작하지 않는다.
 *
 * `fetch`를 세워 실제 `api.ts`를 지난다. 요청 기록이 곧 단정이다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Presentation, StudySession, User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'UTC', starting_level: 'beginner' }

const SESSION: StudySession = {
  session_id: 7,
  started_at: '2026-09-13T09:00:00Z',
  last_activity_at: '2026-09-13T09:00:00Z',
  ended_at: null,
  active_seconds: 0,
  target_minutes: 12,
  extended_minutes: 0,
}

const PRESENTATION: Presentation = {
  presentation_id: 11,
  sentence_id: 3,
  japanese: '気が乗らない。',
  render_segments: [
    { text: '気が乗らない', sentence_item_id: 21, ruby: [] },
    { text: '。', sentence_item_id: null, ruby: [] },
  ],
  presentation_role: 'new',
  review_reason: null,
  context_stage: 'anchor',
  translation_revealed: false,
  tappable_items: [{ sentence_item_id: 21, learning_item_id: 5 }],
  probe: null,
} as unknown as Presentation

const EXPLANATION = {
  sentence_item_id: 21,
  learning_item_id: 5,
  canonical_form: '気が乗らない',
  reading: 'きがのらない',
  item_type: 'expression',
  core_meaning: '내키지 않다',
  meaning_in_context: '마음이 내키지 않았다',
  nuance: '일상 표현',
  example_sentence: '今日は気が乗らない。',
  example_translation: null,
}

const CLICK = 'POST /api/study/presentations/11/items/21/click'
const REVEALED = 'POST /api/study/presentations/11/items/21/explanation-revealed'

const fetchMock = vi.fn<typeof fetch>()
/**
 * 테스트마다 새로 불러온다. `api.ts`는 같은 요청이 날아가 있으면 합치므로(모듈 상태), 앞 테스트에서 끝나지
 * 않은 요청이 뒤 테스트의 요청을 삼키지 않게 한다.
 */
let enterPrivate: typeof import('../../src/private').enterPrivate
let mountStudy: typeof import('../../src/ui/study').mountStudy
let root: FakeElement
let doc: FakeDocument
let table: Record<string, () => Promise<Response>>

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status })
}

function deferred(): { promise: Promise<Response>; resolve: (response: Response) => void } {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((settle) => {
    resolve = settle
  })
  return { promise, resolve }
}

function key(url: unknown, init?: RequestInit): string {
  return `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`
}

function calls(): string[] {
  return fetchMock.mock.calls.map(([url, init]) => key(url, init))
}

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 0)
    })
  }
}

function press(text: string): void {
  const button = buttons(root).find((candidate) => candidate.textContent === text)
  expect(button, `no button ${text}`).toBeDefined()
  button!.click()
}

function toasts(): FakeElement[] {
  return byClass(doc.body, 'toast')
}

/** 로그인 영역에 들어가 문장이 보이는 학습 화면까지. `/click`은 `click` 약속으로 답한다. */
async function enterStudy(session: StudySession = SESSION): Promise<AbortController> {
  table = {
    'GET /api/auth/me': async () => json(200, USER),
    'POST /api/study/session': async () => json(200, { session, resumed: false, timed_out_session_id: null }),
    'POST /api/study/session/7/next': async () => json(200, { presentation: PRESENTATION }),
    ...table,
  }
  const area = new AbortController()
  enterPrivate({ root: root as unknown as HTMLElement, signal: area.signal, goHome: () => {}, openLogin: () => {} })
  await settle()
  expect(byClass(root, 'token')).toHaveLength(1)
  return area
}

beforeEach(async () => {
  vi.resetModules()
  ;({ enterPrivate } = await import('../../src/private'))
  ;({ mountStudy } = await import('../../src/ui/study'))
  root = createFakeElement('div')
  doc = fakeDocument()
  vi.stubGlobal('document', doc)
  table = {}
  fetchMock.mockReset()
  fetchMock.mockImplementation((url, init) => table[key(url, init)]?.() ?? new Promise<Response>(() => {}))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('late /click after leaving the study screen', () => {
  it('opens the sheet and sends explanation-revealed when the user stayed', async () => {
    table = { [CLICK]: async () => json(200, EXPLANATION) }
    await enterStudy()

    byClass(root, 'token')[0]!.click()
    await settle()

    expect(byClass(root, 'sheet')).toHaveLength(1)
    expect(calls()).toContain(REVEALED)
  })

  it('draws no sheet and sends no explanation-revealed after leaving for 학습 기록', async () => {
    const click = deferred()
    table = { [CLICK]: () => click.promise }
    await enterStudy()

    byClass(root, 'token')[0]!.click()
    await settle()
    press('학습 기록')
    await settle()
    expect(root.children[0]!.className).toContain('history')

    click.resolve(json(200, EXPLANATION))
    await settle()

    expect(byClass(root, 'sheet')).toEqual([])
    expect(calls()).not.toContain(REVEALED)
    expect(calls().filter((call) => call === CLICK)).toHaveLength(1)
  })

  it('draws no sheet and sends no explanation-revealed after 오늘 학습 완료', async () => {
    const click = deferred()
    const reached = { ...SESSION, active_seconds: 12 * 60 }
    table = {
      [CLICK]: () => click.promise,
      'POST /api/study/session/7/finish': async () => json(200, { ...reached, ended_at: '2026-09-13T09:12:00Z' }),
    }
    await enterStudy(reached)

    byClass(root, 'token')[0]!.click()
    await settle()
    press('오늘 학습 완료')
    await settle()
    expect(byClass(root, 'session-finished')).toHaveLength(1)

    click.resolve(json(200, EXPLANATION))
    await settle()

    expect(byClass(root, 'sheet')).toEqual([])
    expect(calls()).not.toContain(REVEALED)
  })
})

describe('late 409 after leaving', () => {
  const FINISHED = () => json(409, { detail: 'Study session is already finished' })

  function sessionStarts(): number {
    return calls().filter((call) => call === 'POST /api/study/session').length
  }

  it('starts no session for a late 409 on /click', async () => {
    const click = deferred()
    table = { [CLICK]: () => click.promise }
    await enterStudy()

    byClass(root, 'token')[0]!.click()
    await settle()
    press('학습 기록')
    await settle()
    click.resolve(FINISHED())
    await settle()

    expect(sessionStarts()).toBe(1)
    expect(root.children[0]!.className).toContain('history')
  })

  it('starts no session for a late 409 on another interaction (translation)', async () => {
    const reveal = deferred()
    table = { 'POST /api/study/presentations/11/translation/reveal': () => reveal.promise }
    await enterStudy()

    press('문장 뜻 보기')
    await settle()
    press('학습 기록')
    await settle()
    reveal.resolve(FINISHED())
    await settle()

    expect(sessionStarts()).toBe(1)
    expect(root.children[0]!.className).toContain('history')
  })

  it('starts no session for a late 409 on /complete', async () => {
    const complete = deferred()
    table = { 'POST /api/study/presentations/11/complete': () => complete.promise }
    await enterStudy()

    press('다음 문장')
    await settle()
    press('학습 기록')
    await settle()
    complete.resolve(json(409, { detail: 'Presentation is already completed' }))
    await settle()

    expect(sessionStarts()).toBe(1)
    expect(calls()).not.toContain('GET /api/study/session')
  })

  it('recovers with a new session when the user stayed', async () => {
    table = { [CLICK]: FINISHED }
    await enterStudy()

    byClass(root, 'token')[0]!.click()
    await settle()

    expect(sessionStarts()).toBe(2)
  })
})

describe('late session start after leaving', () => {
  it('shows no toast and asks for no sentence', async () => {
    const start = deferred()
    table = { 'POST /api/study/session': () => start.promise }
    const screen = new AbortController()
    mountStudy(root as unknown as HTMLElement, screen.signal, {
      onHome: () => {},
      onUnauthenticated: () => {},
      onOpenHistory: () => {},
      onLoggedOut: () => {},
    })
    await settle()
    expect(calls()).toEqual(['POST /api/study/session'])

    screen.abort()
    start.resolve(json(200, { session: SESSION, resumed: true, timed_out_session_id: null }))
    await settle()

    expect(toasts()).toEqual([])
    expect(calls()).toEqual(['POST /api/study/session'])
  })

  it('shows the resume toast and asks for the sentence when the user stayed', async () => {
    table = {
      'POST /api/study/session': async () => json(200, { session: SESSION, resumed: true, timed_out_session_id: null }),
    }
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, {
      onHome: () => {},
      onUnauthenticated: () => {},
      onOpenHistory: () => {},
      onLoggedOut: () => {},
    })
    await settle()

    expect(toasts().map((toast) => toast.textContent)).toEqual([MESSAGES.sessionResumed])
    expect(calls()).toEqual(['POST /api/study/session', 'POST /api/study/session/7/next'])
  })
})
