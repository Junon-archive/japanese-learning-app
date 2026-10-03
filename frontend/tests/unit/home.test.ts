/**
 * 홈 화면 셋(`src/home/language-select.ts`, `src/home/ja.ts`, `src/home/en.ts`).
 * `03_UI_UX_SPEC.md`의 `언어 선택 홈`, `언어별 홈`, ADR-025 결정 1·2.
 *
 * 갈리는 지점:
 *
 * -   세 화면 모두 방문자가 무슨 앱인지 바로 안다: 상단바(앱 이름·`학습하러 가기`), 한 줄 소개, 카드.
 * -   **카드에 문장 수 숫자가 없다.**
 * -   카드는 hash로만 이동하고, 만들 때 `openLogin`을 부르지 않는다(불변식 14). 요청도 0건이다.
 * -   언어별 홈의 앱 이름은 **언어 선택 홈(`#/`)**으로 간다(언어별 홈으로 돌아가지 않는다).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount as mountEnHome } from '../../src/home/en'
import { mount as mountJaHome } from '../../src/home/ja'
import { mount as mountLanguageSelectHome } from '../../src/home/language-select'
import type { PublicScreenContext } from '../../src/routes'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn(() => {
  throw new Error('the home must not make requests')
})

let root: FakeElement
let navigations: string[]
let logins: number

function render(
  mount: (ctx: PublicScreenContext) => void,
  language: 'ja' | 'en' | null,
  signal = new AbortController().signal,
): void {
  mount({
    root: root as unknown as HTMLElement,
    signal,
    subpath: '',
    navigate: (hash) => navigations.push(hash),
    openLogin: () => {
      logins += 1
    },
    language,
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

describe('language select home (#/)', () => {
  it('says what the app is in one line under the top bar', () => {
    render(mountLanguageSelectHome, null)

    const screen = root.children[0]!
    expect(screen.children[0]!.className).toBe('topbar')
    expect(screen.querySelector('h1')!.textContent).toBe('실제 문장 속에서 표현을 익히는 앱이에요.')
    expect(buttons(byClass(root, 'topbar')[0]!).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '학습하러 가기',
    ])
  })

  it('has exactly the two language cards with their wording', () => {
    render(mountLanguageSelectHome, null)

    expect(cards()).toHaveLength(2)
    const [ja, en] = cards().map(flatText)
    expect(ja).toContain('일본어')
    expect(ja).toContain('문장 속 표현과 한자 읽기를 익혀요.')
    expect(en).toContain('영어')
    expect(en).toContain('드라마와 대화에서 실제로 쓰는 표현을 익혀요.')
  })

  it('puts no number on the cards', () => {
    render(mountLanguageSelectHome, null)

    for (const card of cards()) expect(flatText(card)).not.toMatch(/\d/)
  })

  it('moves to the language homes by hash only', () => {
    render(mountLanguageSelectHome, null)

    cards()[0]!.click()
    cards()[1]!.click()

    expect(navigations).toEqual(['#/ja', '#/en'])
    expect(logins).toBe(0)
  })

  it('goes home from the app name', () => {
    render(mountLanguageSelectHome, null)

    buttons(root).find((button) => button.textContent === 'Nihongo Context')!.click()

    expect(navigations).toEqual(['#/'])
  })

  it('only passes the login entry to the top bar and does not call it', () => {
    render(mountLanguageSelectHome, null)
    expect(logins).toBe(0)

    byClass(root, 'topbar-login')[0]!.click()

    expect(logins).toBe(1)
  })

  it('has no card for login, account or statistics', () => {
    render(mountLanguageSelectHome, null)

    expect(flatText(root)).not.toMatch(/계정|통계|설정|회원가입/)
  })

  it('draws nothing once its signal is aborted', () => {
    const controller = new AbortController()
    controller.abort()

    render(mountLanguageSelectHome, null, controller.signal)

    expect(root.children).toEqual([])
  })
})

describe('ja home (#/ja)', () => {
  it('says what the app is in one line and has the two cards', () => {
    render(mountJaHome, 'ja')

    expect(root.children[0]!.querySelector('h1')!.textContent).toBe(
      '일본어 표현을 실제 문장 속에서 익히는 앱이에요.',
    )
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
    render(mountJaHome, 'ja')

    for (const card of cards()) expect(flatText(card)).not.toMatch(/\d/)
  })

  it('moves by hash only', () => {
    render(mountJaHome, 'ja')

    cards()[0]!.click()
    cards()[1]!.click()

    expect(navigations).toEqual(['#/ja/demo', '#/ja/kana'])
    expect(logins).toBe(0)
  })

  it('goes to the language select home, not itself, from the app name', () => {
    render(mountJaHome, 'ja')

    buttons(root).find((button) => button.textContent === 'Nihongo Context')!.click()

    expect(navigations).toEqual(['#/'])
  })

  it('draws nothing once its signal is aborted', () => {
    const controller = new AbortController()
    controller.abort()

    render(mountJaHome, 'ja', controller.signal)

    expect(root.children).toEqual([])
  })
})

describe('en home (#/en)', () => {
  it('says what the app is in one line and has exactly one card', () => {
    render(mountEnHome, 'en')

    expect(root.children[0]!.querySelector('h1')!.textContent).toBe(
      '아는 단어인데 안 들리는 표현을 문장 속에서 익혀요.',
    )
    expect(cards()).toHaveLength(1)
    const [demo] = cards().map(flatText)
    expect(demo).toContain('표현 학습 체험해 보기')
    expect(demo).toContain('모르는 표현을 눌러 뜻을 확인해요.')
    expect(demo).toContain('로그인 없이')
  })

  it('puts no number on the card', () => {
    render(mountEnHome, 'en')

    for (const card of cards()) expect(flatText(card)).not.toMatch(/\d/)
  })

  it('moves to the english demo by hash only', () => {
    render(mountEnHome, 'en')

    cards()[0]!.click()

    expect(navigations).toEqual(['#/en/demo'])
    expect(logins).toBe(0)
  })

  it('goes to the language select home, not itself, from the app name', () => {
    render(mountEnHome, 'en')

    buttons(root).find((button) => button.textContent === 'Nihongo Context')!.click()

    expect(navigations).toEqual(['#/'])
  })

  it('draws nothing once its signal is aborted', () => {
    const controller = new AbortController()
    controller.abort()

    render(mountEnHome, 'en', controller.signal)

    expect(root.children).toEqual([])
  })
})
