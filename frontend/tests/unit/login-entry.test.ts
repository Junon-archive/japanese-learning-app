/**
 * 부팅과 로그인 진입. **불변식 14: 공개 화면을 열 때 로그인 상태를 확인하지 않는다.**
 *
 * `src/main.ts`를 실제로 부팅한다. `fetch`는 기본으로 던지는 스텁이다 --- 어느 경로가 부르든 호출
 * 기록에 남는다. 정적 검사(`demo-isolation.test.ts`)는 "코드에 없다"를, 이 파일은 "그래서 안
 * 나간다"와 "누를 때만 한 번 나간다"를 말한다.
 *
 * 갈리는 지점:
 *
 * -   부팅 여섯 가지 hash에서 가짜 타이머를 끝까지 진행해도 요청 0건. 상단바 `로그인`을 누르면 정확히 1건.
 * -   `fetchMe` 결과별 화면(200/401/403/그 밖), 로그인 영역 적재 실패.
 * -   **떠난 화면은 새 화면 진입 요청을 시작하지 않는다.** 동적 import 중에 떠나면 `fetchMe`가 없고,
 *     `fetchMe` 대기 중에 떠나면 늦은 응답이 화면도 `POST /api/study/session`도 만들지 않는다.
 * -   URL에서 온 값은 화면에 나오지 않는다.
 */
import ts from 'typescript'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { StudySession, User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeBrowser, FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, descendants, fakeBrowser, fakeDocument, flatText } from './fake-dom'
import type { Project } from './import-graph'
import { createProject, lineOf } from './import-graph'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

const SESSION: StudySession = {
  session_id: 7,
  started_at: '2026-09-13T09:00:00Z',
  last_activity_at: '2026-09-13T09:00:00Z',
  ended_at: null,
  active_seconds: 0,
  target_minutes: 12,
  extended_minutes: 0,
}

const fetchMock = vi.fn<typeof fetch>()

let root: FakeElement
let browser: FakeBrowser

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

/** 동적 import와 그 뒤 microtask를 끝낸다. 가짜 타이머 테스트는 `vi.runAllTimersAsync`를 더 부른다. */
async function settle(): Promise<void> {
  await vi.dynamicImportSettled()
  if (vi.isFakeTimers()) {
    await vi.runAllTimersAsync()
  } else {
    await flush()
  }
  await vi.dynamicImportSettled()
}

async function boot(hash: string): Promise<void> {
  browser = fakeBrowser(hash)
  vi.stubGlobal('location', browser.location)
  vi.stubGlobal('history', browser.history)
  vi.stubGlobal('window', browser.window)
  vi.resetModules()
  await import('../../src/main')
  await settle()
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

function calls(): string[] {
  return fetchMock.mock.calls.map(([url, init]) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '')
    return `${init?.method ?? 'GET'} ${path}`
  })
}

function topBarRight(): string[] {
  const bar = byClass(root, 'topbar')[0]!
  return buttons(byClass(bar, 'topbar-actions')[0]!).map((button) => button.textContent)
}

function loginButton(): FakeElement {
  const button = byClass(root, 'topbar-login')[0]
  expect(button, 'no topbar login button').toBeDefined()
  return button!
}

function screenClass(): string {
  return root.children[0]?.className ?? ''
}

/** `/api/auth/me`만 정한 값으로 답하고 나머지 요청은 끝나지 않게 둔다. */
function answerMe(respond: () => Promise<Response>): void {
  fetchMock.mockImplementation((url) =>
    String(url).endsWith('/api/auth/me') ? respond() : new Promise<Response>(() => {}),
  )
}

/** `METHOD /path`별 응답. 표에 없는 요청은 끝나지 않게 둔다. */
function answer(table: Record<string, () => Promise<Response>>): void {
  fetchMock.mockImplementation((url, init) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`
    return table[key]?.() ?? new Promise<Response>(() => {})
  })
}

function deferred(): { promise: Promise<Response>; resolve: (response: Response) => void } {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((settle) => {
    resolve = settle
  })
  return { promise, resolve }
}

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(() => {
    throw new Error('no request is allowed here')
  })
  root = createFakeElement('div')
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.doUnmock('../../src/private')
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('boot', () => {
  const HASHES = ['', '#/', '#/demo', '#/kana', '#/kana/hiragana', '#/unknown']

  for (const hash of HASHES) {
    it(`makes no request for ${JSON.stringify(hash)} even after every timer, then exactly one on 로그인`, async () => {
      vi.useFakeTimers()
      await boot(hash)
      await vi.runAllTimersAsync()

      expect(fetchMock).not.toHaveBeenCalled()
      expect(topBarRight()).toContain('로그인')

      answerMe(async () => json(401, { detail: 'Not authenticated' }))
      loginButton().click()
      await settle()

      expect(calls()).toEqual(['GET /api/auth/me'])
    })
  }

  it('checks once for a double tap on 로그인', async () => {
    await boot('')
    answerMe(() => new Promise<Response>(() => {}))

    const login = loginButton()
    login.click()
    login.click()
    await settle()

    expect(calls()).toEqual(['GET /api/auth/me'])
    expect(login.textContent).toBe('확인 중')
    expect(login.disabled).toBe(true)
  })
})

describe('login entry result', () => {
  it('goes to the study screen on 200 and starts the session there', async () => {
    await boot('')
    answerMe(async () => json(200, USER))

    loginButton().click()
    await settle()

    expect(screenClass()).toContain('study')
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/study/session'])
  })

  it('titles the study screen for screen readers and says a resumed session in a toast', async () => {
    await boot('')
    answer({
      'GET /api/auth/me': async () => json(200, USER),
      'POST /api/study/session': async () =>
        json(200, { session: SESSION, resumed: true, timed_out_session_id: null }),
      'POST /api/study/session/7/next': async () =>
        json(200, {
          presentation: {
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
          },
        }),
    })

    loginButton().click()
    await settle()

    const title = root.children[0]!.querySelector('h1')!
    expect(title.textContent).toBe('오늘의 학습')
    expect(title.className).toBe('visually-hidden')
    expect(topBarRight()).toEqual(['학습 기록', '로그아웃', '후리가나'])
    const body = (document as unknown as FakeDocument).body
    expect(byClass(body, 'toast').map((toast) => toast.textContent)).toEqual([MESSAGES.sessionResumed])
    // 안내는 오류가 아니다. 화면 안에 인라인 안내로 남기지 않는다.
    expect(flatText(byClass(root, 'notice-slot')[0]!)).not.toContain(MESSAGES.sessionResumed)
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/study/session', 'POST /api/study/session/7/next'])
    // 문장 아래 힌트. 어느 표현이 학습 대상인지 암시하지 않는다.
    expect(flatText(byClass(root, 'sentence-box')[0]!)).toContain('모르는 표현을 눌러 보세요.')
  })

  it('keeps the app name usable while the study screen waits, and closes no session on the way home', async () => {
    await boot('')
    answer({ 'GET /api/auth/me': async () => json(200, USER) })
    loginButton().click()
    await settle()

    const brand = buttons(byClass(root, 'topbar')[0]!)[0]!
    expect(brand.disabled).toBe(false)
    brand.click()
    await settle()

    expect(screenClass()).toContain('home')
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/study/session'])
  })

  it('goes to the login form on 401', async () => {
    await boot('')
    answerMe(async () => json(401, { detail: 'Not authenticated' }))

    loginButton().click()
    await settle()

    expect(screenClass()).toContain('login')
    expect(byClass(root, 'login-form')).toHaveLength(1)
    expect(calls()).toEqual(['GET /api/auth/me'])
  })

  it('shows only the origin rejection on 403, without a retry button', async () => {
    await boot('')
    answerMe(async () => json(403, { detail: 'Origin not allowed' }))

    loginButton().click()
    await settle()

    const notice = byClass(root, 'notice')[0]!
    expect(flatText(notice)).toContain(MESSAGES.originRejected)
    expect(buttons(notice)).toEqual([])
    expect(topBarRight()).toEqual(['로그인'])
    expect(calls()).toEqual(['GET /api/auth/me'])
  })

  it('offers a retry that calls fetchMe again and nothing else on a connection failure', async () => {
    vi.useFakeTimers()
    await boot('#/demo')
    answerMe(async () => json(503, { detail: 'unavailable' }))

    loginButton().click()
    await settle()

    // 503은 api.ts가 유한 번 다시 보낸다. 그 뒤에 안내가 남는다.
    const meCalls = calls().length
    expect(calls().every((call) => call === 'GET /api/auth/me')).toBe(true)
    const notice = byClass(root, 'notice')[0]!
    expect(flatText(notice)).toContain(MESSAGES.loginCheckFailed)
    expect(buttons(notice).map((button) => button.textContent)).toEqual([MESSAGES.retry])
    expect(topBarRight()).toEqual(['로그인'])
    expect(browser.replaceStateCalls).toHaveLength(1)

    answerMe(async () => json(200, USER))
    buttons(notice)[0]!.click()
    await settle()

    // fetchMe만 다시 불렸다. hash 처리(replaceState)는 되풀이되지 않았다.
    expect(calls().slice(meCalls)).toEqual(['GET /api/auth/me', 'POST /api/study/session'])
    expect(browser.replaceStateCalls).toHaveLength(1)
    expect(screenClass()).toContain('study')
  })

  it('restarts the whole entry from the 로그인 on a failure screen', async () => {
    await boot('')
    answerMe(async () => json(403, { detail: 'Origin not allowed' }))
    loginButton().click()
    await settle()
    const failure = root.children[0]

    answerMe(async () => json(401, { detail: 'Not authenticated' }))
    loginButton().click()
    await settle()

    expect(calls()).toEqual(['GET /api/auth/me', 'GET /api/auth/me'])
    expect(root.children[0]).not.toBe(failure)
    expect(screenClass()).toContain('login')
  })

  it('restarts the whole entry from the 로그인 on the connection failure screen', async () => {
    vi.useFakeTimers()
    await boot('#/demo')
    answerMe(async () => json(503, { detail: 'unavailable' }))
    loginButton().click()
    await settle()

    const failure = root.children[0]!
    const staleRetry = buttons(byClass(failure, 'notice')[0]!)[0]!
    expect(staleRetry.textContent).toBe(MESSAGES.retry)
    const firstEntry = calls().length
    expect(browser.replaceStateCalls).toHaveLength(1)
    // 실패 화면에 hash가 다시 생긴 상태를 hashchange 없이 만든다. 재진입이 hash를 다시 지우는지 보려는 것이다.
    history.replaceState(null, '', '/#/demo')
    const replacedBefore = browser.replaceStateCalls.length

    answerMe(async () => json(401, { detail: 'Not authenticated' }))
    loginButton().click()
    await settle()

    // 처음부터: 새 화면, hash 지움, fetchMe 한 번.
    expect(root.children[0]).not.toBe(failure)
    expect(screenClass()).toContain('login')
    expect(browser.replaceStateCalls.slice(replacedBefore)).toEqual([[null, '', '/']])
    expect(location.hash).toBe('')
    expect(calls().slice(firstEntry)).toEqual(['GET /api/auth/me'])

    // 이전 실패 화면은 abort됐다. 떼어진 화면의 `다시 시도하기`는 fetchMe를 부르지 않는다.
    staleRetry.click()
    await settle()
    expect(calls().slice(firstEntry)).toEqual(['GET /api/auth/me'])
    expect(screenClass()).toContain('login')
  })

  it('retries the dynamic import from the 로그인 on the load failure screen', async () => {
    let loads = 0
    // `vi.dynamicImportSettled`는 mock factory 안의 `vi.importActual`을 기다리지 않는다. settle()만 믿으면
    // 두 번째 진입이 끝나기 전에 단정하고, 남은 enterPrivate의 fetchMe가 다음 테스트의 fetchMock에 찍힌다.
    let secondLoadDone: () => void = () => {}
    const secondLoad = new Promise<void>((resolve) => {
      secondLoadDone = resolve
    })
    vi.doMock('../../src/private', async () => {
      loads += 1
      if (loads === 1) throw new Error('chunk load failed')
      try {
        return await vi.importActual('../../src/private')
      } finally {
        secondLoadDone()
      }
    })
    await boot('#/demo')

    loginButton().click()
    await settle()
    const failure = root.children[0]!
    expect(flatText(byClass(failure, 'notice')[0]!)).toContain(MESSAGES.loginAreaLoadFailed)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(loads).toBe(1)
    history.replaceState(null, '', '/#/demo')
    const replacedBefore = browser.replaceStateCalls.length

    answerMe(async () => json(401, { detail: 'Not authenticated' }))
    loginButton().click()
    await secondLoad
    await settle()

    expect(loads).toBe(2)
    expect(root.children[0]).not.toBe(failure)
    expect(screenClass()).toContain('login')
    expect(browser.replaceStateCalls.slice(replacedBefore)).toEqual([[null, '', '/']])
    expect(calls()).toEqual(['GET /api/auth/me'])
  })

  it('leaves only a buttonless notice when the login area fails to load', async () => {
    vi.doMock('../../src/private', () => {
      throw new Error('chunk load failed')
    })
    await boot('#/demo')

    loginButton().click()
    await settle()

    expect(fetchMock).not.toHaveBeenCalled()
    const notice = byClass(root, 'notice')[0]!
    expect(flatText(notice)).toContain(MESSAGES.loginAreaLoadFailed)
    expect(buttons(notice)).toEqual([])
    // 다시 시도는 상단바 로그인이다.
    expect(topBarRight()).toEqual(['로그인'])
    expect(loginButton().disabled).toBe(false)
  })

  it('clears the hash with replaceState and gets no hashchange', async () => {
    await boot('#/demo')
    answerMe(async () => json(401, { detail: 'Not authenticated' }))

    loginButton().click()
    await settle()

    expect(browser.replaceStateCalls).toEqual([[null, '', '/']])
    expect(location.hash).toBe('')
    // hashchange가 왔다면 홈이 로그인 화면을 덮었을 것이다.
    expect(screenClass()).toContain('login')
  })

  it('does not replace the url when there is no hash', async () => {
    await boot('')
    answerMe(async () => json(401, { detail: 'Not authenticated' }))

    loginButton().click()
    await settle()

    expect(browser.replaceStateCalls).toEqual([])
  })
})

describe('leaving during the login entry', () => {
  it('does not call fetchMe when the user leaves while the login area is loading', async () => {
    await boot('')
    answerMe(async () => json(200, USER))

    loginButton().click()
    // 동적 import가 끝나기 전에 떠난다.
    location.hash = '#/demo'
    await settle()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(screenClass()).toContain('demo')
  })

  for (const [name, status, body] of [
    ['200', 200, USER],
    ['401', 401, { detail: 'Not authenticated' }],
    ['failure', 404, { detail: 'Not found' }],
  ] as const) {
    it(`draws nothing and starts no session when a late ${name} arrives after leaving`, async () => {
      await boot('')
      let answer: (response: Response) => void = () => {}
      answerMe(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve
          }),
      )

      loginButton().click()
      await settle()
      expect(calls()).toEqual(['GET /api/auth/me'])

      location.hash = '#/demo'
      await settle()
      const demo = root.children[0]
      expect(screenClass()).toContain('demo')

      answer(json(status, body))
      await settle()

      expect(root.children[0]).toBe(demo)
      expect(calls()).toEqual(['GET /api/auth/me'])
    })
  }
})

describe('leaving after logging in', () => {
  it('starts no session when the login succeeds after the user left', async () => {
    await boot('')
    const login = deferred()
    answer({
      'GET /api/auth/me': async () => json(401, { detail: 'Not authenticated' }),
      'POST /api/auth/login': () => login.promise,
    })
    loginButton().click()
    await settle()

    const [id, secret] = descendants(root).filter((node) => node.tagName === 'INPUT')
    id!.value = 'owner'
    secret!.value = 'secret'
    byClass(root, 'login-form')[0]!.fire('submit')
    await settle()
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/auth/login'])

    location.hash = '#/demo'
    await settle()
    const demo = root.children[0]

    login.resolve(json(200, USER))
    await settle()

    expect(root.children[0]).toBe(demo)
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/auth/login'])
  })

  it('starts the session when the user stayed', async () => {
    await boot('')
    answer({
      'GET /api/auth/me': async () => json(401, { detail: 'Not authenticated' }),
      'POST /api/auth/login': async () => json(200, USER),
    })
    loginButton().click()
    await settle()

    byClass(root, 'login-form')[0]!.fire('submit')
    await settle()

    expect(screenClass()).toContain('study')
    expect(calls()).toEqual(['GET /api/auth/me', 'POST /api/auth/login', 'POST /api/study/session'])
  })
})

describe('url values', () => {
  function printed(): string {
    return descendants(root)
      .flatMap((node) => [node.textContent, node.className, ...Object.values(node.attributes)])
      .join(' ')
  }

  const HOSTILE = ['#/<img src=x onerror=alert(1)>', '#/demo/<img src=x onerror=alert(1)>']

  for (const hash of HOSTILE) {
    it(`never prints ${hash}`, async () => {
      await boot(hash)

      expect(location.hash).toBe('#/')
      expect(printed()).not.toContain('img')
      expect(printed()).not.toContain('onerror')
      expect(screenClass()).toContain('home')
    })
  }

  // #/kana는 하위 경로를 받는다. 모르는 하위 경로도 가나 화면이고 그 값은 화면에 나오지 않는다.
  const KANA_HOSTILE = '#/kana/<img src=x onerror=alert(1)>'

  it(`never prints ${KANA_HOSTILE}`, async () => {
    await boot(KANA_HOSTILE)

    expect(screenClass()).toContain('kana')
    expect(printed()).not.toContain('img')
    expect(printed()).not.toContain('onerror')
  })
})

// ---------------------------------------------------------------------------------------------
// openLogin 호출 위치 (AST)
// ---------------------------------------------------------------------------------------------

/**
 * **`openLogin` 호출은 `ui/topbar.ts`의 로그인 버튼 `click` 리스너 콜백 안 한 곳뿐이다**
 * (`spec/04_SECURITY_AND_DATA.md`의 `모듈 경계`, ADR-022 결정 1). 정적 그래프 검사는 "언제 불리는가"를
 * 보지 못한다 --- 부팅이나 타이머에서 부르면 그래프는 그대로인데 요청이 나간다. 위 부팅 단정이 결과를,
 * 이 검사가 코드 위치를 본다.
 *
 * 주입된 로그인 함수의 이름은 `openLogin`(main·routes·private·공개 화면)과 `onLogin`(`renderTopBar`)이다.
 * 그 이름의 참조는 다음만 허용한다.
 *
 * ``` text
 * 선언          function openLogin, 매개변수, 구조 분해 { openLogin }, 타입의 속성 이름
 * 값 전달       계획된 전달처의 객체 리터럴에서 **같은 이름의 속성**으로만 (PLANNED_DESTINATIONS)
 *                 renderTopBar({ onLogin: openLogin }), renderTopBar({ onLogin: ctx.openLogin })
 *                 startRouter({ openLogin }), enterPrivate({ openLogin }), routes.ts context()의 반환 { openLogin }
 * 존재 확인     onLogin !== undefined
 * 호출          ui/topbar.ts의 로그인 버튼(className에 topbar-login) addEventListener('click', 콜백) 바로 안
 * ```
 *
 * 그 밖(`setTimeout(openLogin)`, `const go = openLogin`, 이름을 바꾸는 구조 분해, `.call` 등)은 위반이다.
 * 이름 기반이므로 다른 이름으로 옮겨 담는 의도적인 우회는 막지 못한다 --- 옮겨 담는 형태 자체를 위반으로 낸다.
 */
const LOGIN_NAMES = new Set(['openLogin', 'onLogin'])

/**
 * 로그인 진입 함수가 값으로 건너가도 되는 곳과 그 속성 이름. 여기 없는 객체 리터럴에 담기면 위반이다 ---
 * `renderNotice(..., { onClick: openLogin })`나 `{ handleEvent: openLogin }`은 click 리스너 밖에서 부르는 길을 연다.
 */
const PLANNED_DESTINATIONS: Readonly<Record<string, string>> = {
  /** 상단바가 로그인 버튼 click 리스너에서만 부른다. */
  renderTopBar: 'onLogin',
  /** main.ts -> 라우터. 공개 화면 ctx로 넘긴다. */
  startRouter: 'openLogin',
  /** main.ts -> 로그인 영역. 실패 화면 상단바에 넘긴다. */
  enterPrivate: 'openLogin',
}
/** routes.ts에서 공개 화면 ctx(`PublicScreenContext`)를 만드는 함수. 반환 객체의 `openLogin`. */
const ROUTE_CONTEXT = { file: 'routes.ts', functionName: 'context', key: 'openLogin' }
const TOPBAR = 'ui/topbar.ts'

type LoginReference = { file: string; line: number; kind: 'call' | 'misuse'; text: string; inLoginClick: boolean }

function inTypeNode(node: ts.Node): boolean {
  for (let current = node.parent; current !== undefined; current = current.parent) {
    if (ts.isTypeNode(current)) return true
  }
  return false
}

/** `addEventListener('click', 콜백)`의 콜백 바로 안이고, 대상이 `topbar-login` 버튼인가. */
function isLoginClickListener(call: ts.CallExpression, file: string, source: ts.SourceFile): boolean {
  if (file !== TOPBAR) return false
  let fn: ts.Node | undefined = call.parent
  while (fn !== undefined && !ts.isFunctionLike(fn)) fn = fn.parent
  if (fn === undefined || !(ts.isArrowFunction(fn) || ts.isFunctionExpression(fn))) return false

  const listen = fn.parent
  if (!ts.isCallExpression(listen) || listen.arguments[1] !== fn) return false
  const [event] = listen.arguments
  const callee = listen.expression
  if (
    !ts.isPropertyAccessExpression(callee) ||
    callee.name.text !== 'addEventListener' ||
    event === undefined ||
    !ts.isStringLiteralLike(event) ||
    event.text !== 'click' ||
    !ts.isIdentifier(callee.expression)
  ) {
    return false
  }

  const target = callee.expression.text
  let isLoginButton = false
  const visit = (node: ts.Node): void => {
    if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isPropertyAccessExpression(node.left) &&
      node.left.name.text === 'className' &&
      ts.isIdentifier(node.left.expression) &&
      node.left.expression.text === target &&
      ts.isStringLiteralLike(node.right) &&
      node.right.text.split(/\s+/).includes('topbar-login')
    ) {
      isLoginButton = true
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return isLoginButton
}

function propertyKey(property: ts.ObjectLiteralElementLike): string | undefined {
  return property.name !== undefined && ts.isIdentifier(property.name) ? property.name.text : undefined
}

/** 이 객체 리터럴 속성이 계획된 전달처에 같은 이름으로 건네는 것인가. */
function isPlannedPass(property: ts.ObjectLiteralElementLike, file: string): boolean {
  const key = propertyKey(property)
  const literal = property.parent
  if (key === undefined || !ts.isObjectLiteralExpression(literal)) return false
  const owner = literal.parent

  if (ts.isCallExpression(owner) && owner.arguments.some((argument) => argument === literal)) {
    const callee = owner.expression
    const name = ts.isIdentifier(callee)
      ? callee.text
      : ts.isPropertyAccessExpression(callee)
        ? callee.name.text
        : undefined
    return name !== undefined && PLANNED_DESTINATIONS[name] === key
  }

  if (file === ROUTE_CONTEXT.file && key === ROUTE_CONTEXT.key && ts.isReturnStatement(owner)) {
    let fn: ts.Node | undefined = owner.parent
    while (fn !== undefined && !ts.isFunctionLike(fn)) fn = fn.parent
    return fn !== undefined && ts.isFunctionDeclaration(fn) && fn.name?.text === ROUTE_CONTEXT.functionName
  }
  return false
}

/** 허용되지 않는 참조와 모든 호출. 선언·계획된 값 전달·존재 확인은 내지 않는다. */
function loginReferences(project: Project): LoginReference[] {
  const found: LoginReference[] = []

  for (const file of project.files) {
    const source = project.sourceFile(file)

    const visit = (node: ts.Node): void => {
      ts.forEachChild(node, visit)
      if (!ts.isIdentifier(node) || !LOGIN_NAMES.has(node.text) || inTypeNode(node)) return

      const parent = node.parent
      // `ctx.openLogin`은 속성 접근 전체를 참조로 본다. `openLogin.x`는 그 자체로 위반이다.
      let reference: ts.Node = node
      if (ts.isPropertyAccessExpression(parent)) {
        if (parent.name !== node) {
          found.push({ file, line: lineOf(node), kind: 'misuse', text: parent.getText(source), inLoginClick: false })
          return
        }
        reference = parent
      }
      const holder = reference.parent

      const declaration =
        (ts.isFunctionDeclaration(holder) && holder.name === reference) ||
        (ts.isParameter(holder) && holder.name === reference) ||
        (ts.isVariableDeclaration(holder) && holder.name === reference) ||
        ((ts.isPropertySignature(holder) || ts.isPropertyDeclaration(holder)) && holder.name === reference) ||
        (ts.isBindingElement(holder) &&
          holder.name === reference &&
          (holder.propertyName === undefined ||
            (ts.isIdentifier(holder.propertyName) && holder.propertyName.text === node.text)))
      const passedAsValue =
        ((ts.isPropertyAssignment(holder) &&
          (holder.name === reference || holder.initializer === reference)) ||
          ts.isShorthandPropertyAssignment(holder)) &&
        isPlannedPass(holder, file)
      const presenceCheck =
        ts.isBinaryExpression(holder) &&
        [
          ts.SyntaxKind.EqualsEqualsEqualsToken,
          ts.SyntaxKind.ExclamationEqualsEqualsToken,
          ts.SyntaxKind.EqualsEqualsToken,
          ts.SyntaxKind.ExclamationEqualsToken,
        ].includes(holder.operatorToken.kind) &&
        [holder.left, holder.right].some(
          (side) => side !== reference && (side.kind === ts.SyntaxKind.NullKeyword || side.getText(source) === 'undefined'),
        )
      if (declaration || passedAsValue || presenceCheck) return

      if (ts.isCallExpression(holder) && holder.expression === reference) {
        found.push({
          file,
          line: lineOf(holder),
          kind: 'call',
          text: holder.getText(source),
          inLoginClick: isLoginClickListener(holder, file, source),
        })
        return
      }
      found.push({ file, line: lineOf(node), kind: 'misuse', text: holder.getText(source).slice(0, 120), inLoginClick: false })
    }
    visit(source)
  }
  return found
}

const describeReference = (ref: LoginReference): string =>
  `${ref.file}:${ref.line} ${ref.kind}${ref.inLoginClick ? ' (login click)' : ''}: ${ref.text}`

describe('openLogin call site (AST)', () => {
  it('is called only inside the login button click listener of ui/topbar.ts, and passed as a value elsewhere', () => {
    const references = loginReferences(createProject())

    expect(references.filter((ref) => ref.kind === 'misuse').map(describeReference)).toEqual([])
    const callSites = references.filter((ref) => ref.kind === 'call')
    expect(callSites.map((ref) => `${ref.file} ${ref.inLoginClick}`)).toEqual([`${TOPBAR} true`])
  })

  it('positive control: the value is actually passed from main.ts and the public screens', () => {
    // 참조가 하나도 없어서 초록인 것이 아니다. 값 전달을 세면 허용 목록이 비어 있지 않다.
    const project = createProject()
    for (const file of ['main.ts', 'routes.ts', 'home/home.ts']) {
      expect(project.read(file)).toMatch(/onLogin: (ctx\.)?openLogin/)
    }
  })

  const TOPBAR_SOURCE = (): string => createProject().read(TOPBAR)

  const MISPLACED: [string, Record<string, string>, 'call' | 'misuse'][] = [
    [
      'passing openLogin to the top bar under another name',
      {
        'home/probe.ts':
          "import { renderTopBar } from '../ui/topbar'\nexport function mount(ctx: { openLogin: () => void }) {\n  return renderTopBar({ onHome: ctx.openLogin, actions: [] })\n}\n",
      },
      'misuse',
    ],
    [
      'passing openLogin as a notice action',
      {
        'home/probe.ts':
          "import { renderNotice } from '../ui/notice'\nexport function mount(ctx: { openLogin: () => void }) {\n  return renderNotice('x', 'error', { label: 'x', onClick: ctx.openLogin })\n}\n",
      },
      'misuse',
    ],
    [
      'passing openLogin as an event listener object',
      {
        'probe.ts':
          "declare const openLogin: () => void\nwindow.addEventListener('hashchange', { handleEvent: openLogin })\n",
      },
      'misuse',
    ],
    [
      'keeping openLogin in an unplanned object',
      { 'demo/probe.ts': 'export function keep(openLogin: () => void) {\n  return { openLogin }\n}\n' },
      'misuse',
    ],
    [
      'a public module calling ctx.openLogin()',
      { 'kana/probe.ts': 'export function mount(ctx: { openLogin: () => void }): void {\n  ctx.openLogin()\n}\n' },
      'call',
    ],
    [
      'a public module calling a destructured openLogin()',
      { 'demo/probe.ts': 'export function mount({ openLogin }: { openLogin: () => void }): void {\n  openLogin()\n}\n' },
      'call',
    ],
    [
      'main.ts scheduling openLogin with a timer',
      { 'probe.ts': 'declare const openLogin: () => void\nsetTimeout(openLogin, 0)\n' },
      'misuse',
    ],
    [
      'aliasing openLogin',
      { 'home/probe.ts': 'export function mount(ctx: { openLogin: () => void }): void {\n  const go = ctx.openLogin\n  go()\n}\n' },
      'misuse',
    ],
    [
      'renaming openLogin in a destructuring',
      { 'home/probe.ts': 'export function mount({ openLogin: go }: { openLogin: () => void }): void {\n  go()\n}\n' },
      'misuse',
    ],
    [
      'openLogin.call()',
      { 'home/probe.ts': 'export function mount(ctx: { openLogin: () => void }): void {\n  ctx.openLogin.call(null)\n}\n' },
      'misuse',
    ],
  ]

  for (const [name, overlay, kind] of MISPLACED) {
    it(`positive control: flags ${name}`, () => {
      const references = loginReferences(createProject(overlay))
      const probe = references.filter((ref) => ref.file in overlay)
      expect(probe.map((ref) => ref.kind)).toContain(kind)
      expect(probe.some((ref) => ref.inLoginClick)).toBe(false)
    })
  }

  it('positive control: flags onLogin() moved out of the click listener in ui/topbar.ts', () => {
    const moved = TOPBAR_SOURCE().replace('right.append(login)', 'right.append(login)\n    onLogin()')
    expect(moved).not.toBe(TOPBAR_SOURCE())
    const calls = loginReferences(createProject({ [TOPBAR]: moved })).filter((ref) => ref.kind === 'call' && ref.file === TOPBAR)
    expect(calls.map((ref) => ref.inLoginClick)).toEqual([true, false])
  })

  it('positive control: flags onLogin() deferred inside the click listener', () => {
    const deferredCall = TOPBAR_SOURCE().replace(/(\n\s*)onLogin\(\)/, '$1queueMicrotask(() => onLogin())')
    expect(deferredCall).not.toBe(TOPBAR_SOURCE())
    const calls = loginReferences(createProject({ [TOPBAR]: deferredCall })).filter((ref) => ref.kind === 'call' && ref.file === TOPBAR)
    expect(calls.map((ref) => ref.inLoginClick)).toEqual([false])
  })

  it('positive control: flags the call on a click listener of another element', () => {
    const otherButton = TOPBAR_SOURCE().replace(
      "home.addEventListener('click', () => {\n    onHome()",
      "home.addEventListener('click', () => {\n    onHome()\n    options.onLogin?.()",
    )
    expect(otherButton).not.toBe(TOPBAR_SOURCE())
    const calls = loginReferences(createProject({ [TOPBAR]: otherButton })).filter((ref) => ref.kind === 'call' && ref.file === TOPBAR)
    expect(calls.map((ref) => ref.inLoginClick).sort()).toEqual([false, true])
  })
})
