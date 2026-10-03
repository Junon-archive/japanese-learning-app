/**
 * 세션 종료 선택지.
 *
 * **연장 버튼 문구에 숫자가 없어야 한다.** `extra_session_minutes`는 config이고 어떤
 * 응답에도 실려 오지 않는다. `+5분 더`라고 적으면 config를 바꾼 배포에서 버튼이 거짓을
 * 말하며, 그 거짓은 화면상 아무 이상 없이 보인다.
 *
 * MVP-03 운영 보강(2026-10-03): **도달 전에도 세션을 끝낼 수 있다.** 이 파일은 두 조각을
 * 각각 본다 --- 도달 전의 `renderFinishButton`(버튼 하나)과 도달 후의
 * `renderSessionEndChoice`(안내 + 버튼 둘). 어느 쪽을 언제 그리는지는 `ui/study.ts`의 일이고
 * `study.test.ts`가 본다(`03_UI_UX_SPEC.md`의 `도달 전과 도달 후`, 합격 기준 32).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderFinishButton, renderSessionEndChoice, renderSessionFinished } from '../../src/ui/session-end'
import type { FakeElement } from './fake-dom'
import { fakeDocument, flatText } from './fake-dom'

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

describe('renderFinishButton (도달 전)', () => {
  function finishButton(taps: string[] = []): FakeElement {
    return renderFinishButton(() => {
      taps.push('finish')
    }) as unknown as FakeElement
  }

  it('is a single secondary button and nothing else', () => {
    const button = finishButton()

    expect(button.tagName).toBe('BUTTON')
    expect(button.type).toBe('button')
    // 오탭을 자리와 위계로 막는다 --- `다음 문장`(primary)과 같은 위계로 그리지 않는다.
    expect(button.className.split(' ')).toContain('secondary')
    expect(button.className.split(' ')).not.toContain('primary')
    expect(button.children).toEqual([])
  })

  it('uses the very same label as the reached block (한 동작에 두 이름을 두지 않는다)', () => {
    const reached = renderSessionEndChoice({
      onFinish: () => {},
      onExtend: () => {},
    }) as unknown as FakeElement

    expect(finishButton().textContent).toBe(buttons(reached)[0]!.textContent)
  })

  it('puts no number in the label', () => {
    // `default_session_minutes`·`extra_session_minutes`를 문구에 적지 않는다는 기존 규칙 그대로다.
    expect(finishButton().textContent).not.toMatch(/\d/)
  })

  it('carries neither the reached wording nor 더 학습하기', () => {
    // 둘 다 "도달했다"는 뜻이라 도달 전에는 거짓이다.
    const button = finishButton()

    expect(flatText(button)).not.toContain('오늘 목표한 시간을 채웠어요.')
    expect(flatText(button)).not.toContain('더 학습하기')
  })

  it('calls back once per tap, with no confirmation step', () => {
    const taps: string[] = []
    const button = finishButton(taps)

    button.click()

    // 한 번 누르면 바로 `/finish`다. 2단계 누르기도 확인 대화상자도 없다.
    expect(taps).toEqual(['finish'])
    expect(button.children).toEqual([])
  })
})

describe('session end wording', () => {
  it('says the goal time is reached', () => {
    const choice = renderSessionEndChoice({ onFinish: () => {}, onExtend: () => {} }) as unknown as FakeElement

    expect(choice.children[0]!.textContent).toBe('오늘 목표한 시간을 채웠어요.')
  })

  it('ends with one line of completion and one line of study time', () => {
    const finished = renderSessionFinished({
      session_id: 1,
      started_at: '2026-09-13T09:00:00Z',
      last_activity_at: '2026-09-13T09:12:00Z',
      ended_at: '2026-09-13T09:12:00Z',
      active_seconds: 725,
      target_minutes: 12,
      extended_minutes: 0,
    }) as unknown as FakeElement

    expect(finished.children.map((child) => child.textContent)).toEqual(['오늘 학습을 마쳤어요.', '학습 시간 12분'])
  })
})
