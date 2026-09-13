/**
 * 상단바(`renderTopBar`).
 *
 * 갈리는 지점: **`onLogin`은 로그인 버튼을 누를 때만, 한 번만 불린다**(불변식 14). 만들 때
 * 부르지 않고, 연속으로 눌러도 로그인 확인이 겹치지 않는다. 상단바는 레이아웃만 만들고
 * 오른쪽 메뉴는 받은 요소를 그대로 둔다.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount as mountDemo } from '../../src/demo/demo'
import { mount as mountHome } from '../../src/home/home'
import type { PublicScreenContext } from '../../src/routes'
import { mountHistory } from '../../src/ui/history'
import { mountLogin } from '../../src/ui/login'
import { mountStudy } from '../../src/ui/study'
import { renderTopBar } from '../../src/ui/topbar'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument } from './fake-dom'

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

/**
 * 화면별 오른쪽 구성(`03_UI_UX_SPEC.md`의 `상단바` 표). 후리가나 토글은 Wave 3에서 Study Screen과
 * Demo의 `actions`에 더해진다. 로그인 확인 실패(403·연결 실패)와 로그인 영역 불러오기 실패 화면의
 * `로그인`은 `login-entry.test.ts`가 main.ts를 부팅해 본다.
 */
describe('top bar on each screen', () => {
  let root: FakeElement

  function right(): string[] {
    const bar = byClass(root, 'topbar')
    expect(bar).toHaveLength(1)
    return buttons(byClass(bar[0]!, 'topbar-actions')[0]!).map((button) => button.textContent)
  }

  function publicContext(): PublicScreenContext {
    return {
      root: root as unknown as HTMLElement,
      signal: new AbortController().signal,
      subpath: '',
      navigate: () => {},
      openLogin: () => {},
    }
  }

  const noop = (): void => {}

  beforeEach(() => {
    root = createFakeElement('div')
    // 학습·기록 화면이 들어가며 보내는 요청은 끝나지 않게 둔다. 상단바만 본다.
    vi.stubGlobal('fetch', () => new Promise<Response>(() => {}))
  })

  it('home: 로그인', () => {
    mountHome(publicContext())
    expect(right()).toEqual(['로그인'])
  })

  it('demo: 로그인', () => {
    mountDemo(publicContext())
    expect(right()).toEqual(['로그인'])
  })

  it('login: nothing', () => {
    mountLogin(root as unknown as HTMLElement, new AbortController().signal, {
      onHome: noop,
      onAuthenticated: noop,
    })
    expect(right()).toEqual([])
  })

  it('study: 학습 기록, 로그아웃', () => {
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, {
      onHome: noop,
      onUnauthenticated: noop,
      onOpenHistory: noop,
      onLoggedOut: noop,
    })
    expect(right()).toEqual(['학습 기록', '로그아웃'])
  })

  it('history: 로그아웃 only', () => {
    mountHistory(root as unknown as HTMLElement, new AbortController().signal, {
      timezone: 'UTC',
      onHome: noop,
      onBack: noop,
      onUnauthenticated: noop,
      onLoggedOut: noop,
    })
    expect(right()).toEqual(['로그아웃'])
  })

  it('does not import the logout code or anything that reaches the API', () => {
    const source = readFileSync(fileURLToPath(new URL('../../src/ui/topbar.ts', import.meta.url)), 'utf8')
    const specifiers = [...source.matchAll(/(?:from\s*|import\s*\(?\s*)['"]([^'"]+)['"]/g)].map(
      (match) => match[1],
    )

    for (const forbidden of ['logout', 'api', 'endpoints', 'env', 'private']) {
      expect(specifiers.filter((specifier) => specifier!.includes(forbidden))).toEqual([])
    }
  })
})
