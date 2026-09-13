/**
 * 선택 홈(`src/home/home.ts`). `03_UI_UX_SPEC.md`의 `선택 홈`.
 *
 * 갈리는 지점:
 *
 * -   방문자가 무슨 앱인지 바로 안다: 상단바(앱 이름·`로그인`), 한 줄 소개, 카드 둘.
 * -   **카드에 문장 수 숫자가 없다.**
 * -   카드는 hash로만 이동하고, 만들 때 `openLogin`을 부르지 않는다(불변식 14). 요청도 0건이다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount } from '../../src/home/home'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn(() => {
  throw new Error('the home must not make requests')
})

let root: FakeElement
let navigations: string[]
let logins: number

function render(signal = new AbortController().signal): void {
  mount({
    root: root as unknown as HTMLElement,
    signal,
    subpath: '',
    navigate: (hash) => navigations.push(hash),
    openLogin: () => {
      logins += 1
    },
  })
}

function cards(): FakeElement[] {
  return byClass(root, 'home-card')
}

beforeEach(() => {
  root = createFakeElement('div')
  navigations = []
  logins = 0
  fetchMock.mockClear()
  vi.stubGlobal('document', fakeDocument())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

describe('home', () => {
  it('says what the app is in one line under the top bar', () => {
    render()

    const screen = root.children[0]!
    expect(screen.children[0]!.className).toBe('topbar')
    expect(screen.querySelector('h1')!.textContent).toBe('일본어 표현을 실제 문장 속에서 익히는 앱이에요.')
    expect(buttons(byClass(root, 'topbar')[0]!).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '로그인',
    ])
  })

  it('has exactly the two cards with their wording', () => {
    render()

    expect(cards()).toHaveLength(2)
    const [demo, kana] = cards().map(flatText)
    expect(demo).toContain('표현 학습 체험해 보기')
    expect(demo).toContain('모르는 표현을 눌러 뜻을 확인해요.')
    expect(demo).toContain('로그인 없이')
    expect(kana).toContain('글자부터 배우기')
    expect(kana).toContain('히라가나와 가타카나를 표와 퀴즈로 익혀요.')
    expect(kana).toContain('히라가나')
    expect(kana).toContain('가타카나')
  })

  it('puts no number on the cards', () => {
    render()

    for (const card of cards()) expect(flatText(card)).not.toMatch(/\d/)
  })

  it('moves by hash only', () => {
    render()

    cards()[0]!.click()
    cards()[1]!.click()

    expect(navigations).toEqual(['#/demo', '#/kana'])
    expect(logins).toBe(0)
  })

  it('goes home from the app name', () => {
    render()

    buttons(root).find((button) => button.textContent === 'Nihongo Context')!.click()

    expect(navigations).toEqual(['#/'])
  })

  it('only passes the login entry to the top bar and does not call it', () => {
    render()
    expect(logins).toBe(0)

    byClass(root, 'topbar-login')[0]!.click()

    expect(logins).toBe(1)
  })

  it('has no card for login, account or statistics', () => {
    render()

    expect(flatText(root)).not.toMatch(/계정|통계|설정|회원가입/)
  })

  it('draws nothing once its signal is aborted', () => {
    const controller = new AbortController()
    controller.abort()

    render(controller.signal)

    expect(root.children).toEqual([])
  })
})
