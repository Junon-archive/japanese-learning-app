/**
 * 세션 종료 선택지.
 *
 * **연장 버튼 문구에 숫자가 없어야 한다.** `extra_session_minutes`는 config이고 어떤
 * 응답에도 실려 오지 않는다. `+5분 더`라고 적으면 config를 바꾼 배포에서 버튼이 거짓을
 * 말하며, 그 거짓은 화면상 아무 이상 없이 보인다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderSessionEndChoice } from '../../src/ui/session-end'
import type { FakeElement } from './fake-dom'
import { fakeDocument } from './fake-dom'

function buttons(node: FakeElement): FakeElement[] {
  return node.children.flatMap((child) =>
    child.tagName === 'BUTTON' ? [child] : buttons(child),
  )
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderSessionEndChoice', () => {
  it('offers finish and extend, and nothing else', () => {
    const choice = renderSessionEndChoice({
      onFinish: () => {},
      onExtend: () => {},
    }) as unknown as FakeElement

    const labels = buttons(choice).map((button) => button.textContent)
    expect(labels).toHaveLength(2)
    expect(labels[0]).toBe('오늘 학습 완료')
  })

  it('puts no number in the extend label', () => {
    const choice = renderSessionEndChoice({
      onFinish: () => {},
      onExtend: () => {},
    }) as unknown as FakeElement

    const extend = buttons(choice)[1]
    expect(extend?.textContent).not.toMatch(/\d/)
  })

  it('uses the wording the spec confirmed for extend', () => {
    // 03_UI_UX_SPEC.md의 `Session End`. v0.2의 `+5분 더`는 철회됐고 문구가 확정됐다.
    const choice = renderSessionEndChoice({
      onFinish: () => {},
      onExtend: () => {},
    }) as unknown as FakeElement

    expect(buttons(choice)[1]?.textContent).toBe('더 학습하기')
  })

  it('calls back exactly once per tap', () => {
    const finished: string[] = []
    const choice = renderSessionEndChoice({
      onFinish: () => finished.push('finish'),
      onExtend: () => finished.push('extend'),
    }) as unknown as FakeElement

    buttons(choice)[0]?.click()
    buttons(choice)[1]?.click()

    expect(finished).toEqual(['finish', 'extend'])
  })
})
