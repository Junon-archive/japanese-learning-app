/**
 * 공개 route(`src/routes.ts`). `03_UI_UX_SPEC.md`의 `화면 이동`, ADR-022 결정 1·5.
 *
 * 갈리는 지점:
 *
 * -   `''`와 `#/`는 선택 홈, `#/demo`는 Demo, 모르는 hash는 선택 홈이고 URL이 `#/`로 바뀐다(state는 null).
 * -   하위 경로는 그것을 허용한다고 선언한 route만 받는다(`#/kana`는 Wave 3에서 등록된다).
 * -   `navigate`가 같은 hash에서도 화면을 다시 적용한다(hashchange가 오지 않으므로).
 * -   뒤로 가기(`hashchange`)로 공개 화면 사이를 오가고, 떠난 route의 늦은 동적 import는 화면을 덮지 못한다.
 * -   `hashchange` 리스너는 `routes.ts` 한 곳이다. 요청은 0건이다.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PublicRoute } from '../../src/routes'
import { PUBLIC_ROUTES, resolveHash } from '../../src/routes'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeBrowser, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeBrowser, fakeDocument, flatText } from './fake-dom'

const SRC = fileURLToPath(new URL('../../src', import.meta.url))

const fetchMock = vi.fn<typeof fetch>(() => {
  throw new Error('public routes must not make requests')
})

let root: FakeElement
let browser: FakeBrowser

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
  browser = fakeBrowser(hash)
  vi.stubGlobal('location', browser.location)
  vi.stubGlobal('history', browser.history)
  vi.stubGlobal('window', browser.window)
  vi.resetModules()
  await import('../../src/main')
  await settle()
}

function screen(): FakeElement {
  return root.children[0]!
}

function byText(text: string): FakeElement {
  const found = buttons(root).find((button) => button.textContent === text)
  expect(found, `no button ${text}`).toBeDefined()
  return found!
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

beforeEach(() => {
  fetchMock.mockClear()
  root = createFakeElement('div')
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  expect(fetchMock).not.toHaveBeenCalled()
  vi.doUnmock('../../src/demo/demo')
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('resolveHash', () => {
  const KANA: PublicRoute = {
    prefix: '#/kana',
    load: () => Promise.reject(new Error('not loaded in this test')),
    loadFailure: '',
    acceptsSubpath: true,
  }
  const ROUTES = [...PUBLIC_ROUTES, KANA]

  it('reads an empty hash and #/ as the home', () => {
    expect(resolveHash('')).toEqual({ kind: 'home' })
    expect(resolveHash('#/')).toEqual({ kind: 'home' })
  })

  it('finds the demo route without a subpath', () => {
    const resolved = resolveHash('#/demo')

    expect(resolved.kind).toBe('route')
    expect(resolved.kind === 'route' && resolved.route.prefix).toBe('#/demo')
    expect(resolved.kind === 'route' && resolved.subpath).toBe('')
  })

  it('treats a subpath on a route that does not accept one as unknown', () => {
    expect(resolveHash('#/demo/anything')).toEqual({ kind: 'unknown' })
    expect(resolveHash('#/demox')).toEqual({ kind: 'unknown' })
  })

  it('passes the subpath to a route that accepts one', () => {
    for (const [hash, subpath] of [
      ['#/kana', ''],
      ['#/kana/hiragana', 'hiragana'],
    ] as const) {
      const resolved = resolveHash(hash, ROUTES)
      expect(resolved.kind === 'route' && resolved.route).toBe(KANA)
      expect(resolved.kind === 'route' && resolved.subpath).toBe(subpath)
    }
    expect(resolveHash('#/kanax', ROUTES)).toEqual({ kind: 'unknown' })
  })

  it('does not know #/kana before the kana route is registered', () => {
    expect(resolveHash('#/kana')).toEqual({ kind: 'unknown' })
    expect(resolveHash('#/unknown')).toEqual({ kind: 'unknown' })
  })
})

describe('router', () => {
  it('shows the home for an empty hash and #/ without touching the url', async () => {
    await boot('')
    expect(screen().className).toContain('home')

    await boot('#/')
    expect(screen().className).toContain('home')
    expect(browser.replaceStateCalls).toEqual([])
  })

  it('shows the home for an unknown hash and rewrites the url to #/ with a null state', async () => {
    await boot('#/unknown')

    expect(screen().className).toContain('home')
    expect(browser.replaceStateCalls).toEqual([[null, '', '#/']])
    expect(location.hash).toBe('#/')
    expect(browser.entries()).toEqual(['#/'])
  })

  it('shows the demo for #/demo', async () => {
    await boot('#/demo')

    expect(screen().className).toContain('demo')
  })

  it('re-applies the route when navigating to the hash it is already on', async () => {
    await boot('')
    const first = screen()

    // 앱 이름 -> navigate('#/'). ''와 '#/'는 같은 홈이라 hash가 바뀌지 않는다.
    byText('Nihongo Context').click()
    await settle()

    expect(screen()).not.toBe(first)
    expect(screen().className).toContain('home')
    expect(browser.entries()).toEqual([''])
  })

  it('goes back and forth between public screens with the browser history', async () => {
    await boot('')

    byClass(root, 'home-card')[0]!.click()
    await settle()
    expect(location.hash).toBe('#/demo')
    expect(screen().className).toContain('demo')

    history.back()
    await settle()
    expect(screen().className).toContain('home')
  })

  it('does not let a late route load cover the screen the user went back to', async () => {
    await boot('')

    location.hash = '#/demo'
    await Promise.resolve()
    history.back()
    await settle()

    expect(screen().className).toContain('home')
  })

  it('shows the route failure message inline when the route fails to load', async () => {
    vi.doMock('../../src/demo/demo', () => {
      throw new Error('chunk load failed')
    })
    await boot('#/demo')

    const notice = byClass(root, 'notice')[0]!
    expect(flatText(notice)).toContain(MESSAGES.demoLoadFailed)
    expect(buttons(notice)).toEqual([])
    expect(buttons(byClass(root, 'topbar')[0]!).map((button) => button.textContent)).toEqual([
      'Nihongo Context',
      '로그인',
    ])
  })

  it('listens to hashchange once and nowhere else', async () => {
    await boot('')

    expect(browser.listenerTypes()).toEqual(['hashchange'])
    const listeners = walk(SRC)
      .filter((path) => /addEventListener\s*\(\s*['"]hashchange/.test(readFileSync(path, 'utf8')))
      .map((path) => path.slice(SRC.length + 1))
    expect(listeners).toEqual(['routes.ts'])
  })
})
