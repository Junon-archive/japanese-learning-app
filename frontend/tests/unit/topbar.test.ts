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

import { mount as mountEnDemo } from '../../src/demo/en/demo'
import { mount as mountJaDemo } from '../../src/demo/ja/demo'
import { mount as mountEnHome } from '../../src/home/en'
import { mount as mountJaHome } from '../../src/home/ja'
import { mount as mountLanguageSelectHome } from '../../src/home/language-select'
import type { PublicScreenContext } from '../../src/routes'
import { mountHistory } from '../../src/ui/history'
import { mountLogin } from '../../src/ui/login'
import { MESSAGES } from '../../src/ui/notice'
import { mountStudy } from '../../src/ui/study'
import { renderTopBar } from '../../src/ui/topbar'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument } from './fake-dom'

/**
 * 공개 화면 상단바 오른쪽 버튼(MVP-03 운영 보강, 2026-10-03)과 Login 폼의 제출 버튼. **다른
 * 버튼이다**(`03_UI_UX_SPEC.md`의 `상단바`·`Login`, 합격 기준 33).
 */
const ENTRY_LABEL = '학습하러 가기'
const LOGIN_SUBMIT_LABEL = '로그인'

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
    expect(byText(bar, '학습하러 가기')?.disabled).toBe(false)
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
      '학습하러 가기',
    ])
  })

  it('does not call onLogin while rendering', () => {
    render({ login: true })

    expect(logins).toBe(0)
  })

  it('disables the login button and shows 확인 중 when pressed', () => {
    const bar = render({ login: true })
    const login = byText(bar, '학습하러 가기')!

    login.click()

    expect(logins).toBe(1)
    expect(login.disabled).toBe(true)
    expect(login.textContent).toBe('확인 중')
  })

  it('calls onLogin once for a double tap', () => {
    const bar = render({ login: true })
    const login = byText(bar, '학습하러 가기')!

    login.click()
    login.click()

    expect(logins).toBe(1)
  })
})

/**
 * 화면별 오른쪽 구성(`03_UI_UX_SPEC.md`의 `상단바` 표). 후리가나 토글은 Wave 3에서 Study Screen과
 * Demo의 `actions`에 더해진다. 로그인 확인 실패(403·연결 실패)와 로그인 영역 불러오기 실패 화면의
 * `학습하러 가기`는 `login-entry.test.ts`가 main.ts를 부팅해 본다.
 */
describe('top bar on each screen', () => {
  let root: FakeElement

  function right(): string[] {
    const bar = byClass(root, 'topbar')
    expect(bar).toHaveLength(1)
    return buttons(byClass(bar[0]!, 'topbar-actions')[0]!).map((button) => button.textContent)
  }

  function publicContext(language: 'ja' | 'en' | null): PublicScreenContext {
    return {
      root: root as unknown as HTMLElement,
      signal: new AbortController().signal,
      subpath: '',
      navigate: () => {},
      openLogin: () => {},
      language,
    }
  }

  const noop = (): void => {}

  beforeEach(() => {
    root = createFakeElement('div')
    // 학습·기록 화면이 들어가며 보내는 요청은 끝나지 않게 둔다. 상단바만 본다.
    vi.stubGlobal('fetch', () => new Promise<Response>(() => {}))
  })

  it('language select home: 학습하러 가기', () => {
    mountLanguageSelectHome(publicContext(null))
    expect(right()).toEqual(['학습하러 가기'])
  })

  it('ja home: 학습하러 가기', () => {
    mountJaHome(publicContext('ja'))
    expect(right()).toEqual(['학습하러 가기'])
  })

  it('en home: 학습하러 가기', () => {
    mountEnHome(publicContext('en'))
    expect(right()).toEqual(['학습하러 가기'])
  })

  it('ja demo: 후리가나, 학습하러 가기', () => {
    mountJaDemo(publicContext('ja'))
    expect(right()).toEqual(['후리가나', '학습하러 가기'])
  })

  it('en demo: 학습하러 가기 (후리가나 토글 없음)', () => {
    mountEnDemo(publicContext('en'))
    expect(right()).toEqual(['학습하러 가기'])
  })

  it('login: nothing', () => {
    mountLogin(root as unknown as HTMLElement, new AbortController().signal, {
      onHome: noop,
      onAuthenticated: noop,
    })
    expect(right()).toEqual([])
  })

  /**
   * **두 버튼이 섞이지 않았다**(MVP-03 합격 기준 33, `03_UI_UX_SPEC.md`의 `상단바`와 `Login`).
   * 상단바 진입 버튼은 **목적지**를 말하고(공개 화면은 로그인 여부를 모른다), Login 폼의 제출
   * 버튼은 실제로 자격 증명을 보내므로 계속 `로그인`이다. 한 테스트에서 함께 단언한다 --- 따로
   * 두면 한쪽을 고칠 때 다른 쪽도 같이 고치고 지나간다.
   */
  it('names the top bar entry 학습하러 가기 while the Login form submit stays 로그인', () => {
    mountLanguageSelectHome(publicContext(null))
    expect(right()).toEqual([ENTRY_LABEL])
    expect(ENTRY_LABEL).not.toBe(LOGIN_SUBMIT_LABEL)

    const loginRoot = createFakeElement('div')
    mountLogin(loginRoot as unknown as HTMLElement, new AbortController().signal, {
      onHome: noop,
      onAuthenticated: noop,
    })

    const form = byClass(loginRoot, 'login-form')[0]!
    const submit = buttons(form)
    expect(submit.map((button) => button.textContent)).toEqual([LOGIN_SUBMIT_LABEL])
    expect(submit[0]!.type).toBe('submit')
    // Login 화면의 상단바 오른쪽은 비어 있다 --- 진입 버튼이 여기 다시 나오지 않는다.
    expect(buttons(byClass(loginRoot, 'topbar-actions')[0]!)).toEqual([])
  })

  it('names that same button in the login area load failure notice', () => {
    // 안내 둘째 문장이 버튼을 **이름으로** 가리킨다. 버튼 문구만 바꾸면 안내가 거짓이 된다
    // (`03_UI_UX_SPEC.md`의 `화면 문구 표`, `10_ERROR_HANDLING.md`).
    expect(MESSAGES.loginAreaLoadFailed).toContain(ENTRY_LABEL)
    expect(MESSAGES.loginAreaLoadFailed).not.toContain(`위의 ${LOGIN_SUBMIT_LABEL}을`)
  })

  it('study: 학습 기록, 로그아웃, 후리가나', () => {
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, 'ja', {
      onHome: noop,
      onUnauthenticated: noop,
      onOpenHistory: noop,
      onLoggedOut: noop,
    })
    expect(right()).toEqual(['학습 기록', '로그아웃', '후리가나'])
  })

  it('study (영어): 학습 기록, 로그아웃 (후리가나 토글 없음)', () => {
    mountStudy(root as unknown as HTMLElement, new AbortController().signal, 'en', {
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
