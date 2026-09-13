/**
 * 로그인 화면(`src/ui/login.ts`). `03_UI_UX_SPEC.md`의 `Login`.
 *
 * 갈리는 지점:
 *
 * -   **폼은 두 필드와 버튼 하나가 전부다.** 폼 안에 demo 진입 버튼이 없다(MVP-02). 회원가입·비밀번호
 *     재설정 진입점도 없다.
 * -   **실패 문구는 사유와 무관한 한 문구다.** 서버가 같은 401로 감춘 것을 화면이 가르지 않는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { User } from '../../src/types'
import { mountLogin } from '../../src/ui/login'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, descendants, fakeDocument, flatText } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

const fetchMock = vi.fn<typeof fetch>()

let root: FakeElement
let authenticated: User[]

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

function render(): void {
  authenticated = []
  mountLogin(root as unknown as HTMLElement, new AbortController().signal, {
    onHome: () => {},
    onAuthenticated: (user) => authenticated.push(user),
  })
}

function inputs(): FakeElement[] {
  return descendants(root).filter((node) => node.tagName === 'INPUT')
}

async function submit(loginId: string, password: string): Promise<void> {
  const [id, secret] = inputs()
  id!.value = loginId
  secret!.value = password
  byClass(root, 'login-form')[0]!.fire('submit')
  await flush()
}

beforeEach(() => {
  root = createFakeElement('div')
  fetchMock.mockReset()
  vi.stubGlobal('document', fakeDocument())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('login form', () => {
  it('is two fields and one button, with no demo entry', () => {
    render()

    const form = byClass(root, 'login-form')[0]!
    expect(inputs().map((input) => input.type)).toEqual(['text', 'password'])
    expect(buttons(form).map((button) => button.textContent)).toEqual(['로그인'])
    expect(byClass(root, 'demo-enter')).toEqual([])
    expect(root.children[0]!.querySelector('h1')!.textContent).toBe('로그인')
    expect(descendants(root).filter((node) => node.tagName === 'LABEL').map((label) => label.textContent)).toEqual([
      '아이디',
      '비밀번호',
    ])
    expect(flatText(root)).not.toMatch(/데모|체험|회원가입|비밀번호 재설정|비밀번호 찾기/)
  })

  it('hands the user from the login response to the caller', async () => {
    render()
    fetchMock.mockResolvedValue(new Response(JSON.stringify(USER), { status: 200 }))

    await submit('owner', 'secret')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url).endsWith('/api/auth/login')).toBe(true)
    expect(init?.method).toBe('POST')
    expect(authenticated).toEqual([USER])
  })

  it('shows one message for any 401, whatever the reason', async () => {
    render()
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: 'Invalid credentials' }), { status: 401 }))

    await submit('nobody', 'wrong')

    expect(authenticated).toEqual([])
    expect(flatText(byClass(root, 'notice-slot')[0]!).trim()).toBe(MESSAGES.loginFailed)
    // 비밀번호는 비우고 아이디는 둔다.
    expect(inputs().map((input) => input.value)).toEqual(['nobody', ''])
  })
})
