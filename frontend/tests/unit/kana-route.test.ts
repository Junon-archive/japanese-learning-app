/**
 * 가나 학습 **진입과 종료 경로**(`#/kana`). `03_UI_UX_SPEC.md`의 `화면 이동`, `가나 학습`.
 *
 * `src/main.ts`를 실제로 부팅시킨다(`demo-route.test.ts`와 같은 방식).
 *
 * -   `#/kana`, `#/kana/<하위>`로 들어오든 선택 홈 카드로 들어오든 요청 0건이다.
 * -   상단바 오른쪽은 `로그인`뿐이다.
 * -   route의 동적 import가 실패하면 그 자리에 인라인 문구만 남는다(버튼 없음).
 * -   뒤로 가기와 앱 이름으로 선택 홈에 돌아간다.
 *
 * `fetch`는 던지는 스텁이고 모든 테스트 끝에 호출 0회를 단정한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeBrowser, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn<typeof fetch>(() => {
  throw new Error('kana learning must not make requests')
})

let root: FakeElement

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

async function settle(): Promise<void> {
  await flush()
  await vi.dynamicImportSettled()
  await flush()
}

async function boot(hash: string): Promise<void> {
  const browser = fakeBrowser(hash)
  vi.stubGlobal('location', browser.location)
  vi.stubGlobal('history', browser.history)
  vi.stubGlobal('window', browser.window)
  vi.resetModules()
  await import('../../src/main')
  await settle()
}

function screenClass(): string {
  return root.children[0]?.className ?? ''
}

function topBarRight(): string[] {
  const bar = byClass(root, 'topbar')[0]!
  return buttons(byClass(bar, 'topbar-actions')[0]!).map((button) => button.textContent)
}

beforeEach(() => {
  fetchMock.mockClear()
  root = createFakeElement('div')
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  expect(fetchMock).not.toHaveBeenCalled()
  vi.doUnmock('../../src/kana/screen')
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('entering kana learning', () => {
  for (const hash of ['#/kana', '#/kana/hiragana', '#/kana/katakana']) {
    it(`opens ${hash} by url with only 로그인 on the right and no request`, async () => {
      await boot(hash)

      expect(screenClass()).toContain('kana')
      expect(location.hash).toBe(hash)
      expect(topBarRight()).toEqual(['로그인'])
    })
  }

  it('opens from the home card without a request', async () => {
    await boot('')

    byClass(root, 'home-card')[1]!.click()
    await settle()

    expect(location.hash).toBe('#/kana')
    expect(screenClass()).toContain('kana')
  })

  it('shows the load failure inline without a button when the route fails to load', async () => {
    vi.doMock('../../src/kana/screen', () => {
      throw new Error('chunk load failed')
    })
    await boot('#/kana')

    const notice = byClass(root, 'notice')[0]!
    expect(flatText(notice)).toContain(MESSAGES.kanaLoadFailed)
    expect(buttons(notice)).toEqual([])
    expect(topBarRight()).toEqual(['로그인'])
  })
})

describe('leaving kana learning', () => {
  it('goes home with the back button without a request', async () => {
    await boot('')
    byClass(root, 'home-card')[1]!.click()
    await settle()

    history.back()
    await settle()

    expect(location.hash).toBe('')
    expect(screenClass()).toContain('home')
  })

  it('goes home from the app name without a request', async () => {
    await boot('#/kana')

    buttons(root)
      .find((button) => button.textContent === 'Nihongo Context')!
      .click()
    await settle()

    expect(location.hash).toBe('#/')
    expect(screenClass()).toContain('home')
  })
})
