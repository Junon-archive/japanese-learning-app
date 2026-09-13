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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeBrowser, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, descendants, fakeBrowser, fakeDocument, flatText } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

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

describe('url values', () => {
  const HOSTILE = ['#/<img src=x onerror=alert(1)>', '#/demo/<img src=x onerror=alert(1)>', '#/kana/<img src=x>']

  for (const hash of HOSTILE) {
    it(`never prints ${hash}`, async () => {
      await boot(hash)

      expect(location.hash).toBe('#/')
      const everything = descendants(root)
        .flatMap((node) => [node.textContent, node.className, ...Object.values(node.attributes)])
        .join(' ')
      expect(everything).not.toContain('img')
      expect(everything).not.toContain('onerror')
      expect(screenClass()).toContain('home')
    })
  }
})
