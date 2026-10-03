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
import { sessionProgress } from '../../src/ui/progress'
import type { FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'UTC', starting_level: 'beginner' }

const SESSION: StudySession = {
  session_id: 7,
  language: 'ja',
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
  text: '気が乗らない。',
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
    // 열린 session이 있으므로 `afterLogin`이 언어 선택 화면을 건너뛰고 바로 Study Screen이다.
    'GET /api/study/session': async () => json(200, { session, resumable: true }),
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

/**
 * **도달 전 세션 종료**(`03_UI_UX_SPEC.md`의 `Session End`의 `도달 전과 도달 후`, MVP-03 합격
 * 기준 32, `mvp-03-english/12_TEST_PLAN.md`의 `도달 전 세션 종료`).
 *
 * 전에는 `오늘 학습 완료`가 **도달 후에만** 그려졌다. 그래서 도달 전 세션에는 끝낼 UI가 하나도
 * 없었고, 언어를 바꾸는 유일한 길("끝내고 다시 들어오기")이 막혔다. 기존 테스트가 전부
 * **도달한 세션**만 썼기 때문에 그 공백을 아무도 보지 않았다 --- 그래서 여기서는 도달/미도달을
 * 둘 다 만든다.
 *
 * **분 수를 테스트에 적지 않는다.** 도달/미도달은 payload의 `target_minutes`·`extended_minutes`로
 * 분모를 계산해 `active_seconds`를 상대적으로 세워 만든다(`ui/progress.ts`가 canonical이고
 * 그 판정을 여기서 복사하지 않는다 --- `sessionProgress`로 전제를 먼저 확인한다).
 */
describe('도달 전 세션 종료', () => {
  const FINISH_LABEL = '오늘 학습 완료'
  const EXTEND_LABEL = '더 학습하기'
  const REACHED_TEXT = '오늘 목표한 시간을 채웠어요.'

  const FINISH = 'POST /api/study/session/7/finish'
  const EXTEND = 'POST /api/study/session/7/extend'
  const COMPLETE = 'POST /api/study/presentations/11/complete'
  const NEXT = 'POST /api/study/session/7/next'
  const OPEN = 'GET /api/study/session'

  /** 분모. `05_API_SPEC.md`의 `진행 상태의 갱신과 세션 종료 판정`이 쓰는 두 값에서만 나온다. */
  function totalSeconds(session: StudySession): number {
    return (session.target_minutes + session.extended_minutes) * 60
  }

  /** 분자를 분모보다 **작게**. 방금 시작한 세션(운영에서 걸린 상태)과 같은 쪽이다. */
  function beforeReached(session: StudySession): StudySession {
    return { ...session, active_seconds: Math.floor(totalSeconds(session) / 10) }
  }

  /** 분자를 분모와 **같게**. 도달 판정이 참이 되는 최소 지점이다. */
  function atReached(session: StudySession): StudySession {
    return { ...session, active_seconds: totalSeconds(session) }
  }

  function screen(): FakeElement {
    return root.children[0]!
  }

  function slot(name: string): FakeElement {
    const found = byClass(root, name)
    expect(found, `slot .${name}`).toHaveLength(1)
    return found[0]!
  }

  function labelsOnScreen(): string[] {
    return buttons(root).map((button) => button.textContent)
  }

  function finishCalls(): string[] {
    return calls().filter((call) => call === FINISH)
  }

  it('shows 오늘 학습 완료 in the finish slot before the goal is reached', async () => {
    const session = beforeReached(SESSION)
    // 전제: 이 payload는 정말 도달 **전**이다. 아니면 아래 단언이 도달 후 화면을 보고 통과한다.
    expect(sessionProgress(session).reached).toBe(false)

    await enterStudy(session)

    // 이 단언이 결함 그 자체다. 없으면 사용자가 그 세션에 갇힌다.
    expect(buttons(slot('finish-slot')).map((button) => button.textContent)).toEqual([FINISH_LABEL])
  })

  it('shows neither the reached wording nor 더 학습하기 before the goal is reached', async () => {
    await enterStudy(beforeReached(SESSION))

    expect(flatText(screen())).not.toContain(REACHED_TEXT)
    expect(labelsOnScreen()).not.toContain(EXTEND_LABEL)
    expect(byClass(root, 'session-end')).toEqual([])
    expect(slot('end-slot').childNodes).toEqual([])
    // 종료 버튼은 하나뿐이다.
    expect(labelsOnScreen().filter((label) => label === FINISH_LABEL)).toHaveLength(1)
  })

  it('adds the wording and 더 학습하기 when the goal becomes reached, without a second 오늘 학습 완료', async () => {
    const reached = atReached(SESSION)
    expect(sessionProgress(reached).reached).toBe(true)
    table = {
      [COMPLETE]: async () => json(200, { presentation_id: 11, completed_at: '2026-09-13T09:12:00Z' }),
      [NEXT]: async () => json(200, { presentation: PRESENTATION }),
    }
    await enterStudy(beforeReached(SESSION))
    expect(buttons(slot('finish-slot'))).toHaveLength(1)

    // 진행은 `/complete` 뒤의 `GET /session` 한 번으로만 움직인다(`ui/study.ts`).
    table[OPEN] = async () => json(200, { session: reached, resumable: true })
    press('다음 문장')
    await settle()

    // 도달 후 화면은 바뀌지 않았다: 안내 + `오늘 학습 완료` + `더 학습하기`.
    const end = byClass(root, 'session-end')
    expect(end).toHaveLength(1)
    expect(buttons(end[0]!).map((button) => button.textContent)).toEqual([FINISH_LABEL, EXTEND_LABEL])
    // 도달 전 자리는 비었다. 종료 버튼이 동시에 둘 보이지 않는다.
    expect(slot('finish-slot').childNodes).toEqual([])
    expect(labelsOnScreen().filter((label) => label === FINISH_LABEL)).toHaveLength(1)
  })

  it('keeps the reached block exactly as it was (문구·클래스·버튼 순서)', async () => {
    await enterStudy(atReached(SESSION))

    expect(slot('finish-slot').childNodes).toEqual([])
    const end = slot('end-slot').children
    expect(end.map((node) => `${node.tagName}.${node.className}`)).toEqual(['SECTION.session-end'])
    const box = end[0]!
    expect(box.children.map((node) => `${node.tagName}.${node.className}`)).toEqual([
      'P.session-end-text',
      'DIV.session-end-actions',
    ])
    expect(box.children[0]!.textContent).toBe(REACHED_TEXT)
    expect(
      box.children[1]!.children.map((node) => `${node.className} ${node.textContent}`),
    ).toEqual([`primary ${FINISH_LABEL}`, `secondary ${EXTEND_LABEL}`])
  })

  it('finishes the session with exactly one /finish and no /extend, straight to the completion screen', async () => {
    const session = beforeReached(SESSION)
    table = {
      [FINISH]: async () => json(200, { ...session, ended_at: '2026-09-13T09:02:00Z' }),
    }
    await enterStudy(session)
    const before = calls().length

    press(FINISH_LABEL)
    await settle()

    // 한 번 누르면 바로 완료 화면이다. 확인 대화상자도 2단계 누르기도 없다.
    expect(calls().slice(before)).toEqual([FINISH])
    expect(calls()).not.toContain(EXTEND)
    expect(byClass(root, 'session-finished')).toHaveLength(1)
    expect(byClass(root, 'finish-slot')).toEqual([])
    expect(labelsOnScreen()).not.toContain(FINISH_LABEL)
  })

  it('sends /finish once for a double tap', async () => {
    const session = beforeReached(SESSION)
    const finish = deferred()
    table = { [FINISH]: () => finish.promise }
    await enterStudy(session)
    const button = buttons(slot('finish-slot'))[0]!

    button.click()
    button.click()
    await settle()
    finish.resolve(json(200, { ...session, ended_at: '2026-09-13T09:02:00Z' }))
    await settle()

    expect(finishCalls()).toHaveLength(1)
    expect(byClass(root, 'session-finished')).toHaveLength(1)
  })

  /**
   * `03_UI_UX_SPEC.md`의 `완료 화면`: "새 세션 시작 버튼을 두지 않는다" --- 세션 행이 부풀고
   * "한 번 더 하시죠"라는 압박이 된다. 2026-10-03 보강이 더한 것은 Study Screen의 **끝내는**
   * 버튼이고, 완료 화면에는 아무것도 더하지 않았다(`mvp-03-english/12_TEST_PLAN.md`의
   * `완료 화면에 버튼이 하나도 없다`). 상단바는 로그인 영역 공통 틀이라 세는 범위에서 뺀다.
   */
  it('leaves no button in the body of the completion screen (새 세션 시작 버튼을 두지 않는다)', async () => {
    const session = beforeReached(SESSION)
    table = { [FINISH]: async () => json(200, { ...session, ended_at: '2026-09-13T09:02:00Z' }) }
    await enterStudy(session)

    press(FINISH_LABEL)
    await settle()

    const topBar = byClass(screen(), 'topbar')[0]!
    const inTopBar = new Set(buttons(topBar))
    expect(byClass(root, 'session-finished')).toHaveLength(1)
    // 본문 버튼 0개. `다른 언어로`도 `한 번 더`도 `처음부터 다시`도 없다.
    expect(buttons(screen()).filter((button) => !inTopBar.has(button))).toEqual([])
    // 양성 대조군: 세는 범위가 통째로 비어서 통과한 것이 아니다. 상단바 버튼은 그대로 있다.
    expect(buttons(topBar).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '학습 기록',
      '로그아웃',
      '후리가나',
    ])
    // 화면에 남은 것은 상단바와 완료 블록 둘뿐이다(문장도 Next도 없다).
    expect(screen().children.map((node) => node.className)).toEqual(['topbar', 'session-finished'])
  })

  it('puts the button right under the progress slot, outside the 다음 문장 footer', async () => {
    await enterStudy(beforeReached(SESSION))

    // 자리 회귀. footer에 붙어 있으면 `다음 문장`을 누르려다 세션을 끝낸다.
    const order = screen().children.map((node) => node.className)
    expect(order[order.indexOf('progress-slot') + 1]).toBe('finish-slot')
    const button = buttons(slot('finish-slot'))[0]!
    expect(button.className.split(' ')).toContain('secondary')
    expect(buttons(byClass(root, 'study-foot')[0]!).map((node) => node.textContent)).toEqual([
      '다음 문장',
    ])
  })
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

  /** `enterStudy`의 `afterLogin`이 진입 시 한 번 부른다(언어 선택 화면을 건너뛰는 분기). */
  function sessionGets(): number {
    return calls().filter((call) => call === 'GET /api/study/session').length
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
    // 떠난 뒤 늦게 온 409는 `refreshSession`(=`GET /api/study/session`)으로 이어지지 않는다.
    // 진입 때의 한 번(언어 선택 화면을 건너뛰는 분기) 말고는 더 부르지 않는다.
    expect(sessionGets()).toBe(1)
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
    mountStudy(root as unknown as HTMLElement, screen.signal, 'ja', {
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
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, 'ja', {
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
