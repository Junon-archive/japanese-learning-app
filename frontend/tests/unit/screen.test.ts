/**
 * 화면 교체(`showScreen`)와 토스트(`showToast`).
 *
 * `showScreen`에서 갈리는 지점은 `signal`이다: **떠난 화면의 늦은 응답은 지금 화면을 바꾸지
 * 못한다**(ADR-022 결정 1). 그 밖에는 즉시 교체, 진입 class, 맨 위 스크롤, 제목 포커스.
 *
 * 토스트는 정보성 안내만이고 4초 뒤 사라진다. `#app` 밖(body)에 붙는다. 이 스텁에서는
 * `transitionend`가 저절로 오지 않으므로, 사라지기 시작하는 것(class)과 DOM에서 떼는 것을
 * 나눠 본다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { showToast } from '../../src/ui/notice'
import { showScreen } from '../../src/ui/screen'
import type { FakeDocument, FakeElement } from './fake-dom'
import { createFakeElement, fakeDocument } from './fake-dom'

let doc: FakeDocument

function el(tagName: string): FakeElement {
  return createFakeElement(tagName)
}

function show(root: FakeElement, screen: FakeElement, signal: AbortSignal): void {
  showScreen(root as unknown as HTMLElement, screen as unknown as HTMLElement, signal)
}

beforeEach(() => {
  doc = fakeDocument()
  vi.stubGlobal('document', doc)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('showScreen', () => {
  it('does nothing once the signal is aborted', () => {
    const root = el('div')
    const current = el('main')
    root.append(current)
    doc.documentElement.scrollTop = 300
    const controller = new AbortController()
    controller.abort()

    const late = el('main')
    const title = el('h1')
    late.append(title)
    show(root, late, controller.signal)

    expect(root.children).toEqual([current])
    expect(late.className).toBe('')
    expect(doc.documentElement.scrollTop).toBe(300)
    expect(doc.activeElement).toBeNull()
  })

  it('replaces the screen at once, scrolls to top and focuses the title', () => {
    const root = el('div')
    const previous = el('main')
    root.append(previous)
    doc.documentElement.scrollTop = 300

    const screen = el('main')
    screen.className = 'screen'
    const body = el('section')
    const title = el('h1')
    body.append(title)
    screen.append(body)
    show(root, screen, new AbortController().signal)

    expect(root.children).toEqual([screen])
    expect(previous.parentNode).toBeNull()
    expect(screen.classList.contains('screen')).toBe(true)
    expect(screen.classList.contains('screen-enter')).toBe(true)
    expect(doc.documentElement.scrollTop).toBe(0)
    expect(title.getAttribute('tabindex')).toBe('-1')
    expect(doc.activeElement).toBe(title)
  })

  it('keeps an existing tabindex and leaves focus alone without a title', () => {
    const root = el('div')
    const withTitle = el('main')
    const title = el('h1')
    title.setAttribute('tabindex', '0')
    withTitle.append(title)
    show(root, withTitle, new AbortController().signal)
    expect(title.getAttribute('tabindex')).toBe('0')

    const untitled = el('main')
    untitled.append(el('p'))
    show(root, untitled, new AbortController().signal)

    expect(root.children).toEqual([untitled])
    expect(doc.activeElement).toBe(title)
  })
})

describe('showToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  function toasts(): FakeElement[] {
    return doc.body.children.filter((child) => child.classList.contains('toast'))
  }

  it('appends a status message to body, outside the app root', () => {
    showToast('이어서 학습해요.')

    const [toast] = toasts()
    expect(toasts()).toHaveLength(1)
    expect(toast?.getAttribute('role')).toBe('status')
    expect(toast?.textContent).toBe('이어서 학습해요.')
    expect(toast?.parentNode).toBe(doc.body)
  })

  it('starts leaving after 4 seconds and is removed on its own transitionend', () => {
    showToast('기록했어요')
    const toast = toasts()[0]!

    vi.advanceTimersByTime(3999)
    expect(toast.classList.contains('is-leaving')).toBe(false)
    vi.advanceTimersByTime(1)
    expect(toast.classList.contains('is-leaving')).toBe(true)

    // 자식에서 올라온 transitionend는 이 토스트의 것이 아니다.
    const child = el('span')
    toast.append(child)
    child.fire('transitionend')
    expect(toast.parentNode).toBe(doc.body)

    toast.fire('transitionend')
    expect(toasts()).toEqual([])
  })

  it('is not removed by a transitionend before it starts leaving', () => {
    showToast('기록했어요')
    const toast = toasts()[0]!

    // 올라오는 움직임이 끝났을 뿐이다.
    toast.fire('transitionend')

    expect(toast.parentNode).toBe(doc.body)
  })

  it('starts leaving right away when tapped', () => {
    showToast('진도를 초기화했어요.')
    const toast = toasts()[0]!

    toast.click()
    expect(toast.classList.contains('is-leaving')).toBe(true)

    vi.advanceTimersByTime(4000)
    toast.fire('transitionend')
    expect(toasts()).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shows one toast at a time', () => {
    showToast('첫 안내')
    const first = toasts()[0]!

    showToast('다음 안내')

    expect(first.parentNode).toBeNull()
    expect(toasts().map((toast) => toast.textContent)).toEqual(['다음 안내'])
  })
})
