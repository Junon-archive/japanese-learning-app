/**
 * Demo **진입과 종료 경로**. 요청 0건이 여기서 고정된다.
 *
 * 이 파일은 `src/main.ts`를 실제로 부팅시킨다. 한때 demo 종료 경로가 `GET /api/auth/me`를 불러
 * **demo가 backend를 호출했다.** vitest가 전부 초록인 상태에서 브라우저 e2e만 그것을 잡았다. 그래서
 * 여기서 단정한다:
 *
 * -   `#/demo`로 들어오든 선택 홈 카드로 들어오든 요청 0건이다.
 * -   나가는 길은 상단바(앱 이름 -> 선택 홈)와 뒤로 가기이고, 어느 쪽도 요청을 만들지 않는다.
 * -   demo 화면 안에 로그인 화면으로 가는 버튼이 없다. 상단바 오른쪽은 후리가나 토글과 `로그인`이다.
 * -   저장된 진도가 있으면 route로 들어와도 그 자리에서 이어진다. 이어지는 데도 요청이 없다.
 *
 * `fetch`는 던지는 스텁이고 모든 테스트 끝에 호출 0회를 단정한다. 진행 규칙과 저장값 검증은
 * `demo-progress.test.ts`, 화면 문구는 `demo.test.ts`가 본다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEMO_SENTENCES } from '../../src/demo/fixture'
import { DEMO_FIXTURE, advance, initialProgress } from '../../src/demo/progress'
import { memoryStorage } from './demo-harness'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeBrowser, fakeDocument } from './fake-dom'

const fetchMock = vi.fn<typeof fetch>(() => {
  throw new Error('the demo must not make requests')
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

function press(text: string): void {
  const button = buttons(root).find((candidate) => candidate.textContent === text)
  expect(button, `no button ${text}`).toBeDefined()
  button!.click()
}

beforeEach(() => {
  fetchMock.mockClear()
  root = createFakeElement('div')
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('entering the demo', () => {
  it('opens by url without a request', async () => {
    await boot('#/demo')

    expect(screenClass()).toContain('demo')
  })

  it('opens from the home card without a request', async () => {
    await boot('')

    byClass(root, 'home-card')[0]!.click()
    await settle()

    expect(location.hash).toBe('#/demo')
    expect(screenClass()).toContain('demo')
  })

  it('has the login entry in the top bar and no exit button in the screen', async () => {
    await boot('#/demo')

    const bar = byClass(root, 'topbar')[0]!
    expect(buttons(byClass(bar, 'topbar-actions')[0]!).map((button) => button.textContent)).toEqual([
      '후리가나',
      '로그인',
    ])
    expect(byClass(root, 'demo-exit')).toEqual([])
  })

  it('continues from the saved progress without a request', async () => {
    let saved = initialProgress(DEMO_FIXTURE)
    for (let i = 0; i < 3; i += 1) saved = advance(DEMO_FIXTURE, saved)
    vi.stubGlobal('localStorage', memoryStorage({ 'nc.demo.v1': JSON.stringify(saved) }))

    await boot('#/demo')

    expect(screenClass()).toContain('demo')
    expect(byClass(root, 'sentence')[0]!.getAttribute('aria-label')).toBe(
      DEMO_SENTENCES[saved.position]!.presentation.japanese,
    )
    expect(byClass(root, 'demo-progress')[0]!.textContent).toBe(`${saved.seen} / ${DEMO_SENTENCES.length}`)
  })
})

describe('leaving the demo', () => {
  it('goes home from the app name without a request', async () => {
    await boot('#/demo')

    press('Nihongo Context')
    await settle()

    expect(location.hash).toBe('#/')
    expect(screenClass()).toContain('home')
  })

  it('goes home with the back button without a request', async () => {
    await boot('')
    byClass(root, 'home-card')[0]!.click()
    await settle()

    history.back()
    await settle()

    expect(location.hash).toBe('')
    expect(screenClass()).toContain('home')
  })
})
