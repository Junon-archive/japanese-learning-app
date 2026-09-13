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
import type { FakeElement, FakeNode } from './fake-dom'
import { descendants, fakeDocument, isTappable, textWithoutRt } from './fake-dom'

// 𠮟 = U+20B9F (서로게이트 페어), ヘ + U+309A, く + U+3099 (결합 문자)
const SEGMENTS: RenderSegment[] = [
  { text: '𠮟られて', sentence_item_id: 7001, ruby: [] },
  { text: 'も', sentence_item_id: null, ruby: [] },
  { text: 'ページ', sentence_item_id: 7002, ruby: [] },
  { text: 'を', sentence_item_id: null, ruby: [] },
  { text: 'めぐった', sentence_item_id: 7003, ruby: [] },
  { text: '。', sentence_item_id: null, ruby: [] },
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

/**
 * 후리가나(`render_segments[].ruby`, 05_API_SPEC.md R1~R7, 불변식 17).
 *
 * 서로게이트 페어(𠮟)에 읽기가 달린 tappable, ruby가 섞인 비 tappable, ruby가 빈 tappable이 한 문장에 있다.
 * 읽기를 text에 붙여 그리거나(`<rt>` 없이) 토글 상태에 따라 `<rt>`를 빼면 여기가 빨개진다.
 */
const RUBY_SEGMENTS: RenderSegment[] = [
  {
    text: 'この仕事、田中さんに',
    sentence_item_id: null,
    ruby: [
      { text: 'この', reading: null },
      { text: '仕事', reading: 'しごと' },
      { text: '、', reading: null },
      { text: '田中', reading: 'たなか' },
      { text: 'さんに', reading: null },
    ],
  },
  {
    text: '任せ',
    sentence_item_id: 5511,
    ruby: [
      { text: '任', reading: 'まか' },
      { text: 'せ', reading: null },
    ],
  },
  { text: 'てもいい', sentence_item_id: 5512, ruby: [] },
  { text: 'と', sentence_item_id: null, ruby: [] },
  {
    text: '𠮟られて',
    sentence_item_id: 5513,
    ruby: [
      { text: '𠮟', reading: 'しか' },
      { text: 'られて', reading: null },
    ],
  },
  { text: '。', sentence_item_id: null, ruby: [] },
]

const RUBY_JAPANESE = 'この仕事、田中さんに任せてもいいと𠮟られて。'

const READINGS = RUBY_SEGMENTS.flatMap((segment) =>
  segment.ruby.flatMap((part) => (part.reading === null ? [] : [part.reading])),
)

function renderRuby(onTapItem: (sentenceItemId: number) => void = () => {}): FakeElement {
  return renderSentence(RUBY_SEGMENTS, onTapItem) as unknown as FakeElement
}

/** 같은 문장에서 ruby만 비운 것. 버튼·텍스트가 ruby 유무와 무관한지 비교하는 기준이다. */
function renderWithoutRuby(): FakeElement {
  const bare = RUBY_SEGMENTS.map((segment) => ({ ...segment, ruby: [] }))
  return renderSentence(bare, () => {}) as unknown as FakeElement
}

function rtOf(sentence: FakeElement): FakeElement[] {
  return descendants(sentence).filter((node) => node.tagName === 'RT')
}

/** 노드 모양: 텍스트 노드는 그 문자열, `<ruby>`는 [text, reading], 그 밖의 요소는 [태그]. */
function shape(node: FakeNode): string | string[] {
  if (node.nodeType === 3) return node.textContent
  if (node.tagName !== 'RUBY') return [node.tagName]
  const rt = rtOf(node)
  expect(rt).toHaveLength(1)
  expect(node.childNodes[node.childNodes.length - 1]).toBe(rt[0])
  return [textWithoutRt(node), rt[0]!.textContent]
}

describe('renderSentence with ruby', () => {
  it('keeps the sentence text without rt equal to japanese, and the aria-label free of readings', () => {
    const sentence = renderRuby()

    expect(joinSegments(RUBY_SEGMENTS)).toBe(RUBY_JAPANESE)
    expect(textWithoutRt(sentence)).toBe(RUBY_JAPANESE)
    expect(sentence.getAttribute('aria-label')).toBe(RUBY_JAPANESE)
    for (const reading of READINGS) {
      expect(sentence.getAttribute('aria-label')).not.toContain(reading)
    }
  })

  it('draws each part: a text node without a reading, <ruby>text<rt>reading</rt></ruby> with one', () => {
    const sentence = renderRuby()

    expect(sentence.children).toHaveLength(RUBY_SEGMENTS.length)
    RUBY_SEGMENTS.forEach((segment, index) => {
      const child = sentence.children[index]!
      if (segment.ruby.length === 0) {
        // ruby가 비면 지금처럼 text만이다.
        expect(child.textContent).toBe(segment.text)
        expect(child.childNodes).toEqual([])
        return
      }
      expect(child.textContent).toBe('')
      expect(child.childNodes.map(shape)).toEqual(
        segment.ruby.map((part) => (part.reading === null ? part.text : [part.text, part.reading])),
      )
    })
  })

  it('keeps every ruby wholly inside one tappable button or wholly outside any', () => {
    const sentence = renderRuby()

    const rubies = descendants(sentence).filter((node) => node.tagName === 'RUBY')
    expect(rubies).toHaveLength(READINGS.length)
    for (const ruby of rubies) {
      // ruby의 부모가 곧 segment 요소다. 버튼 경계를 넘거나 두 segment에 걸칠 자리가 없다.
      expect(sentence.children).toContain(ruby.parentNode)
    }
    RUBY_SEGMENTS.forEach((segment, index) => {
      const child = sentence.children[index]!
      expect(isTappable(child)).toBe(segment.sentence_item_id !== null)
      expect(textWithoutRt(child)).toBe(segment.text)
    })
  })

  it('leaves the tappable buttons, their count and text, the same as without ruby', () => {
    const withRuby = renderRuby().children.filter(isTappable)
    const without = renderWithoutRuby().children.filter(isTappable)

    expect(withRuby).toHaveLength(without.length)
    expect(withRuby.map(textWithoutRt)).toEqual(without.map((button) => button.textContent))
    expect(new Set(withRuby.map((button) => button.className))).toEqual(new Set(['token']))
  })

  it('passes the sentence_item_id when a button holding ruby is tapped, from the reading too', () => {
    const tapped: number[] = []
    const sentence = renderRuby((id) => tapped.push(id))

    for (const child of sentence.children.filter(isTappable)) child.click()
    // 읽기 요소에서 시작한 click도 버튼으로 올라간다. 버튼 밖 읽기(仕事, 田中)는 아무것도 부르지 않는다.
    for (const rt of rtOf(sentence)) rt.click()

    expect(tapped).toEqual([5511, 5512, 5513, 5511, 5513])
  })

  it('always creates rt, whatever the furigana class on the document is', () => {
    const root = (document as unknown as { documentElement: FakeElement }).documentElement

    root.classList.remove('furigana-on')
    const off = rtOf(renderRuby()).map((rt) => rt.textContent)
    root.classList.add('furigana-on')
    const on = rtOf(renderRuby()).map((rt) => rt.textContent)

    expect(off).toEqual(READINGS)
    expect(on).toEqual(READINGS)
  })
})
