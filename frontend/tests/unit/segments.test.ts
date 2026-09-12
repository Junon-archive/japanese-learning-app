/**
 * `render_segments` 렌더링의 불변식.
 *
 * fixture에 **서로게이트 페어(𠮟)와 결합 문자(ヘ+゜, く+゛)** 가 들어 있다. 이것이 이
 * 테스트의 핵심이다 --- frontend가 offset을 다시 계산하기 시작하면 JavaScript 문자열이
 * UTF-16이기 때문에 그런 문자가 있는 문장에서만 경계가 어긋난다. 평범한 문장으로만
 * 테스트하면 그 회귀가 통과한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { joinSegments, renderSentence } from '../../src/ui/segments'
import type { RenderSegment } from '../../src/types'
import type { FakeElement } from './fake-dom'
import { fakeDocument, isTappable } from './fake-dom'

// 𠮟 = U+20B9F (서로게이트 페어), ヘ + U+309A, く + U+3099 (결합 문자)
const SEGMENTS: RenderSegment[] = [
  { text: '𠮟られて', sentence_item_id: 7001 },
  { text: 'も', sentence_item_id: null },
  { text: 'ページ', sentence_item_id: 7002 },
  { text: 'を', sentence_item_id: null },
  { text: 'めぐった', sentence_item_id: 7003 },
  { text: '。', sentence_item_id: null },
]

/** 서버가 같은 payload에 함께 싣는 `japanese`. */
const JAPANESE = '𠮟られてもページをめぐった。'

/** 스텁 document 위에서 만든 노드다. 실제 `HTMLElement`가 아니므로 여기서 좁힌다. */
function render(onTapItem: (sentenceItemId: number) => void = () => {}): FakeElement {
  return renderSentence(SEGMENTS, onTapItem) as unknown as FakeElement
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('joinSegments', () => {
  it('reproduces `japanese` exactly', () => {
    expect(joinSegments(SEGMENTS)).toBe(JAPANESE)
  })

  it('covers a sentence whose UTF-16 length differs from its code point count', () => {
    // 이 차이가 곧 "프론트에서 offset을 계산하면 깨진다"의 이유다.
    expect(JAPANESE.length).not.toBe([...JAPANESE].length)
  })
})

describe('renderSentence', () => {
  it('renders one span per segment, in order, with the text untouched', () => {
    const sentence = render()

    expect(sentence.children).toHaveLength(SEGMENTS.length)
    expect(sentence.children.map((child) => child.textContent)).toEqual(
      SEGMENTS.map((segment) => segment.text),
    )
    // 이어 붙인 결과가 다시 `japanese`다 --- 자르거나 정규화하지 않았다는 뜻이다.
    expect(sentence.children.map((child) => child.textContent).join('')).toBe(JAPANESE)
    expect(sentence.getAttribute('aria-label')).toBe(JAPANESE)
  })

  it('makes exactly the segments with a sentence_item_id tappable', () => {
    const sentence = render()

    const tappable = sentence.children.filter(isTappable)
    expect(tappable).toHaveLength(
      SEGMENTS.filter((segment) => segment.sentence_item_id !== null).length,
    )
    expect(tappable.map((child) => child.textContent)).toEqual(
      SEGMENTS.filter((segment) => segment.sentence_item_id !== null).map(
        (segment) => segment.text,
      ),
    )
  })

  it('styles every tappable span identically', () => {
    // target과 incidental을 구분하면 그 문장의 평가 대상이 드러난다
    // (03_UI_UX_SPEC.md의 `tappable span 표시`).
    const sentence = render()

    const classNames = new Set(sentence.children.filter(isTappable).map((c) => c.className))
    expect(classNames.size).toBe(1)
  })

  it('passes the segment sentence_item_id to the tap handler', () => {
    const tapped: number[] = []
    const sentence = render((id) => tapped.push(id))

    for (const child of sentence.children.filter(isTappable)) child.click()

    expect(tapped).toEqual([7001, 7002, 7003])
  })

  it('does not tap through non-tappable segments', () => {
    const tapped: number[] = []
    const sentence = render((id) => tapped.push(id))

    for (const child of sentence.children.filter((child) => !isTappable(child))) child.click()

    expect(tapped).toEqual([])
  })
})
