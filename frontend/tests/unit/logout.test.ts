/**
 * 로그아웃 버튼과 로그아웃 뒤의 화면.
 *
 * 갈리는 지점이 하나다: **실패는 선택 홈으로 보내지 않지만 401은 보낸다.**
 *
 * -   일반 실패에 화면을 로그아웃 상태로 바꾸면 쿠키가 살아 있는데 화면만 나간 것이 되고,
 *     그것은 거짓 표시다(`10_ERROR_HANDLING.md`). 사용자는 "로그아웃했다"고 믿고 기기를
 *     두고 간다.
 * -   401은 폐기할 세션이 이미 없다는 뜻이므로 로그아웃한 결과(선택 홈)가 **옳은 결과**다.
 *
 * 여기서는 `fetch`를 세워 실제 `api.ts`를 지난다 --- path와 method까지 이 테스트가 고정한다. 아래
 * `from the login area`는 `main.ts`를 부팅해 상단바 `로그인`부터 지난다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import { renderLogoutButton } from '../../src/ui/logout'
import type { FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeBrowser, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn<typeof fetch>()

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

let loggedOut: number
let failures: string[]

function render(): FakeElement {
  loggedOut = 0
  failures = []
  return renderLogoutButton({
    onLoggedOut: () => {
      loggedOut += 1
    },
    onFailure: (message) => failures.push(message),
  }) as unknown as FakeElement
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('document', fakeDocument())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderLogoutButton', () => {
  it('is one button with the confirmed label and no dialog', () => {
    const button = render()

    expect(button.tagName).toBe('BUTTON')
    expect(button.textContent).toBe('로그아웃')
    // 확인 대화상자를 두지 않는다. 누르면 바로 요청이 나간다.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('posts to the logout endpoint and reports it', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

    render().click()
    await flush()

    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url).endsWith('/api/auth/logout')).toBe(true)
    expect(init?.method).toBe('POST')
    expect(init?.credentials).toBe('include')
    // study session을 닫지 않는다 --- `/finish`를 부르지 않았다.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(loggedOut).toBe(1)
    expect(failures).toEqual([])
  })

  it('treats 401 exactly like success', async () => {
    // 폐기할 세션이 이미 없다. 로그아웃한 결과가 옳다.
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }))

    render().click()
    await flush()

    expect(loggedOut).toBe(1)
    expect(failures).toEqual([])
  })

  it('does not report a logout when the session may still be alive', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 403 }))

    const button = render()
    button.click()
    await flush()

    expect(loggedOut).toBe(0)
    expect(failures).toHaveLength(1)
    expect(failures[0]).not.toBe('')
    // 다시 누를 수 있다. 무한 spinner도 잠긴 버튼도 남기지 않는다.
    expect(button.disabled).toBe(false)
  })

  it('sends one request per tap, not per double tap', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

    const button = render()
    button.click()
    button.click()
    await flush()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(loggedOut).toBe(1)
  })
})

describe('from the login area', () => {
  const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

  let root: FakeElement
  let logoutStatus: number

  function json(status: number, body: unknown): Response {
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  }

  function calls(): string[] {
    return fetchMock.mock.calls.map(
      ([url, init]) => `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`,
    )
  }

  async function settle(): Promise<void> {
    await flush()
    await vi.dynamicImportSettled()
    await flush()
  }

  function press(text: string): void {
    const button = buttons(root).find((candidate) => candidate.textContent === text)
    expect(button, `no button ${text}`).toBeDefined()
    button!.click()
  }

  /** 상단바 `로그인` -> 200 -> Study Screen. 학습 요청은 끝나지 않게 둔다. */
  async function enterStudy(): Promise<void> {
    const browser = fakeBrowser('')
    vi.stubGlobal('location', browser.location)
    vi.stubGlobal('history', browser.history)
    vi.stubGlobal('window', browser.window)
    vi.resetModules()
    await import('../../src/main')
    await settle()

    press('로그인')
    await settle()
    expect(root.children[0]!.className).toContain('study')
  }

  beforeEach(() => {
    root = createFakeElement('div')
    vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
    logoutStatus = 204
    fetchMock.mockImplementation((url, init) => {
      const path = String(url)
      if (path.endsWith('/api/auth/me')) return Promise.resolve(json(200, USER))
      if (path.endsWith('/api/auth/logout') && init?.method === 'POST') {
        return Promise.resolve(json(logoutStatus, { detail: 'x' }))
      }
      return new Promise<Response>(() => {})
    })
  })

  afterEach(() => {
    vi.resetModules()
  })

  function toasts(): string[] {
    return byClass((document as unknown as FakeDocument).body, 'toast').map((toast) => toast.textContent)
  }

  for (const status of [204, 401]) {
    it(`goes to the home with a toast after ${status} from the study screen`, async () => {
      logoutStatus = status
      await enterStudy()

      press('로그아웃')
      await settle()

      expect(root.children[0]!.className).toContain('home')
      expect(toasts()).toEqual([MESSAGES.loggedOut])
      // study session을 닫지 않았다.
      expect(calls().filter((call) => call.includes('/finish'))).toEqual([])
    })
  }

  it('goes to the home after logging out from the history screen', async () => {
    await enterStudy()
    press('학습 기록')
    await settle()
    expect(root.children[0]!.className).toContain('history')

    press('로그아웃')
    await settle()

    expect(root.children[0]!.className).toContain('home')
    expect(toasts()).toEqual([MESSAGES.loggedOut])
  })

  it('stays where it is with a notice when logging out fails', async () => {
    logoutStatus = 403
    await enterStudy()
    const study = root.children[0]

    press('로그아웃')
    await settle()

    expect(root.children[0]).toBe(study)
    expect(flatText(byClass(root, 'notice-slot')[0]!)).toContain(MESSAGES.originRejected)
    expect(toasts()).toEqual([])
  })
})
