/**
 * 로그아웃 버튼.
 *
 * 갈리는 지점이 하나다: **실패는 로그인 화면으로 보내지 않지만 401은 보낸다.**
 *
 * -   일반 실패에 화면을 로그아웃 상태로 바꾸면 쿠키가 살아 있는데 화면만 나간 것이 되고,
 *     그것은 거짓 표시다(`10_ERROR_HANDLING.md`). 사용자는 "로그아웃했다"고 믿고 기기를
 *     두고 간다.
 * -   401은 폐기할 세션이 이미 없다는 뜻이므로 로그인 화면이 **옳은 결과**다.
 *
 * 여기서는 `fetch`를 세워 실제 `api.ts`를 지난다 --- path와 method까지 이 테스트가 고정한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderLogoutButton } from '../../src/ui/logout'
import type { FakeElement } from './fake-dom'
import { fakeDocument } from './fake-dom'

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

  it('posts to the logout endpoint and goes to the login screen', async () => {
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
    // 폐기할 세션이 이미 없다. 로그인 화면이 옳은 결과다.
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }))

    render().click()
    await flush()

    expect(loggedOut).toBe(1)
    expect(failures).toEqual([])
  })

  it('does not go to the login screen when the session may still be alive', async () => {
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
