/**
 * 바텀시트(`openSheet`).
 *
 * 갈리는 지점: **닫으면 조작이 즉시 가능하다.** 가림막 뒤 화면의 `inert` 해제와 포커스 복귀는
 * `transitionend`를 기다리지 않는다. 이 스텁에서는 `transitionend`가 저절로 오지 않으므로,
 * 그 이벤트 없이 단정하는 것이 곧 "이벤트가 오지 않는 환경에서도 막히지 않는다"의 확인이다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SheetHandle } from '../../src/ui/sheet'
import { openSheet } from '../../src/ui/sheet'
import type { FakeDocument, FakeElement } from './fake-dom'
import { buttons, createFakeElement, descendants, fakeDocument } from './fake-dom'

let doc: FakeDocument
let container: FakeElement
let token: FakeElement
let closes: number

function open(options: { body?: FakeElement; returnFocusTo?: FakeElement | null } = {}): {
  handle: SheetHandle
  scrim: FakeElement
  sheet: FakeElement
} {
  const handle = openSheet({
    container: container as unknown as HTMLElement,
    title: '표현 설명',
    body: (options.body ?? createFakeElement('section')) as unknown as HTMLElement,
    returnFocusTo: (options.returnFocusTo === undefined
      ? token
      : options.returnFocusTo) as unknown as HTMLElement | null,
    onClose: () => {
      closes += 1
    },
  })
  const scrim = container.children.at(-1)!
  const sheet = descendants(scrim).find((node) => node.getAttribute('role') === 'dialog')!
  return { handle, scrim, sheet }
}

function closeButton(sheet: FakeElement): FakeElement {
  return buttons(sheet).find((button) => button.textContent === '닫기')!
}

beforeEach(() => {
  doc = fakeDocument()
  vi.stubGlobal('document', doc)
  closes = 0
  container = createFakeElement('main')
  const sentence = createFakeElement('p')
  token = createFakeElement('button')
  sentence.append(token)
  container.append(sentence)
  doc.body.append(container)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('openSheet', () => {
  it('is a modal dialog labelled by its title, inside the screen container', () => {
    const body = createFakeElement('section')
    const { scrim, sheet } = open({ body })

    expect(scrim.parentNode).toBe(container)
    expect(sheet.getAttribute('aria-modal')).toBe('true')
    const titleId = sheet.getAttribute('aria-labelledby')
    const title = descendants(sheet).find((node) => node.getAttribute('id') === titleId)
    expect(titleId).not.toBeNull()
    expect(title?.textContent).toBe('표현 설명')
    expect(descendants(sheet)).toContain(body)
    expect(closeButton(sheet)).toBeDefined()
  })

  it('gives each sheet its own title id', () => {
    const first = open().sheet.getAttribute('aria-labelledby')
    const second = open().sheet.getAttribute('aria-labelledby')

    expect(first).not.toBe(second)
  })

  it('moves focus to the title and makes the screen behind inert', () => {
    const { scrim, sheet } = open()

    const titleId = sheet.getAttribute('aria-labelledby')
    expect(doc.activeElement?.getAttribute('id')).toBe(titleId)
    expect(container.children[0]?.inert).toBe(true)
    expect(scrim.inert).toBe(false)
  })

  it.each([
    ['the close button', (sheet: FakeElement) => closeButton(sheet).click()],
    ['the scrim', (_sheet: FakeElement, scrim: FakeElement) => scrim.click()],
    ['Escape', (sheet: FakeElement) => sheet.fire('keydown', { key: 'Escape' })],
  ])('closes with %s and is usable at once without transitionend', (_name, act) => {
    const { scrim, sheet } = open()

    act(sheet, scrim)

    expect(closes).toBe(1)
    expect(container.children[0]?.inert).toBe(false)
    expect(doc.activeElement).toBe(token)
    expect(scrim.inert).toBe(true)
    expect(scrim.classList.contains('is-closing')).toBe(true)
    // 시각적 숨김은 아직이다. 그래도 뒤 화면을 누를 수 있다.
    expect(scrim.parentNode).toBe(container)
    token.focus()
    expect(doc.activeElement).toBe(token)
  })

  it('does not close on clicks or other keys inside the sheet', () => {
    const body = createFakeElement('section')
    const inside = createFakeElement('button')
    body.append(inside)
    const { scrim, sheet } = open({ body })

    inside.click()
    sheet.fire('keydown', { key: 'Enter' })

    expect(closes).toBe(0)
    expect(scrim.classList.contains('is-closing')).toBe(false)
    expect(container.children[0]?.inert).toBe(true)
  })

  it('closes once however many times it is asked', () => {
    const { handle, scrim, sheet } = open()

    handle.close()
    closeButton(sheet).click()
    scrim.click()
    handle.close()

    expect(closes).toBe(1)
  })

  it('is removed only on the scrim transitionend after closing', () => {
    const { handle, scrim, sheet } = open()

    // 올라오는 움직임의 끝, 시트 본체에서 올라온 끝은 떼는 신호가 아니다.
    scrim.fire('transitionend')
    expect(scrim.parentNode).toBe(container)
    handle.close()
    sheet.fire('transitionend')
    expect(scrim.parentNode).toBe(container)

    scrim.fire('transitionend')
    expect(container.children).not.toContain(scrim)
  })

  it('leaves elements that were already inert as they were', () => {
    const disabledArea = createFakeElement('div')
    disabledArea.inert = true
    container.append(disabledArea)
    const { handle } = open()

    handle.close()

    expect(disabledArea.inert).toBe(true)
    expect(container.children[0]?.inert).toBe(false)
  })

  it('works without a focus target', () => {
    const { handle } = open({ returnFocusTo: null })

    handle.close()

    expect(closes).toBe(1)
    expect(container.children[0]?.inert).toBe(false)
  })
})
