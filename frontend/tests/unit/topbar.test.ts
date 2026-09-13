/**
 * 상단바(`renderTopBar`).
 *
 * 갈리는 지점: **`onLogin`은 로그인 버튼을 누를 때만, 한 번만 불린다**(불변식 14). 만들 때
 * 부르지 않고, 연속으로 눌러도 로그인 확인이 겹치지 않는다. 상단바는 레이아웃만 만들고
 * 오른쪽 메뉴는 받은 요소를 그대로 둔다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderTopBar } from '../../src/ui/topbar'
import type { FakeElement } from './fake-dom'
import { buttons, createFakeElement, fakeDocument } from './fake-dom'

let homes: number
let logins: number

function render(options: { login?: boolean; actions?: FakeElement[] } = {}): FakeElement {
  return renderTopBar({
    onHome: () => {
      homes += 1
    },
    ...(options.login === true
      ? {
          onLogin: () => {
            logins += 1
          },
        }
      : {}),
    actions: (options.actions ?? []) as unknown as HTMLElement[],
  }) as unknown as FakeElement
}

function byText(bar: FakeElement, text: string): FakeElement | undefined {
  return buttons(bar).find((button) => button.textContent === text)
}

beforeEach(() => {
  homes = 0
  logins = 0
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderTopBar', () => {
  it('goes home from the app name', () => {
    const bar = render({ login: true })

    byText(bar, 'Nihongo Context')!.click()

    expect(homes).toBe(1)
    expect(logins).toBe(0)
    expect(byText(bar, '로그인')?.disabled).toBe(false)
  })

  it('has no login button without onLogin and keeps the given actions in order', () => {
    const history = createFakeElement('button')
    history.textContent = '학습 기록'
    const logout = createFakeElement('button')
    logout.textContent = '로그아웃'

    const bar = render({ actions: [history, logout] })

    expect(buttons(bar).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '학습 기록',
      '로그아웃',
    ])
  })

  it('puts the login button after the actions', () => {
    const toggle = createFakeElement('button')
    toggle.textContent = '후리가나'

    const bar = render({ login: true, actions: [toggle] })

    expect(buttons(bar).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '후리가나',
      '로그인',
    ])
  })

  it('does not call onLogin while rendering', () => {
    render({ login: true })

    expect(logins).toBe(0)
  })

  it('disables the login button and shows 확인 중 when pressed', () => {
    const bar = render({ login: true })
    const login = byText(bar, '로그인')!

    login.click()

    expect(logins).toBe(1)
    expect(login.disabled).toBe(true)
    expect(login.textContent).toBe('확인 중')
  })

  it('calls onLogin once for a double tap', () => {
    const bar = render({ login: true })
    const login = byText(bar, '로그인')!

    login.click()
    login.click()

    expect(logins).toBe(1)
  })
})
