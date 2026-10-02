/**
 * 공개 route(`src/routes.ts`). `03_UI_UX_SPEC.md`의 `화면 이동`, ADR-022 결정 1·5.
 *
 * 갈리는 지점:
 *
 * -   `''`와 `#/`는 선택 홈, `#/demo`는 Demo, 모르는 hash는 선택 홈이고 URL이 `#/`로 바뀐다(state는 null).
 * -   하위 경로는 그것을 허용한다고 선언한 route만 받는다(`#/kana`).
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
  vi.doUnmock('../../src/demo/ja/demo')
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('resolveHash', () => {
  const KANA: PublicRoute = {
    prefix: '#/ja/kana',
    load: () => Promise.reject(new Error('not loaded in this test')),
    loadFailure: '',
    acceptsSubpath: true,
    language: 'ja',
  }
  const ROUTES = [KANA, ...PUBLIC_ROUTES]

  it('reads an empty hash and #/ as the home', () => {
    expect(resolveHash('')).toEqual({ kind: 'home' })
    expect(resolveHash('#/')).toEqual({ kind: 'home' })
  })

  it('finds the demo route without a subpath', () => {
    const resolved = resolveHash('#/ja/demo')

    expect(resolved.kind).toBe('route')
    expect(resolved.kind === 'route' && resolved.route.prefix).toBe('#/ja/demo')
    expect(resolved.kind === 'route' && resolved.subpath).toBe('')
  })

  it('treats a subpath on a route that does not accept one as unknown', () => {
    expect(resolveHash('#/ja/demo/anything')).toEqual({ kind: 'unknown' })
    expect(resolveHash('#/ja/demox')).toEqual({ kind: 'unknown' })
  })

  it('passes the subpath to a route that accepts one', () => {
    for (const [hash, subpath] of [
      ['#/ja/kana', ''],
      ['#/ja/kana/hiragana', 'hiragana'],
    ] as const) {
      const resolved = resolveHash(hash, ROUTES)
      expect(resolved.kind === 'route' && resolved.route).toBe(KANA)
      expect(resolved.kind === 'route' && resolved.subpath).toBe(subpath)
    }
    expect(resolveHash('#/ja/kanax', ROUTES)).toEqual({ kind: 'unknown' })
  })

  it('finds the registered kana route with and without a subpath', () => {
    for (const [hash, subpath] of [
      ['#/ja/kana', ''],
      ['#/ja/kana/hiragana', 'hiragana'],
    ] as const) {
      const resolved = resolveHash(hash)
      expect(resolved.kind === 'route' && resolved.route.prefix).toBe('#/ja/kana')
      expect(resolved.kind === 'route' && resolved.subpath).toBe(subpath)
    }
    expect(resolveHash('#/ja/kanax')).toEqual({ kind: 'unknown' })
    expect(resolveHash('#/unknown')).toEqual({ kind: 'unknown' })
  })

  it('finds the ja and en home routes, each with its own language and no subpath', () => {
    const ja = resolveHash('#/ja')
    expect(ja.kind === 'route' && ja.route.prefix).toBe('#/ja')
    expect(ja.kind === 'route' && ja.route.language).toBe('ja')
    expect(ja.kind === 'route' && ja.subpath).toBe('')

    const en = resolveHash('#/en')
    expect(en.kind === 'route' && en.route.prefix).toBe('#/en')
    expect(en.kind === 'route' && en.route.language).toBe('en')

    // '#/ja'는 하위 경로를 받지 않는다. '#/ja/demo'는 그 자리의 route와 따로 매칭된다.
    expect(resolveHash('#/ja/demo').kind === 'route' && resolveHash('#/ja/demo').route.language).toBe('ja')
    expect(resolveHash('#/en/demo').kind === 'route' && resolveHash('#/en/demo').route.language).toBe('en')
  })

  it('treats a subpath on the ja or en home as unknown', () => {
    expect(resolveHash('#/ja/anything')).toEqual({ kind: 'unknown' })
    expect(resolveHash('#/en/anything')).toEqual({ kind: 'unknown' })
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

  it('shows the demo for #/ja/demo', async () => {
    await boot('#/ja/demo')

    expect(screen().className).toContain('demo')
  })

  it('shows the ja home for #/ja and the en home for #/en, each statically (no dynamic import)', async () => {
    await boot('#/ja')
    expect(screen().className).toContain('home')
    expect(screen().className).toContain('ja-home')

    await boot('#/en')
    expect(screen().className).toContain('home')
    expect(screen().className).toContain('en-home')
  })

  it('shows the en demo for #/en/demo', async () => {
    await boot('#/en/demo')

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

    // 언어 선택 홈 카드 1(일본어) -> #/ja.
    byClass(root, 'home-card')[0]!.click()
    await settle()
    expect(location.hash).toBe('#/ja')
    expect(screen().className).toContain('home')

    // 일본어 홈 카드 1(체험) -> #/ja/demo.
    byClass(root, 'home-card')[0]!.click()
    await settle()
    expect(location.hash).toBe('#/ja/demo')
    expect(screen().className).toContain('demo')

    history.back()
    await settle()
    expect(location.hash).toBe('#/ja')
    expect(screen().className).toContain('home')

    history.back()
    await settle()
    expect(location.hash).toBe('')
    expect(screen().className).toContain('home')
  })

  it('does not let a late route load cover the screen the user went back to', async () => {
    await boot('#/ja')

    location.hash = '#/ja/demo'
    await Promise.resolve()
    history.back()
    await settle()

    expect(screen().className).toContain('home')
  })

  it('redirects the legacy #/demo and #/kana hashes to the ja routes in one step', async () => {
    await boot('#/demo')
    expect(browser.replaceStateCalls).toEqual([[null, '', '#/ja/demo']])
    expect(location.hash).toBe('#/ja/demo')
    expect(screen().className).toContain('demo')

    await boot('#/kana')
    expect(browser.replaceStateCalls).toEqual([[null, '', '#/ja/kana']])
    expect(location.hash).toBe('#/ja/kana')
    expect(screen().className).toContain('kana')

    await boot('#/kana/hiragana')
    expect(browser.replaceStateCalls).toEqual([[null, '', '#/ja/kana/hiragana']])
    expect(location.hash).toBe('#/ja/kana/hiragana')
    expect(screen().className).toContain('kana')
  })

  it('shows the route failure message inline when the route fails to load', async () => {
    vi.doMock('../../src/demo/ja/demo', () => {
      throw new Error('chunk load failed')
    })
    await boot('#/ja/demo')

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
